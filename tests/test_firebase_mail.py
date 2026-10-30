import sqlite3
import pytest

import test_demo as demo
from test_demo import client,login
from deployment.demo_app import firebase_mail,communications
from deployment.demo_app.database import hash_password,verify_password


def prepare(client,con):
    con.execute("UPDATE doctor_profiles SET email='maya@example.invalid' WHERE username='dr.maya'")
    con.execute("INSERT INTO account_security(username,firebase_pending) VALUES('dr.maya',1)")


def test_firebase_setup_sends_a_link_without_password_or_gmail(monkeypatch):
    monkeypatch.setenv('FIREBASE_WEB_API_KEY','test-key')
    calls=[]
    monkeypatch.setattr(firebase_mail,'request',lambda action,payload:calls.append((action,payload)) or {'email':'new@example.invalid'})
    result=communications.send_credentials('new@example.invalid','dr.new','never-send-this-password')
    assert result['status']=='accepted' and result['password_setup']
    assert calls[1][0]=='sendOobCode' and calls[1][1]['requestType']=='PASSWORD_RESET'
    assert 'username=dr.new' in calls[1][1]['continueUrl']
    assert 'never-send-this-password' not in str(calls) and 'never-send-this-password' not in str(result)


def test_unverified_firebase_email_never_grants_doctor_access(monkeypatch):
    calls=[]
    def reply(action,payload):
        calls.append((action,payload))
        return {'idToken':'test-token'} if action=='signInWithPassword' else {'users':[{'email':'maya@example.invalid','emailVerified':False}]} if action=='lookup' else {}
    monkeypatch.setattr(firebase_mail,'request',reply)
    with pytest.raises(firebase_mail.MailError,match='EMAIL_VERIFICATION_REQUIRED'): firebase_mail.verify_login('maya@example.invalid','test-password')
    assert calls[-1][1]['requestType']=='VERIFY_EMAIL'


def test_registered_pending_doctor_can_sign_in_after_verified_setup(client,monkeypatch):
    with sqlite3.connect(demo.DB_PATH) as con: prepare(client,con)
    monkeypatch.setenv('FIREBASE_WEB_API_KEY','test-key')
    monkeypatch.setattr(firebase_mail,'verify_login',lambda email,password,username='':True)
    csrf=login(client,'dr.maya','new verified password 123')
    assert 'Patients under your care' in client.get('/doctor').text
    with sqlite3.connect(demo.DB_PATH) as con:
        row=con.execute("SELECT firebase_linked,firebase_pending FROM account_security WHERE username='dr.maya'").fetchone()
        assert row==(1,0)
        assert verify_password('new verified password 123',con.execute("SELECT password_hash FROM users WHERE username='dr.maya'").fetchone()[0])


def test_firebase_does_not_bypass_uninvited_or_inactive_accounts(client,monkeypatch):
    monkeypatch.setenv('FIREBASE_WEB_API_KEY','test-key')
    monkeypatch.setattr(firebase_mail,'verify_login',lambda *a:pytest.fail('Uninvited account attempted Firebase authentication'))
    client.get('/login/doctor');csrf=client.cookies.get('catatriage_csrf')
    response=client.post('/login',data={'username':'dr.maya','password':'firebase-only-password','csrf':csrf,'portal':'doctor'})
    assert 'Those credentials' in response.text
    with sqlite3.connect(demo.DB_PATH) as con:
        prepare(client,con);con.execute("UPDATE doctor_profiles SET is_active=0 WHERE username='dr.maya'")
    response=client.post('/login',data={'username':'dr.maya','password':'firebase-only-password','csrf':csrf,'portal':'doctor'})
    assert 'Those credentials' in response.text


def test_linked_account_password_change_updates_firebase_and_local_hash(client,monkeypatch):
    csrf=login(client)
    with sqlite3.connect(demo.DB_PATH) as con:
        prepare(client,con);con.execute("UPDATE account_security SET firebase_linked=1,firebase_pending=0 WHERE username='dr.maya'")
    calls=[]
    monkeypatch.setattr(firebase_mail,'change_password',lambda *args:calls.append(args))
    data={'csrf':csrf,'username':'dr.maya','current_password':'demo-doctor','new_password':'new safe password 123','confirmation':'new safe password 123'}
    assert client.post('/login/doctor/password',data=data).status_code==200
    assert calls==[('maya@example.invalid','demo-doctor','new safe password 123')]
