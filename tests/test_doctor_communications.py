import io
import json
import sqlite3
from urllib.parse import urlparse,parse_qs

import pytest
import test_demo as demo
from test_demo import client,login,future_workday,prepare_month_booking
from deployment.demo_app import communications,main
from deployment.demo_app.database import verify_password


def test_staff_inbox_sent_and_read_are_scoped_to_sender_and_recipient(client):
    csrf=login(client,"admin.nila","demo-admin")
    response=client.post("/messages/send",data={"csrf":csrf,"recipient":"staff:dr.maya","subject":"Leave update","body":"Your leave request needs review.","category":"leave"})
    assert response.status_code==200 and "Leave update" in response.text
    with sqlite3.connect(demo.DB_PATH) as con: message_id=con.execute("SELECT id FROM staff_messages").fetchone()[0]
    login(client,"dr.kamal")
    assert "Leave update" not in client.get("/doctor/inbox").text
    assert client.post(f"/messages/{message_id}/read",data={"csrf":csrf}).status_code==403
    login(client)
    assert "Leave update" in client.get("/doctor/inbox").text
    assert client.post(f"/messages/{message_id}/read",data={"csrf":csrf}).status_code==200
    response=client.post("/messages/send",data={"csrf":csrf,"recipient":"staff:dr.kamal","subject":"Team review","body":"Please review the clinic arrangements."})
    assert "Team review" in response.text
    assert client.post("/messages/send",data={"csrf":csrf,"recipient":"patient:DEMO-0002","subject":"Not mine","body":"Blocked."}).status_code==403
    assert client.post("/messages/send",data={"csrf":csrf,"recipient":"patient:DEMO-0001","subject":"Follow-up","body":"Please contact the clinic."}).status_code==200
    assert "Follow-up" in client.get("/doctor/inbox?box=sent").text
    login(client,"dr.kamal")
    assert "Team review" in client.get("/doctor/inbox").text
    assert "Follow-up" not in client.get("/doctor/inbox").text


def test_admin_broadcast_and_leave_notifications(client):
    csrf=login(client)
    day=future_workday(35)
    assert client.post("/doctor/leave",data={"csrf":csrf,"leave_date":day,"leave_type":"full_day"}).status_code==200
    with sqlite3.connect(demo.DB_PATH) as con: leave_id=con.execute("SELECT id FROM leave_requests").fetchone()[0]
    login(client,"admin.nila","demo-admin")
    assert "Doctor leave request" in client.get("/admin/messages").text
    client.post(f"/admin/leave/{leave_id}/status",data={"csrf":csrf,"status":"approved"})
    client.post("/messages/send",data={"csrf":csrf,"recipient":"staff:all_doctors","subject":"Clinic announcement","body":"The clinic opens at the usual time."})
    for doctor in ("dr.maya","dr.kamal"):
        login(client,doctor)
        assert "Clinic announcement" in client.get("/doctor/inbox").text
    login(client)
    assert "Leave request approved" in client.get("/doctor/inbox").text


def test_registration_generates_email_credentials_and_forces_change(client,monkeypatch):
    sent=[]
    def email(*args):
        sent.append(args)
        return {"status":"accepted","detail":"Email accepted for delivery."}
    monkeypatch.setattr(communications,"send_credentials",email)
    csrf=login(client,"admin.nila","demo-admin")
    response=client.post("/admin/doctors",data={"csrf":csrf,"display_name":"Dr New Colleague","email":"new@example.invalid","mobile":"+94771112222","work_start":"08:00","work_end":"16:00","working_days":["Mon","Tue","Wed","Thu","Fri"]})
    assert response.status_code==200 and len(sent)==1
    recipient,username,password=sent[0]
    assert recipient=="new@example.invalid" and username.startswith("dr.") and len(password)>=24
    assert password not in response.text
    with sqlite3.connect(demo.DB_PATH) as con:
        stored=con.execute("SELECT password_hash FROM users WHERE username=?",(username,)).fetchone()[0]
        assert verify_password(password,stored) and password not in stored
        assert password not in " ".join(row[0] for row in con.execute("SELECT details FROM audit_log"))
    login(client,username,password)
    assert "12 characters" in client.get("/doctor").text
    assert client.get("/doctor/inbox",follow_redirects=False).headers["location"]=="/login/doctor/password"
    assert client.post("/login/doctor/password",data={"csrf":csrf,"username":username,"current_password":password,"new_password":"a new safe passphrase 123","confirmation":"a new safe passphrase 123"}).status_code==200
    login(client,username,"a new safe passphrase 123")
    assert "Patients under your care" in client.get("/doctor").text


def test_password_change_requires_current_password_and_revokes_all_sessions(client):
    csrf=login(client)
    old=client.cookies.get("catatriage_session")
    data={"csrf":csrf,"username":"dr.maya","current_password":"wrong","new_password":"my new passphrase 321","confirmation":"my new passphrase 321"}
    assert client.post("/login/doctor/password",data=data).status_code==400
    data["current_password"]="demo-doctor"
    assert "Password changed successfully" in client.post("/login/doctor/password",data=data).text
    client.cookies.set("catatriage_session",old,domain="testserver.local",path="/")
    assert client.get("/doctor",follow_redirects=False).status_code==303
    login(client,"dr.maya","my new passphrase 321")
    assert client.get("/doctor").status_code==200


def test_password_attempts_are_rate_limited_and_csrf_required(client):
    csrf=login(client)
    data={"csrf":"wrong","username":"dr.maya","current_password":"wrong","new_password":"my new passphrase 321","confirmation":"my new passphrase 321"}
    assert client.post("/login/doctor/password",data=data).status_code==403
    data["csrf"]=csrf
    for _ in range(5): assert client.post("/login/doctor/password",data=data).status_code==400
    assert client.post("/login/doctor/password",data=data).status_code==429


