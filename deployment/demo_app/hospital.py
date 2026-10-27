from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, datetime

from fastapi import HTTPException

from .database import connection, now_iso
from .role_databases import DOCTOR_DB_PATH, role_connection


def require_assignment(user: dict, case_id: str):
    with role_connection(DOCTOR_DB_PATH) as con:
        patient = con.execute("SELECT * FROM patient_profiles WHERE case_id=?", (case_id,)).fetchone()
    if user['r'] == 'doctor' and (not patient or patient['doctor_username'] != user['u']):
        raise HTTPException(403, 'This patient is assigned to another doctor.')
    return patient


def validated_date(value: str, *, future: bool = True) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, 'Choose a valid date.')
    if future and parsed < date.today():
        raise HTTPException(400, 'Choose today or a future date.')
    return parsed


def valid_time(value: str) -> str:
    try:
        return datetime.strptime(value, '%H:%M').strftime('%H:%M')
    except ValueError:
        raise HTTPException(400, 'Use a valid time in HH:MM format.')


def leave_covers(kind: str, slot: str) -> bool:
    return kind == 'full_day' or (kind == 'morning' and '08:00' <= slot < '14:00') or (kind == 'evening' and '14:00' <= slot <= '23:00')


def doctor_available(con, username: str, day: str, slot: str) -> bool:
    parsed = date.fromisoformat(day)
    doctor = con.execute('SELECT * FROM doctor_profiles WHERE username=? AND is_active=1', (username,)).fetchone()
    if not doctor or parsed.strftime('%a') not in doctor['working_days'].split(','):
        return False
    if not doctor['work_start'] <= slot < doctor['work_end']:
        return False
    leaves = con.execute("SELECT leave_type FROM leave_requests WHERE doctor_username=? AND leave_date=? AND status IN ('pending','approved','resolved')", (username, day))
    return not any(leave_covers(row[0], slot) for row in leaves)


def affected_bookings(con, username: str, day: str, kind: str) -> list[dict]:
    with role_connection(DOCTOR_DB_PATH) as dcon:
        patients = {row['case_id']: dict(row) for row in dcon.execute('SELECT * FROM patient_profiles WHERE doctor_username=?', (username,))}
    result = []
    for table, date_column, event in [('appointments','scheduled_date','meeting'), ('surgeries','surgery_date','surgery')]:
        extra = " AND status='confirmed'" if table == 'surgeries' else ''
        for row in con.execute(f'SELECT * FROM {table} WHERE {date_column}=?{extra}', (day,)):
            if row['case_id'] in patients and leave_covers(kind, row['slot']):
                result.append({**patients[row['case_id']], **dict(row), 'event_type': event, 'event_date': day})
    return result


def reserve_surgery(con, case_id: str, day: str, slot: str, doctor: str, rationale: str):
    validated_date(day); valid_time(slot)
    if not doctor_available(con, doctor, day, slot):
        raise HTTPException(409, 'The assigned doctor is unavailable at this date and time. Choose another slot.')
    case = con.execute('SELECT approved_tier FROM cases WHERE case_id=?', (case_id,)).fetchone()
    if not case or not case[0]:
        raise HTTPException(409, 'Record an independent clinical review before confirming surgery.')
    capacity = con.execute('SELECT * FROM surgery_capacity WHERE id=1').fetchone()
    occupied = con.execute("SELECT COUNT(*) FROM surgeries WHERE surgery_date=? AND case_id<>? AND status='confirmed'", (day, case_id)).fetchone()[0]
    limit = min(capacity['max_surgeries_per_day'], capacity['available_beds'])
    if occupied >= limit:
        raise HTTPException(409, f'Surgery schedule is full for {day}. Theatre/bed limit: {limit}. Choose another date.')
    con.execute("""INSERT INTO surgeries(case_id,surgery_date,slot,status,confirmed_by,rationale,created_at)
        VALUES(?,?,?,'confirmed',?,?,?) ON CONFLICT(case_id) DO UPDATE SET surgery_date=excluded.surgery_date,
        slot=excluded.slot,status='confirmed',confirmed_by=excluded.confirmed_by,rationale=excluded.rationale""",
        (case_id, day, slot, doctor, rationale, now_iso()))


def send_whatsapp(sender: str, recipient: str, body: str) -> dict:
    enabled = os.getenv('WHATSAPP_ENABLE', '').lower() in {'1','true','yes'}
    phone_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '').strip()
    access_token = os.getenv('WHATSAPP_ACCESS_TOKEN', '').strip()
    # A Cloud API sender must be verified with Meta. It cannot impersonate a
    # doctor's arbitrary personal WhatsApp account.
    configured_sender = re.sub(r'\D', '', os.getenv('WHATSAPP_SENDER_PHONE', ''))
    if not enabled or not phone_id or not access_token:
        return {'status': 'stored_not_sent', 'detail': 'Message saved. WhatsApp Business credentials are not configured.'}
    if not configured_sender or configured_sender != re.sub(r'\D', '', sender):
        return {'status': 'stored_not_sent', 'detail': 'Message saved. The doctor number does not match the verified WhatsApp Business sender.'}
    recipient = re.sub(r'\D', '', recipient)
    if not 8 <= len(recipient) <= 15:
        return {'status': 'failed', 'detail': 'The patient needs a valid WhatsApp number.'}
    version = os.getenv('WHATSAPP_GRAPH_VERSION', '').strip()
    if not re.fullmatch(r'v\d+\.\d+', version):
        return {'status': 'stored_not_sent', 'detail': 'Set the supported Meta Graph API version in configuration.'}
    payload = json.dumps({'messaging_product': 'whatsapp', 'to': recipient, 'type': 'text', 'text': {'body': body}}).encode()
    req = urllib.request.Request(f'https://graph.facebook.com/{version}/{phone_id}/messages', data=payload,
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read())
        if not data.get('messages'): raise ValueError('No message accepted')
        return {'status': 'accepted', 'detail': 'WhatsApp accepted the message. Delivery is not yet confirmed.'}
    except Exception:
        return {'status': 'failed', 'detail': 'WhatsApp could not accept the message. It remains in communication history.'}
