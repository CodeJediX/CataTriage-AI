import json
import sqlite3
from fastapi.testclient import TestClient
import test_demo as demo
from test_demo import client


def signin(client,username="dr.maya",password="demo-doctor"):
    csrf=client.get('/api/mobile/bootstrap').json()['csrf']
    result=client.post('/api/mobile/login',data={'username':username,'password':password,'csrf':csrf})
    return csrf,result


def test_native_login_and_role_boundaries(client):
    assert client.get('/api/mobile/me',follow_redirects=False).status_code==401
    csrf,bad=signin(client,'admin.nila','demo-admin')
    assert bad.status_code==401
    assert client.get('/api/mobile/workspace').status_code==401
    csrf,ok=signin(client)
    assert ok.status_code==200 and ok.json()['signed_in']
    assert client.get('/api/mobile/me').json()['username']=='dr.maya'
    workspace=client.get('/api/mobile/workspace').json()
    assert workspace['patients']
    assert all(p['doctor_username']=='dr.maya' for p in workspace['patients'])
    own=workspace['patients'][0]['case_id']
    patient=client.get('/api/mobile/patients/'+own)
    assert patient.status_code==200
    assert 'image_path' not in patient.json()['case']
    own_ids={p['case_id'] for p in workspace['patients']}
    with sqlite3.connect(demo.DOCTOR_DB_PATH) as con:
        other=con.execute("SELECT case_id FROM patient_profiles WHERE doctor_username<>'dr.maya' LIMIT 1").fetchone()[0]
    assert other not in own_ids
    assert client.get('/api/mobile/patients/'+other).status_code==403
    demo.login(client,'admin.nila','demo-admin')
    assert client.get('/api/mobile/me').status_code==403


def test_native_csrf_notes_review_and_mailbox(client):
    csrf,_=signin(client)
    case_id=client.get('/api/mobile/workspace').json()['patients'][0]['case_id']
    base='/api/mobile/patients/'+case_id
    assert client.post(base+'/notes',data={'symptoms':'Blurred vision'}).status_code==422
    assert client.post(base+'/notes',data={'symptoms':'Blurred vision','csrf':'wrong'}).status_code==403
    assert client.post(base+'/notes',data={'symptoms':'Blurred vision','notes':'Needs examination','csrf':csrf}).status_code==200
    assert client.get(base).json()['case']['notes']=='Needs examination'
    assert client.post(base+'/review',data={'decision':'approve','tier':'','reason':'Independent clinical assessment','csrf':csrf}).status_code==400
    assert client.post(base+'/review',data={'decision':'approve','tier':'Tier 2','reason':'Independent clinical assessment','csrf':csrf}).status_code==200
    assert client.get(base).json()['case']['approved_tier']=='Tier 2'
    assert client.post('/api/mobile/messages',data={'recipient':'staff:admin.nila','subject':'Clinic update','body':'Isolated test message','csrf':csrf}).status_code==200
    sent=client.get('/api/mobile/mailbox?box=sent').json()['messages']
    assert any(m['subject']=='Clinic update' for m in sent)
    assert client.get('/api/mobile/mailbox?box=bad').status_code==400
    assert client.post('/api/mobile/logout',data={'csrf':csrf}).status_code==200
    assert client.get(base,follow_redirects=False).status_code==401


def test_native_temp_password_guard_and_revocation(client):
    from deployment.demo_app import account_security
    from deployment.demo_app.main import connection
    csrf,_=signin(client)
    with connection() as con: account_security.changed(con,'dr.maya',temporary=True)
    assert client.get('/api/mobile/workspace').status_code==401
    csrf,_=signin(client)
    assert client.get('/api/mobile/me').json()['must_change']
    assert client.get('/api/mobile/workspace').status_code==403
    assert client.post('/api/mobile/password',data={'username':'dr.maya','current_password':'demo-doctor','new_password':'DifferentPassword17!','confirmation':'DifferentPassword17!','csrf':csrf}).status_code==200
    assert client.get('/api/mobile/me').status_code==401
    csrf,ok=signin(client,password='DifferentPassword17!')
    assert ok.status_code==200
    assert client.get('/api/mobile/workspace').status_code==200


def test_native_image_intake_keeps_unknown_empty(client,monkeypatch):
    from deployment.demo_app import main
    monkeypatch.setattr(main.real_provider,'analyze_fusion',lambda *args:{'status':'ok','top_class':'Cataract','confidence':.7,'probabilities':{'Cataract':.7,'Other':.3},'requires_clinician_review':True})
    csrf,_=signin(client)
    case_id=client.get('/api/mobile/workspace').json()['patients'][0]['case_id']
    response=client.post('/api/mobile/intake',data={'case_id':case_id,'modality':'slit_lamp','symptoms':'Blurry vision','notes':'Test examination','csrf':csrf},files=[('left_images',('left.png',demo.png_bytes(),'image/png')),('right_images',('right.png',demo.png_bytes(),'image/png'))])
    assert response.status_code==200,response.text
    record=client.get('/api/mobile/patients/'+case_id).json()
    assert len(record['images'])==2
    assert {image['eye_side'] for image in record['images']}=={'Left','Right'}
    assert {entry['side'] for entry in record['eye_summary']['entries']}=={'Left','Right'}
    assert len(record['images'][0]['analysis']['agent_workflow'])==4
    assert client.get('/api/mobile/images/'+str(record['images'][0]['id'])).status_code==200