def test_surgery_popup_template_and_duplicate_submission_do_not_send_twice(client,monkeypatch):
    sent=[]
    monkeypatch.setattr(communications,"send_surgery_whatsapp",lambda *args:sent.append(args) or {"status":"accepted","detail":"Provider accepted; delivery is not confirmed."})
    csrf=login(client)
    day=future_workday()
    data={"csrf":csrf,"surgery_date":day,"slot":"09:00","rationale":"Reviewed examination and patient agreement."}
    prepare_month_booking(client,day)
    response=client.post("/admin/surgery/DEMO-0001/confirm",data=data)
    assert response.status_code==200 and "Surgery scheduled successfully" in response.text
    assert "Provider accepted; delivery is not confirmed." in response.text
    assert len(sent)==1 and sent[0]==("+94772341180","+94 77 300 0001","Nethmi Perera",day,"09:00")
    assert "Dear Nethmi Perera," in response.text and f"Date: {day}" in response.text
    assert client.post("/admin/surgery/DEMO-0001/confirm",data=data).status_code==200 and len(sent)==1
    login(client)
    assert "Surgery Appointment Confirmation" in client.get("/doctor/inbox?box=sent").text
    token=parse_qs(urlparse(str(response.url)).query)["confirmation"][0]
    login(client,"dr.kamal")
    assert "surgery-confirmation-title" not in client.get("/calendar?confirmation="+token).text


def test_missing_provider_configuration_is_honest_and_template_is_exact(monkeypatch):
    for key in ("GMAIL_APP_PASSWORD","GMAIL_APP_PASSWORD_FILE","GMAIL_OAUTH_JSON","GMAIL_OAUTH_JSON_FILE","WHATSAPP_ENABLE"):
        monkeypatch.delenv(key,raising=False)
    assert communications.send_credentials("new@example.invalid","dr.new","test-only-password")["status"]=="not_configured"
    assert communications.send_surgery_whatsapp("+94770000000","+94771111111","Fictional","2026-12-01","09:00")["status"]=="stored_not_sent"
    message=communications.surgery_message("Fictional","2026-12-01","09:00")
    assert message=="Surgery Appointment Confirmation\n\nDear Fictional,\n\nYour surgery has been scheduled successfully.\n\nSurgery Details:\n\nPatient Name: Fictional\n\nDate: 2026-12-01\n\nTime: 09:00\n\nPlease contact your doctor if you require any further information.\n\nThank you."


def test_verified_whatsapp_template_payload_and_provider_acceptance(monkeypatch):
    for key,value in {"WHATSAPP_ENABLE":"true","WHATSAPP_PHONE_NUMBER_ID":"1234","WHATSAPP_ACCESS_TOKEN":"test-token","WHATSAPP_SENDER_PHONE":"+94770000000","WHATSAPP_SURGERY_TEMPLATE":"surgery_appointment_confirmation","WHATSAPP_GRAPH_VERSION":"v99.0"}.items(): monkeypatch.setenv(key,value)
    requests=[]
    monkeypatch.setattr(communications.urllib.request,"urlopen",lambda request,timeout:requests.append(request) or io.BytesIO(b'{"messages":[{"id":"test"}]}'))
    assert communications.send_surgery_whatsapp("+94770000001","+94771111111","Fictional","2026-12-01","09:00")["status"]=="stored_not_sent"
    assert requests==[]
    result=communications.send_surgery_whatsapp("+94770000000","+94771111111","Fictional","2026-12-01","09:00")
    assert result["status"]=="accepted"
    payload=json.loads(requests[0].data)
    assert payload["type"]=="template" and payload["template"]["name"]=="surgery_appointment_confirmation"
    assert [v["text"] for v in payload["template"]["components"][0]["parameters"]]==["Fictional","Fictional","2026-12-01","09:00"]


def test_email_uses_authorized_gmail_sender_and_keeps_credentials_out_of_status(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL","pamindu39@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD","test-app-password-only")
    monkeypatch.delenv("GMAIL_OAUTH_JSON",raising=False)
    monkeypatch.delenv("GMAIL_OAUTH_JSON_FILE",raising=False)
    sent=[]
    class SMTP:
        def __init__(self,host,port,timeout,context): assert (host,port)==("smtp.gmail.com",465)
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,sender,password): assert sender=="pamindu39@gmail.com" and password=="test-app-password-only"
        def send_message(self,message): sent.append(message); return {}
    monkeypatch.setattr(communications.smtplib,"SMTP_SSL",SMTP)
    result=communications.send_credentials("new@example.invalid","dr.new","private-test-password")
    assert result["status"]=="accepted" and "private-test-password" not in str(result)
    assert sent[0]["From"]=="pamindu39@gmail.com" and sent[0]["To"]=="new@example.invalid"
    assert "private-test-password" in sent[0].get_content() and "24 hours" in sent[0].get_content()


def test_failed_login_email_never_locks_out_existing_doctor(client,monkeypatch):
    csrf=login(client,"admin.nila","demo-admin")
    with sqlite3.connect(demo.DB_PATH) as con: con.execute("UPDATE doctor_profiles SET email='maya@example.invalid' WHERE username='dr.maya'")
    assert 'Email sending is not connected' in client.post("/admin/doctors/dr.maya/login-email",data={"csrf":csrf}).text
    monkeypatch.setattr(communications,"email_ready",lambda:True)
    monkeypatch.setattr(communications,"send_credentials",lambda *args:{"status":"failed","detail":"Not accepted."})
    result=client.post("/admin/doctors/dr.maya/login-email",data={"csrf":csrf})
    assert "Existing login credentials have not changed" in result.text
    login(client)
    assert "Patients under your care" in client.get("/doctor").text
