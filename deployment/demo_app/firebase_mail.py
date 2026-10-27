"""Free Firebase password-setup mail; application access stays doctor-scoped."""
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.request
import urllib.parse


class MailError(Exception):
    pass


def api_key():
    value=os.getenv('FIREBASE_WEB_API_KEY','').strip()
    path=os.getenv('FIREBASE_MAIL_CONFIG_FILE','')
    if not value and path:
        try: value=json.loads(Path(path).read_text(encoding='utf-8'))['api_key']
        except (OSError,ValueError,KeyError): return ''
    return value


def request(action,payload):
    key=api_key()
    if not key: raise MailError('NOT_CONFIGURED')
    req=urllib.request.Request(f'https://identitytoolkit.googleapis.com/v1/accounts:{action}?key={key}',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=15) as response: return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try: code=json.loads(exc.read(16384)).get('error',{}).get('message','FAILED').split(' : ')[0]
        except (ValueError,AttributeError): code='FAILED'
        raise MailError(code) from None
    except Exception: raise MailError('UNAVAILABLE') from None


def send_setup(email,username):
    try:
        try:
            request('signUp',{'email':email,'password':secrets.token_urlsafe(32),'returnSecureToken':False})
        except MailError as exc:
            if str(exc)!='EMAIL_EXISTS': raise
        continue_url=os.getenv('CATATRIAGE_PUBLIC_URL','https://catatriage-ai.vercel.app').rstrip('/')+'/login/doctor?username='+urllib.parse.quote(username)
        request('sendOobCode',{'requestType':'PASSWORD_RESET','email':email,'continueUrl':continue_url})
        return {'status':'accepted','provider':'firebase','password_setup':True,'detail':f'Firebase accepted the password-setup email for {username}. Choose a password using its secure link, then Continue to the doctor portal. If prompted, verify the email before signing in. Check Inbox and Spam. Existing login credentials remain unchanged until setup is completed.'}
    except MailError as exc:
        code=str(exc)
        if code in {'TOO_MANY_ATTEMPTS_TRY_LATER','RESET_PASSWORD_EXCEED_LIMIT','QUOTA_EXCEEDED'}:
            detail='The free Firebase email limit was reached. Please try again later.'
        elif code in {'OPERATION_NOT_ALLOWED','CONFIGURATION_NOT_FOUND','API_KEY_INVALID'}:
            detail='Firebase email configuration needs attention.'
        else: detail='Firebase could not accept the setup email. Check the address or try again later.'
        return {'status':'failed','provider':'firebase','password_setup':True,'detail':detail+' Existing login credentials have not changed.'}


def verify_login(email,password,username=''):
    token=request('signInWithPassword',{'email':email,'password':password,'returnSecureToken':True})
    users=request('lookup',{'idToken':token['idToken']}).get('users',[])
    if len(users)!=1 or users[0].get('email','').lower()!=email.lower(): raise MailError('INVALID_LOGIN_CREDENTIALS')
    if not users[0].get('emailVerified'):
        request('sendOobCode',{'requestType':'VERIFY_EMAIL','idToken':token['idToken'],'continueUrl':os.getenv('CATATRIAGE_PUBLIC_URL','https://catatriage-ai.vercel.app').rstrip('/')+'/login/doctor?username='+urllib.parse.quote(username)})
        raise MailError('EMAIL_VERIFICATION_REQUIRED')
    return True


def change_password(email,current_password,new_password):
    token=request('signInWithPassword',{'email':email,'password':current_password,'returnSecureToken':True})
    result=request('update',{'idToken':token['idToken'],'password':new_password,'returnSecureToken':False})
    if result.get('email','').lower()!=email.lower(): raise MailError('INVALID_LOGIN_CREDENTIALS')