def test_native_surgery_advisory_does_not_book(client,monkeypatch):
    from deployment.demo_app import main
    monkeypatch.setattr(main,'suggest_surgery_date',lambda *args:{'provider':'local_rules','suggested_date':None,'clinical_hold':True,'reason':'Clinical assessment required'})
    csrf,_=signin(client)
    case_id=client.get('/api/mobile/workspace').json()['patients'][0]['case_id']
    result=client.post('/api/mobile/patients/'+case_id+'/suggestion',data={'symptoms':'Severe eye pain','notes':'Assess promptly','csrf':csrf})
    assert result.status_code==200 and result.json()['suggestion']['clinical_hold']
    with sqlite3.connect(demo.DB_PATH) as con: assert not con.execute('SELECT 1 FROM surgeries WHERE case_id=?',(case_id,)).fetchone()
    result=client.post('/api/mobile/patients/'+case_id+'/surgery',data={'surgery_date':'1999-01-01','slot':'09:00','rationale':'Independent clinical assessment','csrf':csrf})
    assert result.status_code==403
    assert 'error' in result.json()


def test_native_chunk_upload_cannot_cross_user_or_form(client,monkeypatch,tmp_path):
    from deployment.demo_app import cloud_database, main, file_store
    from types import SimpleNamespace
    csrf,_=signin(client)
    case_id=client.get('/api/mobile/workspace').json()['patients'][0]['case_id']
    with main.connection() as con:
        con.executescript('CREATE TABLE pending_uploads(id TEXT PRIMARY KEY,owner_name TEXT,action_path TEXT,target_id TEXT,field_name TEXT,original_name TEXT,expected_size INTEGER,expires_at INTEGER); CREATE TABLE upload_chunks(upload_id TEXT,chunk_index INTEGER,content BLOB,PRIMARY KEY(upload_id,chunk_index));')
    blob=tmp_path/'blobs.sqlite3'
    with main.connection(blob) as con: con.execute('CREATE TABLE file_objects(object_key TEXT PRIMARY KEY,content BLOB)')
    monkeypatch.setattr(cloud_database,'enabled',lambda:True)
    monkeypatch.setattr(cloud_database,'connection',lambda namespace='hospital':main.connection({'doctor':main.DOCTOR_DB_PATH,'technician':main.TECHNICIAN_DB_PATH}.get(namespace)))
    monkeypatch.setattr(file_store,'cloud_database',SimpleNamespace(enabled=lambda:True,connection=lambda:main.connection(blob)))
    monkeypatch.setattr(file_store,'APP_DIR',main.APP_DIR)
    monkeypatch.setattr(main.real_provider,'analyze_fusion',lambda *args:{'status':'not_available','reason':'Isolated upload test','urgency':None})
    payload=demo.png_bytes();headers={'X-CSRF-Token':csrf}
    spec={'action':'/api/mobile/intake','target':case_id,'field':'unknown_images','name':'original.png','size':len(payload)}
    assert client.post('/api/mobile/uploads/prepare',json=spec,headers={'X-CSRF-Token':'wrong'}).status_code==403
    prepared=client.post('/api/mobile/uploads/prepare',json=spec,headers=headers)
    assert prepared.status_code==200
    identifier=prepared.json()['id']
    assert client.post(f'/api/mobile/uploads/{identifier}/chunks/0',content=payload,headers=headers).status_code==200
    form={'case_id':case_id,'modality':'slit_lamp','csrf':csrf,'cloud_uploads':json.dumps([identifier])}
    assert client.post('/intake',data=form).status_code==403
    assert client.post('/api/mobile/intake',data=form).status_code==200
    record=client.get('/api/mobile/patients/'+case_id).json()
    assert [i['eye_side'] for i in record['images']]==['Not recorded']
    with main.connection(blob) as con: assert bytes(con.execute('SELECT content FROM file_objects').fetchone()[0])==payload
    with main.connection() as con: assert con.execute('SELECT COUNT(*) FROM pending_uploads').fetchone()[0]==0


def test_native_doctor_cannot_bypass_admin_date_selection(client,monkeypatch):
    from deployment.demo_app import main
    sent=[]
    monkeypatch.setattr(main.communications,'send_surgery_whatsapp',lambda *args:sent.append(args))
    csrf,_=signin(client)
    result=client.post('/api/mobile/patients/DEMO-0001/surgery',data={'surgery_date':'2030-01-01','slot':'09:00','rationale':'Independent clinical assessment','csrf':csrf})
    assert result.status_code==403 and not sent
