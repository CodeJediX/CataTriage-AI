import json
import sqlite3
from datetime import date
import pytest
import test_demo as demo
from test_demo import client,login,png_bytes
from deployment.demo_app import main,month_planning,planning_ai


@pytest.fixture(autouse=True)
def local_planning(monkeypatch):
    monkeypatch.setattr(planning_ai,'choose',lambda *args:{'provider':'local_planning_rules','provider_label':'Local planning checks','external_data_sent':False})


def month_draft(client,csrf,tier='Tier 3'):
    assert client.post('/doctor/review/DEMO-0001',data={'csrf':csrf,'decision':'approve','tier':tier,'reason':'Independent clinical assessment of functional impact.'}).status_code==200
    result=client.post('/api/mobile/patients/DEMO-0001/suggestion',data={'csrf':csrf,'symptoms':'Gradual blurred vision','notes':'Stable mild functional impact. Visual acuity recorded; biometry planned. Patient wants surgery.','functional_impact':'mild','progression':'stable','planning_preference':'later'})
    assert result.status_code==200,result.text
    return result.json()['suggestion']


def approve(client,csrf,draft,month=None):
    return client.post('/api/mobile/patients/DEMO-0001/month',data={'csrf':csrf,'approved_month':month or draft['suggested_month'],'reason':'Doctor assessed this elective month as appropriate.','attestation':'yes','evidence_hash':draft['evidence_hash'],**draft['assessment']})


def test_profile_image_and_username_preserve_ownership(client):
    csrf=login(client)
    assert client.get('/doctor/profile').status_code==200
    bad=client.post('/api/mobile/profile',data={'csrf':csrf,'username':'dr.maya','new_login_name':'doctor.maya','current_password':'wrong'})
    assert bad.status_code==400
    result=client.post('/api/mobile/profile',data={'csrf':csrf,'username':'dr.maya','new_login_name':'doctor.maya','current_password':'demo-doctor'},files={'profile_image':('me.png',png_bytes(),'image/png')})
    assert result.status_code==200 and result.json()['renamed']
    assert client.get('/api/mobile/me').status_code==401
    csrf=client.get('/api/mobile/bootstrap').json()['csrf']
    assert client.post('/api/mobile/login',data={'csrf':csrf,'username':'dr.maya','password':'demo-doctor'}).status_code==401
    csrf=client.get('/api/mobile/bootstrap').json()['csrf']
    assert client.post('/api/mobile/login',data={'csrf':csrf,'username':'doctor.maya','password':'demo-doctor'}).status_code==200
    me=client.get('/api/mobile/me').json()
    assert me['username']=='dr.maya' and me['login_name']=='doctor.maya'
    assert client.get('/api/mobile/profile/image').status_code==200
    assert client.get('/api/mobile/patients/DEMO-0001').status_code==200
    with sqlite3.connect(demo.DOCTOR_DB_PATH) as con: assert con.execute("SELECT doctor_username FROM patient_profiles WHERE case_id='DEMO-0001'").fetchone()[0]=='dr.maya'
    assert client.post('/api/mobile/password',data={'csrf':csrf,'username':'dr.maya','current_password':'demo-doctor','new_password':'a new private password 123','confirmation':'a new private password 123'}).status_code==200


def test_profile_change_is_scoped_unique_and_csrf_protected(client):
    csrf=login(client)
    data={'csrf':csrf,'username':'dr.maya','new_login_name':'dr.kamal','current_password':'demo-doctor'}
    assert client.post('/api/mobile/profile',data=data).status_code==409
    data.update(new_login_name='new.name',username='dr.kamal')
    assert client.post('/api/mobile/profile',data=data).status_code==403
    data.update(username='dr.maya',csrf='bad')
    assert client.post('/api/mobile/profile',data=data).status_code==403
    login(client,'admin.nila','demo-admin')
    assert client.get('/doctor/profile').status_code==403


def test_month_delays_depend_on_doctor_assessment_not_model_percentage(client):
    csrf=login(client);draft=month_draft(client,csrf)
    assert draft['suggested_month']>=month_planning.shift_month(date.today().strftime('%Y-%m'),3)
    assert draft['suggested_date'] is None
    with main.connection() as con:
        case=dict(main._case(con,'DEMO-0001'))
        first=month_planning.suggest_month({**case,'analysis_json':json.dumps({'confidence':.05})},con,'dr.maya',draft['assessment'])
        second=month_planning.suggest_month({**case,'analysis_json':json.dumps({'confidence':.99})},con,'dr.maya',draft['assessment'])
    assert first['suggested_month']==second['suggested_month']
    assert approve(client,csrf,draft).status_code==200
    page=client.get('/doctor/review/DEMO-0001')
    assert page.status_code==200 and 'Doctor-approved month' in page.text and 'type="date"' not in page.text


