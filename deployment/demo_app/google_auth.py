from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .database import audit, connection, now_iso

router = APIRouter()


def enabled() -> bool:
    return all(os.getenv(key) for key in ("GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GOOGLE_REDIRECT_URI"))


@router.get("/auth/google")
def google_start():
    if not enabled(): raise HTTPException(503,"Google sign-in needs the hospital OAuth client configuration.")
    from .main import _sign
    raw = secrets.token_urlsafe(28)+"."+str(int(time.time())+600)
    state = raw+"."+_sign(raw)
    params = urllib.parse.urlencode({"client_id":os.environ["GOOGLE_CLIENT_ID"],"redirect_uri":os.environ["GOOGLE_REDIRECT_URI"],
        "response_type":"code","scope":"openid email profile","state":state,"prompt":"select_account"})
    response=RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+params,status_code=303)
    response.set_cookie("google_oauth_state",state,httponly=True,samesite="lax",max_age=600)
    return response


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    from .main import _sign, make_session
    import hmac
    expected=request.cookies.get("google_oauth_state","")
    try:
        raw,signature=state.rsplit(".",1)
        if not expected or not hmac.compare_digest(state,expected) or not hmac.compare_digest(signature,_sign(raw)) or int(raw.rsplit(".",1)[1])<time.time():
            raise ValueError()
    except Exception:
        raise HTTPException(400,"Google sign-in session expired or does not match this browser.")
    if error or not code: raise HTTPException(400,"Google sign-in was cancelled.")
    if not enabled(): raise HTTPException(503,"Google sign-in is not configured.")
    body=urllib.parse.urlencode({"code":code,"client_id":os.environ["GOOGLE_CLIENT_ID"],"client_secret":os.environ["GOOGLE_CLIENT_SECRET"],
        "redirect_uri":os.environ["GOOGLE_REDIRECT_URI"],"grant_type":"authorization_code"}).encode()
    try:
        req=urllib.request.Request("https://oauth2.googleapis.com/token",data=body,headers={"Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req,timeout=12) as response: tokens=json.loads(response.read())
        # Google validates the ID token signature and returns its verified claims.
        with urllib.request.urlopen("https://oauth2.googleapis.com/tokeninfo?"+urllib.parse.urlencode({"id_token":tokens["id_token"]}),timeout=12) as response:
            claims=json.loads(response.read())
        if claims["aud"]!=os.environ["GOOGLE_CLIENT_ID"] or claims["iss"] not in {"accounts.google.com","https://accounts.google.com"} or int(claims["exp"])<time.time() or str(claims.get("email_verified","")).lower()!="true":
            raise ValueError()
    except Exception:
        raise HTTPException(400,"Google identity could not be verified. Please try signing in again.")
    with connection() as con:
        identity=con.execute("SELECT u.* FROM google_identities g JOIN users u USING(username) JOIN doctor_profiles d USING(username) WHERE g.subject=? AND d.is_active=1",(claims["sub"],)).fetchone()
        if not identity:
            identity=con.execute("SELECT u.* FROM users u JOIN doctor_profiles d USING(username) WHERE lower(d.google_email)=? AND d.is_active=1",(claims["email"].lower(),)).fetchone()
            if identity:
                con.execute("INSERT INTO google_identities(subject,username) VALUES(?,?)",(claims["sub"],identity["username"]))
        if not identity:
            con.execute("INSERT OR REPLACE INTO google_access_requests(subject,email,display_name,requested_at) VALUES(?,?,?,?)",
                (claims["sub"],claims["email"],claims.get("name","Doctor"),now_iso()))
            response=RedirectResponse("/login/doctor?google_status=pending",status_code=303)
        else:
            audit(con,identity["username"],identity["role"],"google_login",None,"Verified Google identity signed in.")
            response=RedirectResponse("/doctor",status_code=303)
            response.set_cookie("catatriage_session",make_session(identity["username"],identity["role"],identity["display_name"]),httponly=True,samesite="strict",max_age=28800,secure=request.url.scheme=="https")
    response.delete_cookie("google_oauth_state")
    return response
