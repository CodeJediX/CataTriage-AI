"""Account email and consistent surgery notices; secrets stay server-side."""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from . import firebase_mail


def valid_email(value):
    return bool(re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+",value)) and len(value)<=254


def temporary_password():
    return secrets.token_urlsafe(24)


def generated_username(con,name):
    slug=re.sub(r"[^a-z0-9]+",".",re.sub(r"^dr\.?\s*","",name.lower())).strip(".")[:35] or "doctor"
    username="dr."+slug
    while con.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone():
        username="dr."+slug+"."+secrets.token_hex(3)
    return username


def _secret_value(name):
    value=os.getenv(name,"").strip()
    path=os.getenv(name+"_FILE","").strip()
    if not value and path:
        try: value=Path(path).read_text(encoding="utf-8-sig").strip()
        except OSError: return ""
    return value


def send_credentials(email,username,password):
    if firebase_mail.api_key(): return firebase_mail.send_setup(email,username)
    sender=os.getenv("ADMIN_EMAIL","pamindu39@gmail.com").strip()
    if not valid_email(email) or not valid_email(sender):
        return {"status":"failed","detail":"A valid sender and doctor email are required."}
    message=EmailMessage()
    message["From"]=sender; message["To"]=email
    message["Subject"]="Your CataTriage doctor account"
    message.set_content(f"Welcome to CataTriage.\n\nDoctor login: {os.getenv('CATATRIAGE_PUBLIC_URL','https://catatriage-ai.vercel.app').rstrip('/')}/login/doctor\nUsername: {username}\nTemporary password: {password}\n\nThis temporary password expires in 24 hours. Change it at first sign-in using the Change password option. Do not forward this email.\n\nHospital Administration")
    oauth=_secret_value("GMAIL_OAUTH_JSON")
    app_password=_secret_value("GMAIL_APP_PASSWORD").replace(" ","")
    if not oauth and not app_password:
        return {"status":"not_configured","detail":f"Doctor registered. Email was not sent: Gmail authorization for {sender} is not configured. Use Send new login email after setup."}
    try:
        if oauth:
            credentials=json.loads(oauth)
            token_body=urllib.parse.urlencode({"client_id":credentials["client_id"],"client_secret":credentials["client_secret"],"refresh_token":credentials["refresh_token"],"grant_type":"refresh_token"}).encode()
            with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token",data=token_body),timeout=12) as response:
                access=json.loads(response.read())["access_token"]
            body=json.dumps({"raw":base64.urlsafe_b64encode(message.as_bytes()).decode()}).encode()
            request=urllib.request.Request("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",data=body,headers={"Authorization":"Bearer "+access,"Content-Type":"application/json"})
            with urllib.request.urlopen(request,timeout=12) as response:
                if not json.loads(response.read()).get("id"): raise ValueError("Not accepted")
        else:
            with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=12,context=ssl.create_default_context()) as smtp:
                smtp.login(sender,app_password)
                if smtp.send_message(message): raise ValueError("Recipient refused")
        return {"status":"accepted","detail":"Gmail accepted the login email. Inbox delivery is not yet confirmed."}
    except Exception:
        return {"status":"failed","detail":"The login email could not be sent. Check Gmail authorization and use Send new login email to generate fresh credentials."}


def email_ready():
    return bool(firebase_mail.api_key() or _secret_value("GMAIL_OAUTH_JSON") or _secret_value("GMAIL_APP_PASSWORD"))


def email_provider():
    return 'Firebase password-setup email' if firebase_mail.api_key() else 'Gmail'


def surgery_message(name,day,slot):
    return f"Surgery Appointment Confirmation\n\nDear {name},\n\nYour surgery has been scheduled successfully.\n\nSurgery Details:\n\nPatient Name: {name}\n\nDate: {day}\n\nTime: {slot}\n\nPlease contact your doctor if you require any further information.\n\nThank you."


def whatsapp_link(phone,body):
    phone=re.sub(r"\D","",phone)
    return "https://wa.me/"+phone+"?text="+urllib.parse.quote(body) if 8<=len(phone)<=15 else None


def send_surgery_whatsapp(sender,recipient,name,day,slot):
    # Sending templates requires a verified Business sender and explicit provider
    # setup. It never substitutes another doctor's number or claims delivery.
    enabled=os.getenv("WHATSAPP_ENABLE","").lower() in {"1","true","yes"}
    config={}
    try:
        by_sender=json.loads(_secret_value("WHATSAPP_DOCTOR_CONFIG_JSON") or "{}")
        config=by_sender.get(re.sub(r"\D","",sender),{})
    except (ValueError,AttributeError): pass
    phone_id=config.get("phone_number_id") or os.getenv("WHATSAPP_PHONE_NUMBER_ID","")
    token=config.get("access_token") or os.getenv("WHATSAPP_ACCESS_TOKEN","")
    verified=config.get("sender_phone") or os.getenv("WHATSAPP_SENDER_PHONE","")
    template=config.get("template_name") or os.getenv("WHATSAPP_SURGERY_TEMPLATE","")
    version=config.get("graph_version") or os.getenv("WHATSAPP_GRAPH_VERSION","")
    if not enabled or not phone_id or not token or not template:
        return {"status":"stored_not_sent","detail":"Surgery confirmed. WhatsApp message saved, not sent: the approved Business template and sender credentials are not configured. The doctor can use Open WhatsApp to send it manually for free."}
    if not sender or re.sub(r"\D","",sender)!=re.sub(r"\D","",verified):
        return {"status":"stored_not_sent","detail":"Surgery confirmed; message not sent. This doctor's number must match a verified WhatsApp Business sender."}
    if not re.fullmatch(r"v\d+\.\d+",version) or not re.fullmatch(r"\d+",str(phone_id)) or not re.fullmatch(r"[a-z0-9_]+",template):
        return {"status":"stored_not_sent","detail":"Surgery confirmed; WhatsApp provider configuration needs review."}
    recipient=re.sub(r"\D","",recipient)
    if not 8<=len(recipient)<=15: return {"status":"failed","detail":"Surgery confirmed; a valid patient WhatsApp number is required to send the message."}
    data={"messaging_product":"whatsapp","to":recipient,"type":"template","template":{"name":template,"language":{"code":config.get("language") or os.getenv("WHATSAPP_TEMPLATE_LANGUAGE","en")},"components":[{"type":"body","parameters":[{"type":"text","text":value} for value in (name,name,day,slot)]}]}}
    request=urllib.request.Request(f"https://graph.facebook.com/{version}/{phone_id}/messages",data=json.dumps(data).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(request,timeout=12) as response: result=json.loads(response.read())
        if not result.get("messages"): raise ValueError("Not accepted")
        return {"status":"accepted","detail":"Surgery confirmed. WhatsApp accepted the template message from the doctor's verified Business number; delivery is not yet confirmed."}
    except Exception:
        return {"status":"failed","detail":"Surgery confirmed. WhatsApp did not accept the message; the saved message remains available for manual sending."}