def test_month_approval_and_admin_booking_enforce_roles_and_boundaries(client,monkeypatch):
    sent=[]
    monkeypatch.setattr(main.communications,'send_surgery_whatsapp',lambda *args: sent.append(args) or {'status':'stored_not_sent','detail':'Isolated test.'})
    csrf=login(client);draft=month_draft(client,csrf)
    assert client.post('/doctor/review/DEMO-0001/surgery',data={'csrf':csrf,'surgery_date':'2030-01-01','slot':'09:00','rationale':'Doctor may not select a date.'}).status_code==403
    assert client.get('/admin/surgery').status_code==403
    assert approve(client,csrf,draft).status_code==200
    admin_csrf=login(client,'admin.nila','demo-admin')
    assert client.get('/admin/surgery/DEMO-0001').status_code==200
    assert client.post('/admin/surgery/DEMO-0001/assistant',data={'csrf':admin_csrf}).status_code==200
    with main.connection() as con: chosen=month_planning.free_slots(con,'dr.maya',draft['suggested_month'],'DEMO-0001')[0]
    form={'csrf':admin_csrf,'surgery_date':chosen['date'],'slot':chosen['slot'],'rationale':'Confirmed the approved month and available calendar.'}
    wrong={**form,'surgery_date':month_planning.shift_month(draft['suggested_month'],1)+'-01'}
    assert client.post('/admin/surgery/DEMO-0001/confirm',data=wrong).status_code==409
    first=client.post('/admin/surgery/DEMO-0001/confirm',data=form)
    assert first.status_code==200 and 'Surgery scheduled successfully' in first.text
    assert client.post('/admin/surgery/DEMO-0001/confirm',data=form).status_code==200
    assert len(sent)==1


def test_changed_evidence_revokes_month_approval(client):
    csrf=login(client);draft=month_draft(client,csrf);assert approve(client,csrf,draft).status_code==200
    client.post('/api/mobile/patients/DEMO-0001/notes',data={'csrf':csrf,'symptoms':'New severe eye pain','notes':'Prompt assessment required.'})
    assert approve(client,csrf,draft).status_code==409
    login(client,'admin.nila','demo-admin')
    assert client.get('/admin/surgery/DEMO-0001').status_code==409


def test_red_flags_and_unknown_assessment_do_not_yield_month(client):
    csrf=login(client)
    form={'csrf':csrf,'symptoms':'Sudden vision loss and severe eye pain','notes':'Assess now.','functional_impact':'mild','progression':'stable','planning_preference':'later'}
    result=client.post('/api/mobile/patients/DEMO-0001/suggestion',data=form).json()['suggestion']
    assert result['suggested_month'] is None and result['clinical_hold']
    form.update(symptoms='Gradual blurred vision',functional_impact='unknown')
    assert client.post('/api/mobile/patients/DEMO-0001/suggestion',data=form).json()['suggestion']['suggested_month'] is None


def test_changed_medical_history_requires_fresh_month_review(client):
    csrf=login(client);draft=month_draft(client,csrf);assert approve(client,csrf,draft).status_code==200
    with main.role_connection(main.DOCTOR_DB_PATH) as con:
        con.execute("UPDATE patient_profiles SET medical_history='Newly recorded ocular history requiring review.' WHERE case_id='DEMO-0001'")
    login(client,'admin.nila','demo-admin')
    assert client.get('/admin/surgery/DEMO-0001').status_code==409


def test_calendar_excludes_conflicting_consultation_and_leave(client):
    csrf=login(client);draft=month_draft(client,csrf)
    with main.connection() as con:
        selected=month_planning.free_slots(con,'dr.maya',draft['suggested_month'],'DEMO-0001')[0]
        con.execute("INSERT INTO appointments(case_id,scheduled_date,slot,service,created_by,created_at) VALUES(?,?,?,'Clinic','admin.nila','test') ON CONFLICT(case_id) DO UPDATE SET scheduled_date=excluded.scheduled_date,slot=excluded.slot",('DEMO-0003',selected['date'],selected['slot']))
        assert selected not in month_planning.free_slots(con,'dr.maya',draft['suggested_month'],'DEMO-0001')
        con.execute("INSERT INTO leave_requests(doctor_username,leave_date,leave_type,status,affected_count,created_at) VALUES('dr.maya',?,'full_day','approved',0,'test')",(selected['date'],))
        assert not any(x['date']==selected['date'] for x in month_planning.free_slots(con,'dr.maya',draft['suggested_month'],'DEMO-0001'))
