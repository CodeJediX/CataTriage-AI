import sqlite3

import test_demo as demo
from test_demo import client,login,prepare_month_booking,future_workday
from deployment.demo_app.database import hash_password


def test_admin_edits_patient_in_both_stores_and_doctor_cannot_edit(client):
    csrf=login(client,'admin.nila','demo-admin')
    data={'csrf':csrf,'full_name':'Updated Patient','age':61,'phone':'+94771111111','email':'patient@example.invalid','address':'Updated address','doctor_username':'dr.maya'}
    result=client.post('/admin/patients/DEMO-0001/edit',data=data)
    assert result.status_code==200 and 'Updated Patient' in result.text
    with sqlite3.connect(demo.DB_PATH) as con: assert con.execute("SELECT patient_alias,age FROM cases WHERE case_id='DEMO-0001'").fetchone()==('Updated Patient',61)
    with sqlite3.connect(demo.DOCTOR_DB_PATH) as con: assert con.execute("SELECT full_name,address FROM patient_profiles WHERE case_id='DEMO-0001'").fetchone()==('Updated Patient','Updated address')
    login(client)
    assert client.post('/admin/patients/DEMO-0001/edit',data=data).status_code==403


def test_delete_patient_hides_case_and_cancels_future_bookings_but_preserves_records(client):
    csrf=login(client)
    day=future_workday()
    prepare_month_booking(client,day)
    client.post('/admin/surgery/DEMO-0001/confirm',data={'csrf':csrf,'surgery_date':day,'slot':'09:00','rationale':'Fictional clinical review for workflow testing.'})
    login(client,'admin.nila','demo-admin')
    result=client.post('/admin/accounts/patient/DEMO-0001/delete',data={'csrf':csrf})
    assert result.status_code==200
    with sqlite3.connect(demo.DB_PATH) as con:
        assert con.execute("SELECT is_archived FROM cases WHERE case_id='DEMO-0001'").fetchone()[0]==1
        assert con.execute("SELECT status FROM surgeries WHERE case_id='DEMO-0001'").fetchone()[0]=='cancelled'
        assert con.execute("SELECT COUNT(*) FROM account_archives WHERE entity_key='DEMO-0001'").fetchone()[0]==1
    login(client)
    assert client.get('/cases/DEMO-0001').status_code==403
    assert 'Nethmi Perera' not in client.get('/doctor').text
    assert 'Nethmi Perera' not in client.get('/calendar?kind=surgery&month='+day[:7]).text
    login(client,'admin.nila','demo-admin')
    restored=client.post('/admin/accounts/patient/DEMO-0001/restore',data={'csrf':csrf,'doctor_username':'dr.maya'})
    assert restored.status_code==200 and 'Nethmi Perera' in restored.text
    with sqlite3.connect(demo.DB_PATH) as con: assert con.execute("SELECT status FROM surgeries WHERE case_id='DEMO-0001'").fetchone()[0]=='cancelled'


def test_delete_doctor_requires_transfer_and_invalidates_existing_sessions(client):
    csrf=login(client)
    old=client.cookies.get('catatriage_session')
    login(client,'admin.nila','demo-admin')
    with sqlite3.connect(demo.DB_PATH) as con:
        con.execute("UPDATE doctor_profiles SET work_start='08:00',working_days='Mon,Tue,Wed,Thu,Fri,Sat,Sun' WHERE username='dr.kamal'")
    assert client.post('/admin/accounts/doctor/dr.maya/delete',data={'csrf':csrf}).status_code==409
    result=client.post('/admin/accounts/doctor/dr.maya/delete',data={'csrf':csrf,'reassign_to':'dr.kamal'})
    assert result.status_code==200
    with sqlite3.connect(demo.DOCTOR_DB_PATH) as con: assert con.execute("SELECT COUNT(*) FROM patient_profiles WHERE doctor_username='dr.maya'").fetchone()[0]==0
    client.cookies.set('catatriage_session',old,domain='testserver.local',path='/')
    assert client.get('/doctor',follow_redirects=False).status_code==303
    login(client,'admin.nila','demo-admin')
    assert client.post('/admin/accounts/doctor/dr.maya/restore',data={'csrf':csrf}).status_code==200
    client.cookies.set('catatriage_session',old,domain='testserver.local',path='/')
    assert client.get('/doctor',follow_redirects=False).status_code==303
    login(client)
    assert client.get('/doctor').status_code==200


def test_transfer_conflict_rolls_back_all_account_changes(client):
    csrf=login(client)
    day=future_workday()
    prepare_month_booking(client,day)
    client.post('/admin/surgery/DEMO-0001/confirm',data={'csrf':csrf,'surgery_date':day,'slot':'09:00','rationale':'Fictional clinical review for workflow testing.'})
    login(client,'admin.nila','demo-admin')
    result=client.post('/admin/accounts/doctor/dr.maya/delete',data={'csrf':csrf,'reassign_to':'dr.kamal'})
    assert result.status_code==409
    with sqlite3.connect(demo.DB_PATH) as con:
        assert con.execute("SELECT is_active FROM doctor_profiles WHERE username='dr.maya'").fetchone()[0]==1
        assert con.execute("SELECT COUNT(*) FROM account_archives").fetchone()[0]==0
    with sqlite3.connect(demo.DOCTOR_DB_PATH) as con: assert con.execute("SELECT doctor_username FROM patient_profiles WHERE case_id='DEMO-0001'").fetchone()[0]=='dr.maya'


def test_deletion_and_restore_require_admin_and_csrf(client):
    csrf=login(client)
    for endpoint in ('delete','restore'):
        assert client.post('/admin/accounts/patient/DEMO-0001/'+endpoint,data={'csrf':csrf}).status_code==403
    login(client,'admin.nila','demo-admin')
    assert client.post('/admin/accounts/patient/DEMO-0001/delete',data={'csrf':'invalid'}).status_code==403


def test_login_identity_uses_provided_logo_and_hides_requested_banner(client,monkeypatch):
    monkeypatch.setenv('CATATRIAGE_HOSTED','true')
    page=client.get('/login')
    assert '/static/catatriage-logo.png' in page.text and 'optical-orbit' in page.text
    assert 'Education demo.' not in page.text and 'Use fictional patient information.' not in page.text
    assert 'Pause animation' in page.text
    assert client.get('/static/catatriage-logo.png').status_code==200
