"""Atomic profile changes and reversible deletion across the role stores."""
import json
from datetime import date

from fastapi import HTTPException

from . import cloud_database,account_security
from .database import now_iso
from .hospital import doctor_available


def doctor_store(con,path):
    if cloud_database.enabled(): return 'catatriage_doctor'
    con.execute('ATTACH DATABASE ? AS doctor_portal',(str(path),))
    return 'doctor_portal'


def validate_transfer(con,case_id,doctor):
    if not con.execute('SELECT 1 FROM doctor_profiles WHERE username=? AND is_active=1',(doctor,)).fetchone():
        raise HTTPException(400,'Choose an active doctor.')
    for table,column in (('appointments','scheduled_date'),('surgeries','surgery_date')):
        extra=" AND status='confirmed'" if table=='surgeries' else ''
        for row in con.execute(f'SELECT {column},slot FROM {table} WHERE case_id=? AND {column}>=?{extra}',(case_id,date.today().isoformat())):
            if not doctor_available(con,doctor,row[0],row[1]):
                raise HTTPException(409,f'The selected doctor is unavailable for the existing booking on {row[0]} at {row[1]}. Reschedule it or choose another doctor.')


def archive(con,kind,key,actor,state):
    con.execute('''INSERT INTO account_archives(entity_type,entity_key,archived_by,archived_at,previous_state) VALUES(?,?,?,?,?)
        ON CONFLICT(entity_type,entity_key) DO UPDATE SET archived_by=excluded.archived_by,archived_at=excluded.archived_at,previous_state=excluded.previous_state,restored_at=NULL''',
        (kind,key,actor,now_iso(),json.dumps(state)))


def delete_patient(con,case_id,actor):
    row=con.execute('SELECT status,is_archived FROM cases WHERE case_id=?',(case_id,)).fetchone()
    if not row: raise HTTPException(404,'Patient not found.')
    if row['is_archived']: return
    upcoming=[dict(item) for item in con.execute('SELECT * FROM appointments WHERE case_id=? AND scheduled_date>=?',(case_id,date.today().isoformat()))]
    archive(con,'patient',case_id,actor,{'status':row['status'],'appointments':upcoming})
    con.execute('UPDATE cases SET is_archived=1 WHERE case_id=?',(case_id,))
    con.execute("UPDATE surgeries SET status='cancelled' WHERE case_id=? AND surgery_date>=? AND status='confirmed'",(case_id,date.today().isoformat()))
    con.execute('DELETE FROM appointments WHERE case_id=? AND scheduled_date>=?',(case_id,date.today().isoformat()))


def delete_doctor(con,store,username,reassign_to,actor):
    doctor=con.execute('SELECT is_active FROM doctor_profiles WHERE username=?',(username,)).fetchone()
    if not doctor: raise HTTPException(404,'Doctor not found.')
    if not doctor[0]: return
    patients=con.execute(f'SELECT p.case_id FROM {store}.patient_profiles p JOIN cases c USING(case_id) WHERE p.doctor_username=? AND c.is_archived=0',(username,)).fetchall()
    if patients:
        if not reassign_to or reassign_to==username: raise HTTPException(409,'Reassign this doctor’s active patients before deleting the account.')
        for patient in patients: validate_transfer(con,patient[0],reassign_to)
        for patient in patients:
            con.execute(f'UPDATE {store}.patient_profiles SET doctor_username=? WHERE case_id=?',(reassign_to,patient[0]))
    archive(con,'doctor',username,actor,{'transferred_patients':[p[0] for p in patients],'reassigned_to':reassign_to})
    con.execute('UPDATE doctor_profiles SET is_active=0 WHERE username=?',(username,))
    account_security.invalidate_sessions(con,username)


def restore(con,kind,key):
    row=con.execute('SELECT * FROM account_archives WHERE entity_type=? AND entity_key=? AND restored_at IS NULL',(kind,key)).fetchone()
    if not row: raise HTTPException(404,'Deleted record not found.')
    if kind=='patient':
        state=json.loads(row['previous_state'])
        status=state.get('status','registered')
        if status=='scheduled': status='awaiting_review'
        con.execute('UPDATE cases SET is_archived=0,status=? WHERE case_id=?',(status,key))
    elif kind=='doctor':
        con.execute('UPDATE doctor_profiles SET is_active=1 WHERE username=?',(key,))
        account_security.invalidate_sessions(con,key)
    else: raise HTTPException(400,'Unknown account type.')
    con.execute('UPDATE account_archives SET restored_at=? WHERE entity_type=? AND entity_key=?',(now_iso(),kind,key))
