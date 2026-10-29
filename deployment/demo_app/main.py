from __future__ import annotations

import base64
import calendar as month_calendar
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import DB_PATH, DOCTOR_IMAGE_DIR, UPLOAD_DIR, audit, connection, hash_password, initialize_database, now_iso, reset_database, verify_password
from .model_provider import ImageValidationError, MODEL_ID, provider, validate_image_bytes
from .real_models import real_provider
from .eye_summary import summarize_eyes, partition_images
from .role_databases import DOCTOR_DB_PATH, TECHNICIAN_DB_PATH, initialize_role_databases, role_connection, sync_doctor_directory
from .lazy_synthetic import GRADE_NAMES, synthetic_provider
from .advisory import suggest_surgery_date
from .hospital import affected_bookings, doctor_available, leave_covers, require_assignment, reserve_surgery, send_whatsapp, validated_date, valid_time
from .google_auth import enabled as google_enabled, router as google_router
from .settings import load_local_config, advisory_settings
from agents.workflow import run_workflow
from . import cloud_database, file_store
from . import account_security, communications, account_management, firebase_mail
from .cloud_uploads import router as upload_router, restore as restore_uploads
from .mobile_api import router as mobile_router
from .enhancements import router as enhancements_router
from . import doctor_account, month_planning, surgery_alerts
from .clinical_planning import clinical_review, clinical_context

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parents[1]
REPORT_DIR = ROOT / "reports" / "model_evaluation_v3"
EVIDENCE_DIR = ROOT / "output" / "pdf"
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
SECRET_PATH = APP_DIR / "data" / ".session_secret"
MAX_AGE_SECONDS = 8 * 60 * 60
load_local_config()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    initialize_role_databases()
    sync_doctor_directory()
    yield


app = FastAPI(
    title="CataTriage-AI Demo",
    description="Research and competition workflow prototype.",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(google_router)
app.include_router(upload_router)
app.include_router(mobile_router)
app.include_router(enhancements_router)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


async def _image_upload(request, image, field="image", required=True):
    restored=await restore_uploads(request)
    uploads=restored.get(field,[])
    if uploads:
        if image and image.filename or len(uploads)!=1: raise HTTPException(400,"Select one image for this action.")
        image=uploads[0]
    if required and (not image or not image.filename): raise HTTPException(400,"Select an image.")
    return image


def _secret() -> bytes:
    configured=os.getenv("CATATRIAGE_SESSION_SECRET", "")
    if configured:
        if len(configured)<32: raise RuntimeError("Session secret must contain at least 32 characters.")
        return configured.encode()
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="ascii")
    return SECRET_PATH.read_text(encoding="ascii").strip().encode()


def _sign(data: str) -> str:
    return hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()


def make_session(username: str, role: str, display_name: str) -> str:
    with connection() as con:
        epoch=account_security.state(con,username)["password_epoch"]
    payload = {"u": username, "r": role, "n": display_name, "v":epoch, "exp": int(datetime.now().timestamp()) + MAX_AGE_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def read_session(request: Request) -> dict | None:
    if hasattr(request.state,"verified_session"): return request.state.verified_session
    token = request.cookies.get("catatriage_session", "")
    try:
        raw, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, _sign(raw)):
            return None
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        if data["exp"] < int(datetime.now().timestamp()):
            return None
        with connection() as con:
            user=con.execute("SELECT role FROM users WHERE username=?",(data["u"],)).fetchone()
            security=account_security.state(con,data["u"])
            profile=con.execute("SELECT is_active FROM doctor_profiles WHERE username=?",(data["u"],)).fetchone() if data["r"]=="doctor" else None
        if not user or user[0]!=data["r"] or data.get("v",0)!=security["password_epoch"] or (profile and not profile[0]): return None
        if security["must_change"] and security["temporary_expires"]<time.time(): return None
        data["must_change"]=bool(security["must_change"])
        with connection() as con: data["login_name"]=doctor_account.login_name(con,data["u"])
        request.state.verified_session=data
        return data
    except Exception:
        return None


@app.middleware("http")
async def first_login_password_change(request: Request,call_next):
    if request.cookies.get("catatriage_session") and not request.url.path.startswith(("/static/","/login","/logout","/api/mobile/")):
        user=read_session(request)
        if user and user.get("must_change"): return RedirectResponse("/login/doctor/password",status_code=303)
    response=await call_next(request)
    if request.url.path.startswith('/api/mobile/'):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
    return response


def ensure_csrf(request: Request) -> str:
    return request.cookies.get("catatriage_csrf") or secrets.token_urlsafe(24)


def verify_csrf(request: Request, value: str) -> None:
    expected = request.cookies.get("catatriage_csrf", "")
    if not expected or not hmac.compare_digest(expected, value or ""):
        raise HTTPException(403, "Invalid or missing form token. Refresh and try again.")


def require_user(request: Request, role: str | None = None) -> dict:
    user = read_session(request)
    if not user:
        raise HTTPException(401, "Sign in required")
    if role and user["r"] != role:
        raise HTTPException(403, f"{role.title()} role required")
    return user


def redirect_login(next_path: str = "/") -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(next_path)}", status_code=303)


def render(request: Request, name: str, **context) -> HTMLResponse:
    csrf = ensure_csrf(request)
    response_status = int(context.pop("response_status", 200))
    user = read_session(request)
    auth_page = request.url.path.startswith('/login')
    pending_count = len(surgery_alerts.for_request(request, user)) if user and not auth_page else 0
    response = templates.TemplateResponse(request, name, {"user": user, "csrf": csrf, "today": date.today(),
        "pending_surgery_count":pending_count,
        "auth_page":auth_page,
        "google_enabled":google_enabled(), "google_pending":request.query_params.get("google_status")=="pending",
        "hosted":os.getenv("CATATRIAGE_HOSTED")=="true", "ephemeral":os.getenv("CATATRIAGE_EPHEMERAL")=="true",
        "cloud_database":cloud_database.enabled(), **context}, status_code=response_status)
    if not request.cookies.get("catatriage_csrf"):
        response.set_cookie("catatriage_csrf", csrf, httponly=True, samesite="strict", secure=request.url.scheme=="https")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers={"Cache-Control":"no-store"})
    if exc.status_code == 401:
        return redirect_login(request.url.path)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
    return render(request, "error.html", response_status=exc.status_code, status_code=exc.status_code, message=str(exc.detail))


@app.exception_handler(ImageValidationError)
async def invalid_image_error(request: Request, exc: ImageValidationError):
    if request.url.path.startswith("/api/mobile/"):
        return JSONResponse({"error":str(exc)},status_code=400)
    return render(request,"error.html",response_status=400,status_code=400,message=str(exc))


@app.get("/health")
def health() -> dict:
    scheduling=advisory_settings()
    return {"status": "ok", "app": "catatriage-demo", "model_id": MODEL_ID, "model_device": provider.device_label,
            "scheduling_provider":scheduling["provider"],"scheduling_model":scheduling["model"],
            "scheduling_fallback_models":scheduling.get("fallback_models",[]),
            "scheduling_configured":bool(scheduling["enabled"] and scheduling["api_key"] and scheduling["base_url"]),
            "persistent_database":"supabase_postgres" if cloud_database.enabled() else "local_sqlite",
            "real_multidata_available": (ROOT / "models" / "cataract_grade_multidata_real" / "best_model.pt").exists(),
            "real_fusion_available": (ROOT / "models" / "clinical_fusion_catscreen_real" / "best_model.pt").exists()}


@app.get('/android',response_class=HTMLResponse)
def android_download_page(request:Request):
    manifest=ROOT/'output/android/release.json'
    if not manifest.exists(): raise HTTPException(404,'Android release is being prepared.')
    release=json.loads(manifest.read_text())
    return render(request,'android.html',release=release)


@app.get('/downloads/{filename}')
def android_apk(filename:str):
    if filename not in {'CataTriage-Doctor-1.0.0.apk','CataTriage-Doctor-1.1.0.apk'}: raise HTTPException(404,'Android release not found.')
    from fastapi.responses import FileResponse
    artifact=ROOT/'output/android'/filename
    if not artifact.exists(): raise HTTPException(404,'Android APK is being prepared.')
    return FileResponse(artifact,media_type='application/vnd.android.package-archive',filename=artifact.name,headers={'Cache-Control':'public,max-age=3600','X-Content-Type-Options':'nosniff'})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return render(request, "login.html", next_path=next, error=None, portal=None)


@app.get("/login/{portal}", response_class=HTMLResponse)
def role_login_page(request: Request, portal: str, next: str = ""):
    if portal not in {"doctor", "admin", "technician"}:
        raise HTTPException(404, "Unknown portal")
    default_next = {"doctor":"/doctor", "admin":"/admin", "technician":"/support"}[portal]
    return render(request, "login.html", next_path=next or default_next, error=None, portal=portal, login_username=request.query_params.get("username",""))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...), next_path: str = Form("/"), portal: str = Form("")):
    verify_csrf(request, csrf)
    with connection() as con:
        username=username.strip().lower()
        key=account_security.attempt_key(request,username)
        if account_security.blocked(con,key): return render(request,"login.html",next_path=next_path,error="Too many attempts. Try again in 15 minutes.",portal=portal or None,response_status=429)
        canonical=doctor_account.resolve_login(con,username)
        row = con.execute("SELECT * FROM users WHERE username=?", (canonical,)).fetchone()
        username=canonical or username
        security=account_security.state(con,username)
        profile=con.execute("SELECT is_active,email FROM doctor_profiles WHERE username=?",(username,)).fetchone() if row and row["role"]=="doctor" else None
        password_ok=bool(row and verify_password(password,row['password_hash']))
        if row and profile and profile[0] and profile['email'] and firebase_mail.api_key() and (security['firebase_linked'] or (security['firebase_pending'] and not password_ok)):
            try:
                firebase_mail.verify_login(profile['email'],password,username)
                if not password_ok or security['firebase_pending'] or security['must_change']:
                    con.execute('UPDATE users SET password_hash=? WHERE username=?',(hash_password(password),username))
                    account_security.changed(con,username,temporary=len(password.strip())<12)
                    con.execute('UPDATE account_security SET firebase_linked=1,firebase_pending=0 WHERE username=?',(username,))
                    security=account_security.state(con,username)
                password_ok=True
            except firebase_mail.MailError as exc:
                account_security.failed(con,key)
                detail='Open the Firebase verification email, verify your address, then sign in again.' if str(exc)=='EMAIL_VERIFICATION_REQUIRED' else 'The email sign-in could not be verified. Check your password or try again later.'
                return render(request,'login.html',next_path=next_path,error=detail,portal=portal or 'doctor',login_username=username)
        if not row or not password_ok or (portal and row["role"] != portal) or (profile and not profile[0]) or (security["must_change"] and security["temporary_expires"]<time.time()):
            account_security.failed(con,key)
            return render(request, "login.html", next_path=next_path, error="Those credentials do not match this role portal.", portal=portal or None)
        con.execute("DELETE FROM authentication_attempts WHERE attempt_key=?",(key,))
        audit(con, row["username"], row["role"], "login", None, "Demo account signed in.")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    response = RedirectResponse("/login/doctor/password" if security["must_change"] else next_path, status_code=303)
    response.set_cookie("catatriage_session", make_session(row["username"], row["role"], row["display_name"]), httponly=True, samesite="strict", max_age=MAX_AGE_SECONDS, secure=request.url.scheme=="https")
    return response


@app.get("/login/doctor/password",response_class=HTMLResponse)
def password_page(request: Request):
    return render(request,"password_change.html",error=None,success=False)


@app.post("/login/doctor/password",response_class=HTMLResponse)
def change_doctor_password(request: Request,username:str=Form(...,max_length=80),current_password:str=Form(...,max_length=128),new_password:str=Form(...,max_length=128),confirmation:str=Form(...,max_length=128),csrf:str=Form(...)):
    verify_csrf(request,csrf)
    if len(new_password)<12 or new_password!=confirmation or new_password==current_password:
        return render(request,"password_change.html",error="Use a different password of at least 12 characters and match both new-password fields.",success=False,response_status=400)
    username=username.strip().lower()
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        key=account_security.attempt_key(request,username)
        if account_security.blocked(con,key): return render(request,"password_change.html",error="Too many attempts. Try again in 15 minutes.",success=False,response_status=429)
        username=doctor_account.resolve_login(con,username) or username
        row=con.execute("SELECT u.*,d.email FROM users u JOIN doctor_profiles d USING(username) WHERE u.username=? AND u.role='doctor' AND d.is_active=1",(username,)).fetchone()
        security=account_security.state(con,username)
        if not row or not verify_password(current_password,row["password_hash"]) or (security["must_change"] and security["temporary_expires"]<time.time()):
            account_security.failed(con,key)
            return render(request,"password_change.html",error="The current credentials could not be verified. Expired temporary passwords require a new login email from the admin.",success=False,response_status=400)
        if security['firebase_linked']:
            try: firebase_mail.change_password(row['email'],current_password,new_password)
            except firebase_mail.MailError: return render(request,'password_change.html',error='The email account could not be updated. Sign in with your latest emailed password setup first, or try again later. Your application password has not changed.',success=False,response_status=400)
        con.execute("UPDATE users SET password_hash=? WHERE username=?",(hash_password(new_password),username))
        account_security.changed(con,username)
        con.execute("DELETE FROM authentication_attempts WHERE attempt_key=?",(key,))
        audit(con,username,"doctor","password_changed",None,"Doctor verified the current password and set a new password; existing sessions revoked.")
    response=render(request,"password_change.html",error=None,success=True)
    response.delete_cookie("catatriage_session")
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    verify_csrf(request, csrf)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("catatriage_session")
    return response


@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    if not read_session(request):
        return redirect_login("/")
    with connection() as con:
        counts = dict(con.execute("SELECT status,COUNT(*) n FROM cases WHERE is_archived=0 GROUP BY status").fetchall())
        tiers = {r[0] or "Pending": r[1] for r in con.execute("SELECT approved_tier,COUNT(*) FROM cases WHERE is_archived=0 GROUP BY approved_tier")}
        cases = con.execute("SELECT *, CAST(julianday('now')-julianday(waiting_since) AS INTEGER) wait_days FROM cases WHERE is_archived=0 ORDER BY wait_days DESC LIMIT 7").fetchall()
        appointments = con.execute("SELECT a.*,c.patient_alias FROM appointments a JOIN cases c USING(case_id) WHERE c.is_archived=0 ORDER BY scheduled_date LIMIT 5").fetchall()
    return render(request, "overview.html", page="overview", counts=counts, tiers=tiers, cases=cases, appointments=appointments)


@app.get("/cases", response_class=HTMLResponse)
def cases_page(request: Request, q: str = "", modality: str = "", tier: str = "", status: str = ""):
    if not read_session(request):
        return redirect_login("/cases")
    clauses, params = ["is_archived=0"], []
    if q:
        clauses.append("(case_id LIKE ? OR patient_alias LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    if modality:
        clauses.append("modality=?"); params.append(modality)
    if tier:
        clauses.append("COALESCE(approved_tier,'Pending')=?"); params.append(tier)
    if status:
        clauses.append("status=?"); params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connection() as con:
        rows = con.execute(f"SELECT *, CAST(julianday('now')-julianday(waiting_since) AS INTEGER) wait_days FROM cases{where} ORDER BY wait_days DESC", params).fetchall()
    return render(request, "cases.html", page="cases", cases=rows, filters={"q":q,"modality":modality,"tier":tier,"status":status})


@app.get("/cases/new", response_class=HTMLResponse)
def new_case_page(request: Request):
    user = read_session(request)
    if not user:
        return redirect_login("/cases/new")
    with role_connection(DOCTOR_DB_PATH) as con:
        patients = con.execute('SELECT * FROM patient_profiles WHERE doctor_username=? ORDER BY full_name', (user['u'],)).fetchall() if user['r']=='doctor' else con.execute('SELECT * FROM patient_profiles ORDER BY full_name').fetchall()
    active=_active_case_ids()
    patients=[patient for patient in patients if patient['case_id'] in active]
    return render(request, 'intake.html', page='new', patients=patients)


@app.post("/cases/new")
async def new_case(
    request: Request, case_id: str = Form(...), patient_alias: str = Form(...), age: int = Form(...), eye: str = Form(...),
    modality: str = Form(...), symptoms: str = Form(""), notes: str = Form(""), illumination_type: str = Form("Diffuse Illumination"),
    reflection: int = Form(0), csrf: str = Form(...), image: UploadFile | None = File(None)
):
    user = require_user(request); verify_csrf(request, csrf)
    if user['r'] == 'doctor':
        raise HTTPException(403, 'Select a registered patient from New intake.')
    case_id = case_id.strip().upper()
    if not case_id.startswith("DEMO-") or len(case_id) > 20:
        return render(request, "new_case.html", page="new", error="Use a fictional ID beginning with DEMO-.")
    if modality not in {"fundus", "slit_lamp"} or eye not in {"Left","Right","Both","Not recorded"} or not (1 <= age <= 110):
        raise HTTPException(400, "Invalid case fields")
    image=await _image_upload(request,image,required=False)
    payload = await image.read() if image and image.filename else b""
    image_path = image_hash = None
    analysis = None
    if payload:
        pil_image, image_meta = validate_image_bytes(payload)
        ext = {"JPEG":"jpg", "PNG":"png", "WEBP":"webp"}[image_meta["format"]]
        filename = f"{uuid4().hex}.{ext}"
        target = UPLOAD_DIR / filename
        file_store.write(target,payload)
        image_path = str(target.relative_to(APP_DIR)).replace("\\", "/")
        image_hash = hashlib.sha256(payload).hexdigest()
        context = {"eye_side": eye if eye in {"Left", "Right"} else "Not recorded", "reflection": int(bool(reflection)),
                   "slit_lamp_illumination_type": illumination_type}
        inference = provider.analyze if modality == "fundus" else lambda data, kind: real_provider.analyze_fusion(data, kind, context)
        analysis = run_workflow(payload, modality, image_meta, inference)
    with connection() as con:
        try:
            con.execute("""INSERT INTO cases(case_id,patient_alias,age,eye,modality,status,created_at,waiting_since,symptoms,notes,image_path,image_sha256,analysis_status,analysis_json)
                VALUES(?,?,?,?,?,'awaiting_review',datetime('now'),date('now'),?,?,?,?,?,?)""",
                (case_id, patient_alias.strip(), age, eye, modality, symptoms.strip(), notes.strip(), image_path, image_hash, analysis["status"] if analysis else "not_run", json.dumps(analysis) if analysis else None))
        except Exception as exc:
            if image_path:
                file_store.delete(APP_DIR / image_path)
            if "UNIQUE" in str(exc):
                return render(request, "new_case.html", page="new", error="That fictional case ID already exists.")
            raise
        audit(con, user["u"], user["r"], "case_created", case_id, f"Created fictional {modality} demo case.")
        if payload:
            audit(con, user["u"], user["r"], "image_upload", case_id, f"Stored validated {image_meta['format']} image as generated filename; sha256={image_hash}.")
            audit(con, user["u"], user["r"], "model_inference" if analysis.get("status") == "ok" else "model_not_available", case_id, f"status={analysis['status']}; model={analysis.get('model_id','none')}; urgency=null")
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


def _active_case_ids():
    with connection() as con: return {row[0] for row in con.execute('SELECT case_id FROM cases WHERE is_archived=0')}


def _case(con, case_id: str):
    row = con.execute("SELECT c.*,a.scheduled_date,a.slot,a.service FROM cases c LEFT JOIN appointments a USING(case_id) WHERE c.case_id=?", (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Case not found")
    return row


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: str):
    if not read_session(request):
        return redirect_login(request.url.path)
    require_assignment(read_session(request), case_id)
    with connection() as con:
        row = _case(con, case_id)
        history = con.execute("SELECT * FROM audit_log WHERE case_id=? ORDER BY id DESC", (case_id,)).fetchall()
        images = [dict(r) for r in con.execute('SELECT * FROM case_images WHERE case_id=? ORDER BY id DESC', (case_id,))]
        for item in images:
            item["analysis"] = json.loads(item["analysis_json"]) if item["analysis_json"] else None
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    current_images,older_images=partition_images(images,analysis)
    return render(request, 'case_detail.html', page='cases', case=row, history=history, analysis=analysis, images=current_images, older_images=older_images,
                  eye_summary=summarize_eyes(images, analysis))


@app.post("/cases/{case_id}/analysis")
async def analyze_case(request: Request, case_id: str, modality: str = Form(...), illumination_type: str = Form("Diffuse Illumination"),
                       reflection: int = Form(0), csrf: str = Form(...), image: UploadFile | None = File(None), eye_side: str = Form("Not recorded")):
    user = require_user(request); verify_csrf(request, csrf)
    require_assignment(user, case_id)
    image=await _image_upload(request,image)
    with connection() as con:
        row = _case(con, case_id)
    if modality != row["modality"]:
        raise HTTPException(400, "Selected modality must match the registered case modality.")
    if eye_side not in {"Left", "Right", "Not recorded"}:
        raise HTTPException(400, "Choose left, right, or eye side unknown.")
    payload = await image.read(8*1024*1024+1)
    pil_image, image_meta = validate_image_bytes(payload)
    context = {"eye_side": eye_side, "reflection": int(bool(reflection)),
               "slit_lamp_illumination_type": illumination_type}
    inference = provider.analyze if modality == "fundus" else lambda data, kind: real_provider.analyze_fusion(data, kind, context)
    result = run_workflow(payload, modality, image_meta, inference)
    result.update(eye_side=eye_side, observation_group=uuid4().hex)
    ext = {"JPEG":"jpg", "PNG":"png", "WEBP":"webp"}[image_meta["format"]]
    filename = f"{uuid4().hex}.{ext}"
    target = UPLOAD_DIR / filename
    file_store.write(target,payload)
    digest = hashlib.sha256(payload).hexdigest()
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute("SELECT image_path FROM cases WHERE case_id=?", (case_id,)).fetchone()[0]
        con.execute("UPDATE cases SET image_path=?,image_sha256=?,analysis_status=?,analysis_json=? WHERE case_id=?",
                    (str(target.relative_to(APP_DIR)).replace("\\", "/"), digest, result["status"], json.dumps(result), case_id))
        audit(con, user["u"], user["r"], "image_upload", case_id, f"Stored validated image as generated filename; sha256={digest}.")
        audit(con, user["u"], user["r"], "model_inference" if result.get("status") == "ok" else "model_not_available", case_id,
              f"status={result['status']}; model={result.get('model_id','none')}; urgency=null")
        con.execute("INSERT INTO case_images(case_id,eye_side,image_path,image_sha256,analysis_json,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (case_id,eye_side,str(target.relative_to(APP_DIR)).replace(chr(92),"/"),digest,json.dumps(result),user["u"],now_iso()))
        _sync_case_eye(con, case_id)
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


@app.get("/doctor/review/{case_id}", response_class=HTMLResponse)
def review_page(request: Request, case_id: str):
    try: user = require_user(request, "doctor")
    except HTTPException as exc:
        if exc.status_code == 401: return redirect_login(request.url.path)
        raise
    require_assignment(user, case_id)
    with connection() as con:
        row = _case(con, case_id)
        surgery = con.execute("SELECT * FROM surgeries WHERE case_id=?", (case_id,)).fetchone()
        capacity = con.execute("SELECT * FROM surgery_capacity WHERE id=1").fetchone()
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    from .enhancements import month_context
    return render(request, "clinical_review.html", page="review", case=row, analysis=analysis, reviewer=user, surgery=surgery, capacity=capacity, suggestion=None, booking_error=None, **month_context(__import__(__name__,fromlist=["app"]),user,dict(row)))


@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, q: str = "", scope: str = "mine", message_status: str = ""):
    try:
        user = require_user(request, "doctor")
    except HTTPException as exc:
        if exc.status_code == 401:
            return redirect_login("/doctor")
        raise
    clauses, params = ["p.doctor_username=?"], [user["u"]]
    if q:
        clauses.append("(p.full_name LIKE ? OR p.case_id LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with role_connection(DOCTOR_DB_PATH) as con:
        patients = con.execute(f"SELECT * FROM patient_profiles p{where} ORDER BY full_name", params).fetchall()
        directory = con.execute("SELECT * FROM doctor_directory ORDER BY display_name").fetchall()
        messages = con.execute("SELECT * FROM messages WHERE recipient=? OR sender=? ORDER BY id DESC LIMIT 8", (user["u"], user["u"])).fetchall()
        assessments = con.execute("SELECT a.* FROM self_assessments a JOIN patient_profiles p USING(case_id) WHERE p.doctor_username=? ORDER BY a.id DESC LIMIT 8",(user["u"],)).fetchall()
        notifications = con.execute("SELECT * FROM notifications WHERE doctor_username=? ORDER BY is_read,due_date", (user["u"],)).fetchall()
    with connection() as con:
        appointments = con.execute("SELECT a.*,c.patient_alias FROM appointments a JOIN cases c USING(case_id) WHERE scheduled_date>=? ORDER BY scheduled_date,slot",(date.today().isoformat(),)).fetchall()
        profile = con.execute("SELECT * FROM doctor_profiles WHERE username=?", (user["u"],)).fetchone()
        leaves = con.execute("SELECT * FROM leave_requests WHERE doctor_username=? ORDER BY leave_date DESC", (user["u"],)).fetchall()
        inbox=con.execute("SELECT * FROM staff_messages WHERE recipient=? ORDER BY id DESC LIMIT 4",(user["u"],)).fetchall()
        unread=con.execute("SELECT COUNT(*) FROM staff_messages WHERE recipient=? AND read_at IS NULL",(user["u"],)).fetchone()[0]
    active=_active_case_ids()
    patients=[p for p in patients if p['case_id'] in active]
    with connection() as con: active_doctors={row[0] for row in con.execute('SELECT username FROM doctor_profiles WHERE is_active=1')}
    directory=[d for d in directory if d['username'] in active_doctors]
    ids = {p["case_id"] for p in patients}
    appointments = [a for a in appointments if a["case_id"] in ids]
    assessments = [a for a in assessments if a["case_id"] in ids]
    return render(request, "doctor_workspace.html", page="doctor", patients=patients, directory=directory, messages=messages,
                  assessments=assessments, notifications=notifications, appointments=appointments, filters={"q":q,"scope":scope}, profile=profile, leaves=leaves, message_status=message_status,inbox=inbox,unread=unread)


def _staff_message(con,sender,recipient,subject,body,category="announcement",case_id=None):
    con.execute("INSERT INTO staff_messages(sender,recipient,subject,body,category,case_id,created_at) VALUES(?,?,?,?,?,?,?)",(sender,recipient,subject,body,category,case_id,now_iso()))


@app.get("/doctor/inbox",response_class=HTMLResponse)
@app.get("/admin/messages",response_class=HTMLResponse)
def mailbox(request:Request,box:str="inbox"):
    user=require_user(request,"admin" if request.url.path.startswith("/admin/") else "doctor")
    if box not in {"inbox","sent"}: raise HTTPException(400,"Choose Inbox or Sent.")
    with connection() as con:
        staff=[dict(row) for row in con.execute("SELECT u.username,u.display_name,u.role FROM users u LEFT JOIN doctor_profiles d USING(username) WHERE u.role='admin' OR (u.role='doctor' AND d.is_active=1) ORDER BY u.display_name")]
        column="recipient" if box=="inbox" else "sender"
        messages=[dict(row) for row in con.execute(f"SELECT * FROM staff_messages WHERE {column}=? ORDER BY id DESC LIMIT 100",(user["u"],))]
        unread=con.execute("SELECT COUNT(*) FROM staff_messages WHERE recipient=? AND read_at IS NULL",(user["u"],)).fetchone()[0]
        if box=="sent" and user["r"]=="doctor":
            for row in con.execute("SELECT * FROM outbound_notifications WHERE doctor_username=? ORDER BY id DESC LIMIT 100",(user["u"],)):
                messages.append({**dict(row),"id":None,"sender":user["u"],"recipient":row["case_id"],"subject":"Surgery Appointment Confirmation","category":"surgery","read_at":"outbound","delivery_channel":"whatsapp"})
    with role_connection(DOCTOR_DB_PATH) as con:
        patients=[dict(row) for row in con.execute("SELECT * FROM patient_profiles WHERE doctor_username=? ORDER BY full_name",(user["u"],))] if user["r"]=="doctor" else []
        active=_active_case_ids()
        patients=[patient for patient in patients if patient['case_id'] in active]
        if user["r"]=="doctor":
            legacy=con.execute(f"SELECT * FROM messages WHERE {column}=? ORDER BY id DESC LIMIT 100",(user["u"],)).fetchall()
            assigned={patient["case_id"] for patient in patients}
            for row in legacy:
                if row["case_id"] in assigned:
                    messages.append({**dict(row),"id":None,"subject":"Patient message","category":"patient","created_at":row["sent_at"],"read_at":"legacy"})
    messages.sort(key=lambda row:row["created_at"],reverse=True)
    return render(request,"mailbox.html",page="inbox",box=box,messages=messages[:100],staff=staff,patients=patients,unread=unread,status=request.query_params.get("status",""),mailbox_path=request.url.path)


@app.post("/messages/send")
def send_mailbox_message(request:Request,recipient:str=Form(...),subject:str=Form(...,min_length=2,max_length=120),body:str=Form(...,min_length=2,max_length=5000),category:str=Form("announcement"),case_id:str=Form(""),csrf:str=Form(...)):
    user=require_user(request); verify_csrf(request,csrf)
    if user["r"] not in {"doctor","admin"}: raise HTTPException(403,"Doctor or administrator required.")
    if not subject.strip() or len(body.strip())<2: raise HTTPException(400,"Enter a subject and message.")
    if category not in {"announcement","leave","patient","other"}: raise HTTPException(400,"Choose a valid message category.")
    if recipient.startswith("patient:"):
        if user["r"]!="doctor": raise HTTPException(403,"Only the assigned doctor may send this patient message.")
        case_id=recipient.removeprefix("patient:")
        patient=require_assignment(user,case_id)
        with role_connection(DOCTOR_DB_PATH) as con:
            con.execute("INSERT INTO messages(case_id,sender,recipient,body,sent_at,delivery_channel,delivery_status) VALUES(?,?,?,?,?,'local','stored')",(case_id,user["u"],case_id,subject.strip()+"\n\n"+body.strip(),now_iso()))
    elif recipient.startswith("staff:"):
        target=recipient.removeprefix("staff:")
        if case_id: require_assignment(user,case_id)
        with connection() as con:
            valid=con.execute("SELECT u.username FROM users u LEFT JOIN doctor_profiles d USING(username) WHERE u.username=? AND (u.role='admin' OR (u.role='doctor' AND d.is_active=1))",(target,)).fetchone()
            targets=[row[0] for row in con.execute("SELECT username FROM doctor_profiles WHERE is_active=1")] if target=="all_doctors" and user["r"]=="admin" else [valid[0]] if valid else []
            if not targets: raise HTTPException(400,"Choose an active doctor or administrator.")
            for target in targets: _staff_message(con,user["u"],target,subject.strip(),body.strip(),category,case_id or None)
    else: raise HTTPException(400,"Choose a recipient.")
    with connection() as con: audit(con,user["u"],user["r"],"mailbox_message_sent",case_id or None,f"recipient={recipient}; category={category}; internal message saved")
    path="/doctor/inbox" if user["r"]=="doctor" else "/admin/messages"
    status="Message saved in patient communication history." if recipient.startswith("patient:") else "Message saved to the recipient's inbox."
    return RedirectResponse(path+"?box=sent&status="+quote(status),status_code=303)


@app.post("/messages/{message_id}/read")
def read_mailbox_message(request:Request,message_id:int,csrf:str=Form(...)):
    user=require_user(request); verify_csrf(request,csrf)
    with connection() as con:
        row=con.execute("SELECT recipient FROM staff_messages WHERE id=?",(message_id,)).fetchone()
        if not row or row[0]!=user["u"]: raise HTTPException(403,"Only the recipient can mark this message read.")
        con.execute("UPDATE staff_messages SET read_at=? WHERE id=?",(now_iso(),message_id))
    return RedirectResponse("/doctor/inbox" if user["r"]=="doctor" else "/admin/messages",status_code=303)


@app.post("/doctor/messages")
def doctor_message(request: Request, case_id: str = Form(...), body: str = Form(...), channel: str = Form("local"), csrf: str = Form(...)):
    user = require_user(request, "doctor"); verify_csrf(request, csrf)
    if len(body.strip()) < 2 or len(body) > 1000:
        raise HTTPException(400, "Message must contain 2–1000 characters.")
    patient = require_assignment(user, case_id)
    if not patient: raise HTTPException(404, "Patient not found")
    delivery = {"status":"stored", "detail":"Saved in local communication history."}
    if channel == "whatsapp":
        with connection() as con:
            profile = con.execute("SELECT whatsapp_phone FROM doctor_profiles WHERE username=?", (user["u"],)).fetchone()
        delivery = send_whatsapp(profile[0] if profile else "", patient["phone"], body.strip())
    elif channel != "local":
        raise HTTPException(400, "Unknown communication channel")
    with role_connection(DOCTOR_DB_PATH) as con:
        con.execute("INSERT INTO messages(case_id,sender,recipient,body,sent_at,delivery_channel,delivery_status) VALUES(?,?,?,?,?,?,?)",
            (case_id,user["u"],case_id,body.strip(),now_iso(),channel,delivery["status"]))
    with connection() as con:
        audit(con, user["u"], user["r"], "message_saved", case_id, f"channel={channel}; status={delivery['status']}")
    return RedirectResponse("/doctor?message_status="+quote(delivery["detail"]), status_code=303)


@app.get("/support", response_class=HTMLResponse)
def support_dashboard(request: Request):
    try:
        require_user(request, "technician")
    except HTTPException as exc:
        if exc.status_code == 401:
            return redirect_login("/support")
        raise
    with role_connection(TECHNICIAN_DB_PATH) as con:
        registrations = con.execute("SELECT * FROM registrations ORDER BY id DESC LIMIT 12").fetchall()
        checks = con.execute("SELECT * FROM quality_checks ORDER BY id DESC LIMIT 12").fetchall()
        tickets = con.execute("SELECT * FROM support_tickets ORDER BY id DESC LIMIT 8").fetchall()
    return render(request, "support.html", page="support", registrations=registrations, checks=checks, tickets=tickets)


@app.post("/support/quality-check")
async def support_quality_check(request: Request, case_id: str = Form(...), image: UploadFile | None = File(None), csrf: str = Form(...)):
    user = require_user(request, "technician"); verify_csrf(request, csrf)
    image=await _image_upload(request,image)
    payload = await image.read()
    _, meta = validate_image_bytes(payload)
    width, height = int(meta["width"]), int(meta["height"])
    quality = "pass" if min(width, height) >= 224 else "review"
    feedback = "Technical checks passed; clinical image quality still requires clinician review." if quality == "pass" else "Resolution is below 224 px on one axis; recapture recommended."
    with role_connection(TECHNICIAN_DB_PATH) as con:
        con.execute("INSERT INTO quality_checks(case_id,filename,format,width,height,quality_status,feedback,checked_by,checked_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (case_id.strip().upper(),Path(image.filename or "upload").name,meta["format"],width,height,quality,feedback,user["u"],datetime.now().isoformat(timespec="seconds")))
    with connection() as con:
        audit(con, user["u"], user["r"], "technical_quality_check", case_id.strip().upper(), f"{meta['format']} {width}x{height}; result={quality}; no diagnosis generated.")
    return RedirectResponse("/support", status_code=303)


@app.post("/doctor/review/{case_id}")
def review_case(request: Request, case_id: str, decision: str = Form(...), tier: str = Form(""), reason: str = Form(...), csrf: str = Form(...)):
    user = require_user(request, "doctor"); verify_csrf(request, csrf)
    require_assignment(user,case_id)
    if decision not in {"approve","modify","reject","escalate"}:
        raise HTTPException(400, "Unknown review decision")
    if len(reason.strip()) < 8:
        raise HTTPException(400, "A meaningful review or override reason is required.")
    if decision in {"approve","modify","escalate"} and tier not in {"Tier 1","Tier 2","Tier 3"}:
        raise HTTPException(400, "A doctor must explicitly choose Tier 1, Tier 2, or Tier 3.")
    approved_tier = tier if decision != "reject" else None
    status = "approved" if approved_tier else "review_rejected"
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = _case(con, case_id)
        old_tier = row["approved_tier"]
        con.execute("UPDATE cases SET approved_tier=?,approved_by=?,approval_reason=?,review_state=?,status=? WHERE case_id=?",
                    (approved_tier, user["u"], reason.strip(), decision, status, case_id))
        if not approved_tier:
            con.execute("UPDATE surgeries SET status='cancelled' WHERE case_id=? AND status='confirmed'",(case_id,))
        detail = f"decision={decision}; manual_tier={approved_tier}; previous_tier={old_tier}; reason={reason.strip()}"
        audit(con, user["u"], user["r"], "priority_approval" if approved_tier else "review_rejected", case_id, detail)
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


def _available_today(profile: dict, leave_dates: set[str]) -> bool:
    weekday = date.today().strftime("%a")
    return bool(profile.get("is_active")) and weekday in str(profile.get("working_days", "")).split(",") and profile["username"] not in leave_dates


@app.get("/doctor/leave", response_class=HTMLResponse)
def doctor_leave(request: Request):
    user = require_user(request, "doctor")
    with connection() as con:
        leaves = con.execute("SELECT * FROM leave_requests WHERE doctor_username=? ORDER BY leave_date DESC", (user["u"],)).fetchall()
    return render(request, "leave.html", page="leave", leaves=leaves, affected=None, selected_date="", selected_type="full_day")


@app.post("/doctor/leave", response_class=HTMLResponse)
def submit_leave(request: Request, leave_date: str = Form(...), leave_type: str = Form(...), confirmed: str = Form(""), csrf: str = Form(...)):
    user = require_user(request, "doctor"); verify_csrf(request, csrf)
    validated_date(leave_date)
    if leave_type not in {"full_day","morning","evening"}: raise HTTPException(400, "Choose a valid leave option.")
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        affected = affected_bookings(con, user["u"], leave_date, leave_type)
        if affected and confirmed != "yes":
            leaves = con.execute("SELECT * FROM leave_requests WHERE doctor_username=? ORDER BY leave_date DESC", (user["u"],)).fetchall()
            return render(request, "leave.html", page="leave", leaves=leaves, affected=affected, selected_date=leave_date, selected_type=leave_type)
        if con.execute("SELECT 1 FROM leave_requests WHERE doctor_username=? AND leave_date=? AND status<>'rejected'", (user["u"],leave_date)).fetchone():
            raise HTTPException(409, "You already have a leave request for this date.")
        con.execute("INSERT INTO leave_requests(doctor_username,leave_date,leave_type,affected_count,created_at) VALUES(?,?,?,?,?)",
            (user["u"],leave_date,leave_type,len({a["case_id"] for a in affected}),now_iso()))
        for admin in con.execute("SELECT username FROM users WHERE role='admin'"):
            _staff_message(con,user["u"],admin[0],"Doctor leave request",f"{user['n']} requested {leave_type.replace('_',' ')} leave on {leave_date}. Review affected bookings in the hospital dashboard.","leave")
        audit(con,user["u"],user["r"],"leave_requested",None,f"date={leave_date}; type={leave_type}; affected={len(affected)}")
    return RedirectResponse("/doctor/leave", status_code=303)


@app.post("/doctor/review/{case_id}/suggestion", response_class=HTMLResponse)
def surgery_suggestion(request:Request,case_id:str,csrf:str=Form(...),clinical_context_submitted:str=Form(""),symptoms:str=Form("",max_length=20000),notes:str=Form("",max_length=20000),functional_impact:str=Form("unknown"),progression:str=Form("unknown"),planning_preference:str=Form("balanced")):
    from .enhancements import month_suggestion,month_context
    user=require_user(request,"doctor")
    result=month_suggestion(request,case_id,csrf,symptoms,notes,functional_impact,progression,planning_preference)
    with connection() as con:
        row=_case(con,case_id)
        surgery=con.execute("SELECT * FROM surgeries WHERE case_id=?",(case_id,)).fetchone()
        capacity=con.execute("SELECT * FROM surgery_capacity WHERE id=1").fetchone()
    return render(request,"clinical_review.html",page="review",case=row,analysis=json.loads(row['analysis_json'] or '{}'),reviewer=user,surgery=surgery,capacity=capacity,suggestion=result,booking_error=None,**month_context(__import__(__name__,fromlist=["app"]),user,dict(row)))


@app.post("/doctor/review/{case_id}/surgery", response_class=HTMLResponse)
@app.post("/admin/surgery/{case_id}/confirm")
def confirm_surgery(request: Request, case_id: str, surgery_date: str = Form(...), slot: str = Form(...), rationale: str = Form(...), csrf: str = Form(...)):
    user = require_user(request,"admin"); verify_csrf(request,csrf); patient=require_assignment(user,case_id)
    assigned_doctor=patient["doctor_username"]
    if len(rationale.strip()) < 8: raise HTTPException(400,"Record your clinical scheduling rationale.")
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            before=con.execute("SELECT * FROM surgeries WHERE case_id=?",(case_id,)).fetchone()
            month_planning.require_approved(con,dict(_case(con,case_id)),assigned_doctor,surgery_date)
            available=month_planning.free_slots(con,assigned_doctor,surgery_date[:7],case_id)
            if not any(x["date"]==surgery_date and x["slot"]==slot for x in available): raise HTTPException(409,"This slot is no longer free. Refresh the approved-month calendar.")
            earliest=clinical_context(_case(con,case_id))["doctor_earliest_date"]
            if earliest and surgery_date<earliest: raise HTTPException(409,"Choose a date on or after the doctor-recorded earliest date.")
            reserve_surgery(con,case_id,surgery_date,slot,assigned_doctor,rationale.strip())
        except HTTPException:
            raise
        audit(con,user["u"],user["r"],"surgery_confirmed",case_id,f"admin-selected date within doctor-approved month={surgery_date}; slot={slot}; rationale={rationale.strip()}")
        same=before and before["status"]=="confirmed" and before["surgery_date"]==surgery_date and before["slot"]==slot and before["confirmed_by"]==assigned_doctor
        existing=con.execute("SELECT * FROM outbound_notifications WHERE case_id=? AND doctor_username=? AND surgery_date=? AND slot=? ORDER BY id DESC LIMIT 1",(case_id,assigned_doctor,surgery_date,slot)).fetchone() if same else None
        new_notice=not existing
        if existing: token=existing["confirmation_token"]
        else:
            token=uuid4().hex
            profile=con.execute("SELECT whatsapp_phone FROM doctor_profiles WHERE username=?",(assigned_doctor,)).fetchone()
            sender=profile[0] if profile else ""
            body=communications.surgery_message(patient["full_name"],surgery_date,slot)
            con.execute("""INSERT INTO outbound_notifications(confirmation_token,case_id,doctor_username,patient_name,recipient_phone,sender_phone,surgery_date,slot,body,delivery_status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,'sending',?)""",(token,case_id,assigned_doctor,patient["full_name"],patient["phone"],sender,surgery_date,slot,body,now_iso()))
    if new_notice:
        delivery=communications.send_surgery_whatsapp(sender,patient["phone"],patient["full_name"],surgery_date,slot)
        with connection() as con:
            con.execute("UPDATE outbound_notifications SET delivery_status=?,delivery_detail=? WHERE confirmation_token=?",(delivery["status"],delivery["detail"],token))
            audit(con,user["u"],user["r"],"surgery_notification",case_id,f"channel=whatsapp; status={delivery['status']}; confirmation={token}")
    return RedirectResponse("/calendar?kind=surgery&month="+surgery_date[:7]+"&confirmation="+token,status_code=303)


@app.post("/intake")
async def registered_intake(request: Request, case_id: str = Form(...), modality: str = Form(...),
    symptoms: str = Form(""), notes: str = Form(""), illumination_type: str = Form("Diffuse Illumination"),
    left_images: list[UploadFile] = File([]), right_images: list[UploadFile] = File([]),
    unknown_images: list[UploadFile] = File([]), csrf: str = Form(...)):
    user=require_user(request); verify_csrf(request,csrf)
    if user["r"]=="admin": raise HTTPException(403,"Clinical intake requires a doctor or technician.")
    patient=require_assignment(user,case_id)
    if not patient: raise HTTPException(400,"Select a registered patient.")
    if modality not in {"fundus","slit_lamp"}: raise HTTPException(400,"Choose a supported modality.")
    restored=await restore_uploads(request)
    left_images=left_images+restored.get("left_images",[])
    right_images=right_images+restored.get("right_images",[])
    unknown_images=unknown_images+restored.get("unknown_images",[])
    incoming=[(eye,f) for eye,group in [("Left",left_images),("Right",right_images),("Not recorded",unknown_images)] for f in group if f.filename]
    if len(incoming)>12: raise HTTPException(400,"Upload at most 12 images per intake.")
    prepared=[]
    observation_group=uuid4().hex
    for eye,upload in incoming:
        payload=await upload.read(8*1024*1024+1)
        _,meta=validate_image_bytes(payload)
        context={"eye_side":eye,"reflection":0,"slit_lamp_illumination_type":illumination_type}
        infer=provider.analyze if modality=="fundus" else lambda data,kind,ctx=context: real_provider.analyze_fusion(data,kind,ctx)
        result=run_workflow(payload,modality,meta,infer)
        result.update(eye_side=eye, observation_group=observation_group)
        ext={"JPEG":"jpg","PNG":"png","WEBP":"webp"}[meta["format"]]
        prepared.append((eye,payload,ext,result))
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        _case(con,case_id)
        con.execute("UPDATE cases SET modality=?,symptoms=?,notes=?,status='awaiting_review' WHERE case_id=?",(modality,symptoms.strip(),notes.strip(),case_id))
        if not prepared:
            empty={"status":"not_run","observation_group":observation_group}
            con.execute("UPDATE cases SET eye='Not recorded',image_path=NULL,image_sha256=NULL,analysis_status='not_run',analysis_json=? WHERE case_id=?",(json.dumps(empty),case_id))
        for eye,payload,ext,result in prepared:
            target=UPLOAD_DIR/(uuid4().hex+"."+ext); file_store.write(target,payload)
            relative=str(target.relative_to(APP_DIR)).replace(chr(92),"/")
            digest=hashlib.sha256(payload).hexdigest()
            con.execute("INSERT INTO case_images(case_id,eye_side,image_path,image_sha256,analysis_json,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?)",
                (case_id,eye,relative,digest,json.dumps(result),user["u"],now_iso()))
            con.execute("UPDATE cases SET image_path=?,image_sha256=?,analysis_status=?,analysis_json=? WHERE case_id=?",
                (relative,digest,result["status"],json.dumps(result),case_id))
        if prepared: _sync_case_eye(con, case_id)
        audit(con,user["u"],user["r"],"registered_intake",case_id,f"Saved intake and {len(prepared)} separately analysed images with explicit eye labels; batch={observation_group}.")
    return RedirectResponse("/cases/"+case_id,status_code=303)


def _sync_case_eye(con, case_id: str):
    row=con.execute("SELECT analysis_json FROM cases WHERE case_id=?",(case_id,)).fetchone()
    analysis=json.loads(row[0]) if row and row[0] else None
    images=[dict(item) for item in con.execute("SELECT id,eye_side,analysis_json FROM case_images WHERE case_id=?",(case_id,))]
    current,_=partition_images(images,analysis)
    sides={item["eye_side"] for item in current}
    label="Both" if {"Left","Right"} <= sides else next(iter(sides)) if len(sides)==1 else "Not recorded"
    con.execute("UPDATE cases SET eye=? WHERE case_id=?",(label,case_id))


@app.get("/case-image/{image_id}")
def clinical_image(request: Request, image_id: int):
    user=require_user(request)
    with connection() as con:
        row=con.execute("SELECT * FROM case_images WHERE id=?",(image_id,)).fetchone()
    if not row: raise HTTPException(404,"Image not found")
    require_assignment(user,row["case_id"])
    target=(APP_DIR/row["image_path"]).resolve()
    if not target.is_relative_to(UPLOAD_DIR.resolve()) or not file_store.exists(target): raise HTTPException(404,"Image not found")
    payload,media_type=file_store.display_bytes(target)
    return Response(payload,media_type=media_type,headers={"Cache-Control":"no-store"})


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    try:
        require_user(request, "admin")
    except HTTPException as exc:
        if exc.status_code == 401: return redirect_login("/admin")
        raise
    with connection() as con:
        doctors = [dict(row) for row in con.execute("SELECT d.*,s.email_status,s.email_detail FROM doctor_profiles d LEFT JOIN account_security s USING(username) WHERE d.is_active=1 ORDER BY display_name")]
        leaves = [dict(row) for row in con.execute("SELECT l.*,d.display_name FROM leave_requests l JOIN doctor_profiles d ON d.username=l.doctor_username ORDER BY CASE l.status WHEN 'pending' THEN 0 ELSE 1 END,l.leave_date")]
        capacity = dict(con.execute("SELECT * FROM surgery_capacity WHERE id=1").fetchone())
        google_requests = con.execute("SELECT * FROM google_access_requests ORDER BY requested_at DESC").fetchall()
        surgeries = [dict(row) for row in con.execute("SELECT s.*,c.patient_alias FROM surgeries s JOIN cases c USING(case_id) ORDER BY surgery_date,slot LIMIT 20")]
        appointments = [dict(row) for row in con.execute("SELECT a.*,c.patient_alias FROM appointments a JOIN cases c USING(case_id) ORDER BY scheduled_date,slot")]
    with role_connection(DOCTOR_DB_PATH) as con:
        counts = {row[0]: row[1] for row in con.execute("SELECT doctor_username,COUNT(*) FROM patient_profiles GROUP BY doctor_username")}
        patients = [dict(row) for row in con.execute("SELECT * FROM patient_profiles ORDER BY full_name")]
    active=_active_case_ids()
    patients=[patient for patient in patients if patient['case_id'] in active]
    counts={doctor['username']:sum(p['doctor_username']==doctor['username'] for p in patients) for doctor in doctors}
    today_leave = {item["doctor_username"] for item in leaves if item["leave_date"] == date.today().isoformat() and item["status"] in {"pending", "approved", "resolved"} and item["leave_type"]=="full_day"}
    for doctor in doctors:
        doctor["patient_count"] = int(counts.get(doctor["username"], 0))
        doctor["available_today"] = _available_today(doctor, today_leave)
    with connection() as con:
        for leave in leaves:
            leave["affected"] = affected_bookings(con,leave["doctor_username"],leave["leave_date"],leave["leave_type"])
            for event in leave["affected"]:
                event["alternatives"] = [d for d in doctors if d["username"] != leave["doctor_username"] and doctor_available(con,d["username"],leave["leave_date"],event["slot"])]
    return render(request, "admin.html", page="admin", doctors=doctors, patients=patients, leaves=leaves, capacity=capacity,
                  surgeries=surgeries, google_requests=google_requests, pending_leave=next((item for item in leaves if item["status"] == "pending"), None),account_status=request.query_params.get("account_status",""),email_ready=communications.email_ready(),email_provider=communications.email_provider(),admin_email=os.getenv("ADMIN_EMAIL","pamindu39@gmail.com"))


@app.post("/admin/doctors")
async def admin_save_doctor(
    request: Request, username: str = Form(""), display_name: str = Form(...), mobile: str = Form(...),
    work_start: str = Form(...), work_end: str = Form(...), working_days: list[str] = Form(...),
    whatsapp_phone: str = Form(""), email: str = Form(""), csrf: str = Form(...),
    profile_image: UploadFile | None = File(None), google_email: str = Form(""),
):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    profile_image=await _image_upload(request,profile_image,"profile_image",required=False)
    username = username.strip().lower()
    if username and (not username.startswith("dr.") or not username.replace(".", "").replace("_", "").isalnum()):
        raise HTTPException(400, "Doctor username must begin with dr. and contain only letters, numbers, dots or underscores.")
    if len(display_name.strip()) < 4: raise HTTPException(400,"Enter the doctor's full name.")
    email=email.strip().lower()
    if email and not communications.valid_email(email): raise HTTPException(400,"Enter a valid doctor email address.")
    valid_time(work_start); valid_time(work_end)
    if work_start >= work_end: raise HTTPException(400,"Working hours must end after they start.")
    image_name = None
    if profile_image and profile_image.filename:
        payload = await profile_image.read(); _, meta = validate_image_bytes(payload)
        ext = {"JPEG":"jpg", "PNG":"png", "WEBP":"webp"}[meta["format"]]
        image_name = f"doctor_{uuid4().hex}.{ext}"
        file_store.write(DOCTOR_IMAGE_DIR / image_name,payload)
    days = ",".join(day for day in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"] if day in set(working_days))
    new_password=None
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        if not username: username=communications.generated_username(con,display_name)
        if con.execute("SELECT 1 FROM account_login_names WHERE login_name=? AND username<>?",(username,username)).fetchone(): raise HTTPException(409,"This sign-in username is already in use.")
        existing = con.execute("SELECT username FROM users WHERE username=?", (username,)).fetchone()
        if not existing and not email: raise HTTPException(400,"The doctor's email address is required for new account registration.")
        if email and con.execute("SELECT 1 FROM doctor_profiles WHERE lower(email)=? AND username<>?",(email,username)).fetchone(): raise HTTPException(409,"This email is already registered to another doctor.")
        if existing:
            if con.execute("SELECT role FROM users WHERE username=?",(username,)).fetchone()[0] != "doctor":
                raise HTTPException(409,"This username belongs to another role.")
            con.execute("UPDATE users SET display_name=? WHERE username=? AND role='doctor'", (display_name.strip(), username))
            old = con.execute("SELECT profile_image FROM doctor_profiles WHERE username=?", (username,)).fetchone()
            if not image_name and old: image_name = old[0]
        else:
            new_password=communications.temporary_password()
            con.execute("INSERT INTO users VALUES(?,?,?,?)", (username, display_name.strip(), "doctor", hash_password(new_password)))
            account_security.changed(con,username,temporary=True)
        con.execute("""INSERT INTO doctor_profiles(username,display_name,mobile,work_start,work_end,working_days,profile_image,whatsapp_phone)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,mobile=excluded.mobile,
            work_start=excluded.work_start,work_end=excluded.work_end,working_days=excluded.working_days,
            profile_image=COALESCE(excluded.profile_image,doctor_profiles.profile_image),whatsapp_phone=excluded.whatsapp_phone""",
            (username, display_name.strip(), mobile.strip(), work_start, work_end, days, image_name, whatsapp_phone.strip()))
        if email: con.execute("UPDATE doctor_profiles SET email=? WHERE username=?",(email,username))
        else: email=con.execute("SELECT email FROM doctor_profiles WHERE username=?",(username,)).fetchone()[0]
        audit(con, user["u"], user["r"], "doctor_saved", None, f"Doctor {username} profile and working hours saved.")
        google_email=google_email.strip().lower()
        if google_email and con.execute("SELECT 1 FROM doctor_profiles WHERE lower(google_email)=? AND username<>?",(google_email,username)).fetchone():
            raise HTTPException(409,"This Google email is already assigned to another doctor.")
        if google_email: con.execute("UPDATE doctor_profiles SET google_email=? WHERE username=?",(google_email,username))
    with role_connection(DOCTOR_DB_PATH) as con:
        con.execute("""INSERT INTO doctor_directory(username,display_name,specialty,hospital,phone,email,working_hours,working_days,profile_image,whatsapp_phone)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,phone=excluded.phone,
            working_hours=excluded.working_hours,working_days=excluded.working_days,profile_image=COALESCE(excluded.profile_image,doctor_directory.profile_image),whatsapp_phone=excluded.whatsapp_phone,email=excluded.email""",
            (username, display_name.strip(), "Ophthalmology", "CataTriage Demonstration Hospital", mobile.strip(), email, f"{work_start}-{work_end}", days, image_name, whatsapp_phone.strip()))
    status="Doctor profile updated."
    if new_password:
        with connection() as con: current_login=doctor_account.login_name(con,username)
        delivery=communications.send_credentials(email,current_login,new_password)
        _record_login_email(username,delivery,user)
        status=f"Registered {username}. "+delivery["detail"]
    return RedirectResponse("/admin?account_status="+quote(status), status_code=303)


@app.get('/admin/accounts',response_class=HTMLResponse)
def manage_accounts(request:Request):
    require_user(request,'admin')
    with connection() as con:
        store=account_management.doctor_store(con,DOCTOR_DB_PATH)
        patients=[dict(row) for row in con.execute(f'SELECT p.*,c.age,c.status FROM {store}.patient_profiles p JOIN cases c USING(case_id) WHERE c.is_archived=0 ORDER BY p.full_name')]
        doctors=[dict(row) for row in con.execute('SELECT * FROM doctor_profiles WHERE is_active=1 ORDER BY display_name')]
        deleted=[dict(row) for row in con.execute('SELECT * FROM account_archives WHERE restored_at IS NULL ORDER BY archived_at DESC')]
    for doctor in doctors: doctor['patient_count']=sum(p['doctor_username']==doctor['username'] for p in patients)
    return render(request,'account_management.html',page='accounts',patients=patients,doctors=doctors,deleted=deleted,status=request.query_params.get('status',''))


@app.post('/admin/patients/{case_id}/edit')
def edit_patient(request:Request,case_id:str,full_name:str=Form(...,min_length=3,max_length=150),age:int=Form(...,ge=1,le=110),phone:str=Form(...,min_length=8,max_length=30),email:str=Form('',max_length=254),address:str=Form(...,min_length=1,max_length=1000),doctor_username:str=Form(...),csrf:str=Form(...)):
    user=require_user(request,'admin'); verify_csrf(request,csrf)
    if not full_name.strip() or not address.strip() or (email and not communications.valid_email(email)): raise HTTPException(400,'Enter a valid patient name, address and email.')
    with connection() as con:
        store=account_management.doctor_store(con,DOCTOR_DB_PATH)
        con.execute('BEGIN IMMEDIATE')
        row=con.execute(f'SELECT p.doctor_username,c.is_archived FROM {store}.patient_profiles p JOIN cases c USING(case_id) WHERE p.case_id=?',(case_id,)).fetchone()
        if not row or row['is_archived']: raise HTTPException(404,'Active patient not found.')
        if row['doctor_username']!=doctor_username: account_management.validate_transfer(con,case_id,doctor_username)
        elif not con.execute('SELECT 1 FROM doctor_profiles WHERE username=? AND is_active=1',(doctor_username,)).fetchone(): raise HTTPException(400,'Choose an active doctor.')
        con.execute('UPDATE cases SET patient_alias=?,age=? WHERE case_id=?',(full_name.strip(),age,case_id))
        con.execute(f'UPDATE {store}.patient_profiles SET full_name=?,phone=?,email=?,address=?,doctor_username=? WHERE case_id=?',(full_name.strip(),phone.strip(),email.strip().lower(),address.strip(),doctor_username,case_id))
        audit(con,user['u'],user['r'],'patient_profile_updated',case_id,f'Demographics updated; assigned doctor={doctor_username}; clinical approval unchanged.')
    return RedirectResponse('/admin/accounts?status=Patient%20updated.',status_code=303)


@app.post('/admin/accounts/{kind}/{key}/delete')
def delete_account(request:Request,kind:str,key:str,csrf:str=Form(...),reassign_to:str=Form('')):
    user=require_user(request,'admin'); verify_csrf(request,csrf)
    with connection() as con:
        store=account_management.doctor_store(con,DOCTOR_DB_PATH)
        con.execute('BEGIN IMMEDIATE')
        if kind=='patient': account_management.delete_patient(con,key,user['u'])
        elif kind=='doctor': account_management.delete_doctor(con,store,key,reassign_to,user['u'])
        else: raise HTTPException(400,'Choose a patient or doctor account.')
        audit(con,user['u'],user['r'],'account_deleted',key if kind=='patient' else None,f'type={kind}; key={key}; reversible deletion; audit and medical history retained.')
    return RedirectResponse('/admin/accounts?status=Deleted%20from%20active%20records.%20Restore%20is%20available%20below.',status_code=303)


@app.post('/admin/accounts/{kind}/{key}/restore')
def restore_account(request:Request,kind:str,key:str,csrf:str=Form(...),doctor_username:str=Form('')):
    user=require_user(request,'admin'); verify_csrf(request,csrf)
    with connection() as con:
        store=account_management.doctor_store(con,DOCTOR_DB_PATH)
        con.execute('BEGIN IMMEDIATE')
        if kind=='patient':
            patient=con.execute(f'SELECT doctor_username FROM {store}.patient_profiles WHERE case_id=?',(key,)).fetchone()
            selected=doctor_username or (patient[0] if patient else '')
            account_management.validate_transfer(con,key,selected)
            con.execute(f'UPDATE {store}.patient_profiles SET doctor_username=? WHERE case_id=?',(selected,key))
        account_management.restore(con,kind,key)
        audit(con,user['u'],user['r'],'account_restored',key if kind=='patient' else None,f'type={kind}; key={key}; cancelled bookings were not reinstated.')
    return RedirectResponse('/admin/accounts?status=Record%20restored.%20Review%20and%20rebook%20cancelled%20appointments%20if%20needed.',status_code=303)


def _record_login_email(username,delivery,admin):
    with connection() as con:
        con.execute("INSERT OR IGNORE INTO account_security(username) VALUES(?)",(username,))
        if delivery.get('password_setup') and delivery['status']=='accepted': con.execute('UPDATE account_security SET firebase_pending=1 WHERE username=?',(username,))
        con.execute("UPDATE account_security SET email_status=?,email_detail=?,last_emailed_at=? WHERE username=?",(delivery["status"],delivery["detail"],now_iso(),username))
        audit(con,admin["u"],admin["r"],"doctor_login_email",None,f"doctor={username}; status={delivery['status']}; credentials excluded from audit")


@app.post("/admin/doctors/{username}/login-email")
def resend_doctor_login(request:Request,username:str,csrf:str=Form(...)):
    user=require_user(request,"admin"); verify_csrf(request,csrf)
    if not communications.email_ready(): return RedirectResponse('/admin?account_status='+quote('Email sending is not connected. Existing login credentials have not changed.'),status_code=303)
    password=communications.temporary_password()
    with connection() as con:
        profile=con.execute("SELECT * FROM doctor_profiles WHERE username=? AND is_active=1",(username,)).fetchone()
        if not profile or not communications.valid_email(profile["email"]): raise HTTPException(400,"Save a valid registered doctor email before sending new login credentials.")
        previous=con.execute("SELECT password_hash FROM users WHERE username=?",(username,)).fetchone()[0]
    with connection() as con: current_login=doctor_account.login_name(con,username)
    delivery=communications.send_credentials(profile["email"],current_login,password)
    if delivery["status"]=="accepted" and not delivery.get('password_setup'):
        with connection() as con:
            con.execute("BEGIN IMMEDIATE")
            changed=con.execute("UPDATE users SET password_hash=? WHERE username=? AND password_hash=?",(hash_password(password),username,previous))
            if changed.rowcount!=1: raise HTTPException(409,"The password changed while the email was being sent. The emailed temporary password is inactive; request a fresh login email.")
            account_security.changed(con,username,temporary=True)
    else: delivery={**delivery,"detail":delivery["detail"]+" Existing login credentials have not changed."}
    _record_login_email(username,delivery,user)
    return RedirectResponse("/admin?account_status="+quote(delivery["detail"]),status_code=303)


@app.get("/doctor-profile/{username}")
def doctor_profile_image(request: Request, username: str):
    require_user(request)
    with connection() as con:
        row = con.execute("SELECT profile_image FROM doctor_profiles WHERE username=?", (username,)).fetchone()
    if not row or not row[0]: raise HTTPException(404, "Profile image not found")
    target = (DOCTOR_IMAGE_DIR / row[0]).resolve()
    if not target.is_relative_to(DOCTOR_IMAGE_DIR.resolve()) or not file_store.exists(target): raise HTTPException(404, "Profile image not found")
    payload,media=file_store.display_bytes(target)
    return Response(payload,media_type=media,headers={"Cache-Control":"no-store"})


@app.post("/admin/patients")
def admin_register_patient(
    request: Request, full_name: str = Form(...), address: str = Form(...), mobile: str = Form(...),
    doctor_username: str = Form(...), age: int = Form(...), csrf: str = Form(...),
):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    if not 1 <= age <= 110 or len(full_name.strip())<3 or not address.strip() or len(mobile.strip())<8:
        raise HTTPException(400,"Enter a complete name, address, mobile number and valid age.")
    with connection() as con:
        if not con.execute("SELECT 1 FROM doctor_profiles WHERE username=? AND is_active=1", (doctor_username,)).fetchone():
            raise HTTPException(400, "Choose an active registered doctor.")
        next_number = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM cases").fetchone()[0]) + 1000
        case_id = f"DEMO-{next_number:04d}"
        con.execute("""INSERT INTO cases(case_id,patient_alias,age,eye,modality,status,created_at,waiting_since,symptoms,notes)
            VALUES(?,?,?,'Not recorded','slit_lamp','registered',?,?, '', 'Registered by hospital admin')""",
            (case_id, full_name.strip(), age, now_iso(), date.today().isoformat()))
        audit(con, user["u"], user["r"], "patient_registered", case_id, f"Registered fictional patient and assigned to {doctor_username}.")
    with role_connection(DOCTOR_DB_PATH) as con:
        con.execute("INSERT INTO patient_profiles(case_id,doctor_username,full_name,phone,email,address,medical_history) VALUES(?,?,?,?,?,?,?)",
                    (case_id, doctor_username, full_name.strip(), mobile.strip(), f"{case_id.lower()}@example.invalid", address.strip(), "No history recorded yet."))
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/capacity")
def admin_capacity(request: Request, max_surgeries: int = Form(...), total_beds: int = Form(...), available_beds: int = Form(...), csrf: str = Form(...)):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    if not (1 <= max_surgeries <= 100 and 0 <= available_beds <= total_beds <= 500):
        raise HTTPException(400, "Capacity values are outside the allowed range.")
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        existing=con.execute("SELECT surgery_date,COUNT(*) n FROM surgeries WHERE status='confirmed' AND surgery_date>=? GROUP BY surgery_date HAVING COUNT(*)>? LIMIT 1",
            (date.today().isoformat(),min(max_surgeries,available_beds))).fetchone()
        if existing: raise HTTPException(409,f"Existing bookings on {existing['surgery_date']} exceed this capacity. Reschedule them before reducing the limit.")
        con.execute("UPDATE surgery_capacity SET max_surgeries_per_day=?,total_beds=?,available_beds=?,updated_at=? WHERE id=1",
                    (max_surgeries, total_beds, available_beds, now_iso()))
        audit(con, user["u"], user["r"], "capacity_updated", None, f"max_surgeries={max_surgeries}; beds={available_beds}/{total_beds}")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/google-link")
def admin_google_link(request: Request, doctor_username: str=Form(...), google_email: str=Form(...), csrf: str=Form(...)):
    user=require_user(request,"admin"); verify_csrf(request,csrf)
    google_email=google_email.strip().lower()
    if "@" not in google_email: raise HTTPException(400,"Enter the doctor's Google email.")
    with connection() as con:
        if not con.execute("SELECT 1 FROM doctor_profiles WHERE username=?",(doctor_username,)).fetchone(): raise HTTPException(404,"Doctor not found")
        if con.execute("SELECT 1 FROM doctor_profiles WHERE google_email=? AND username<>?",(google_email,doctor_username)).fetchone(): raise HTTPException(409,"This email belongs to another doctor.")
        con.execute("DELETE FROM google_identities WHERE username=?",(doctor_username,))
        con.execute("UPDATE doctor_profiles SET google_email=? WHERE username=?",(google_email,doctor_username))
        con.execute("DELETE FROM google_access_requests WHERE email=?",(google_email,))
        audit(con,user["u"],user["r"],"google_identity_preapproved",None,f"Approved Google sign-in for doctor {doctor_username}.")
    return RedirectResponse("/admin",status_code=303)


@app.post("/admin/leave/{leave_id}/patient/{case_id}")
def admin_leave_patient_action(
    request: Request, leave_id: int, case_id: str, action: str = Form(...), doctor_username: str = Form(""),
    new_date: str = Form(""), event_type: str = Form("meeting"), csrf: str = Form(...),
):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        leave = con.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
        if not leave: raise HTTPException(404, "Leave request not found")
        event=next((a for a in affected_bookings(con,leave["doctor_username"],leave["leave_date"],leave["leave_type"]) if a["case_id"]==case_id and a["event_type"]==event_type),None)
        if not event: raise HTTPException(409,"This booking is no longer affected by the leave request.")
        if action == "reschedule":
            validated_date(new_date)
            if event_type=="surgery":
                month_planning.require_approved(con,dict(_case(con,case_id)),leave['doctor_username'],new_date)
                if not any(x['date']==new_date and x['slot']==event['slot'] for x in month_planning.free_slots(con,leave['doctor_username'],new_date[:7],case_id)): raise HTTPException(409,'Select a free slot within the approved surgery month.')
                reserve_surgery(con,case_id,new_date,event["slot"],leave["doctor_username"],"Rescheduled by admin due to doctor leave; original clinical decision retained.")
            else:
                if not doctor_available(con,leave["doctor_username"],new_date,event["slot"]): raise HTTPException(409,"Doctor unavailable at the new appointment time.")
                con.execute("UPDATE appointments SET scheduled_date=?,created_by=?,created_at=? WHERE case_id=?", (new_date, user["u"], now_iso(), case_id))
        elif action == "reassign":
            if not doctor_available(con,doctor_username,leave["leave_date"],event["slot"]):
                raise HTTPException(409, "The selected doctor is unavailable at the affected time.")
            with role_connection(DOCTOR_DB_PATH) as dcon:
                dcon.execute("UPDATE patient_profiles SET doctor_username=? WHERE case_id=?", (doctor_username, case_id))
        else: raise HTTPException(400, "Unknown leave action")
        con.execute("UPDATE leave_requests SET status='approved' WHERE id=?", (leave_id,))
        audit(con, user["u"], user["r"], "leave_patient_action", case_id, f"leave={leave_id}; action={action}; doctor={doctor_username}; date={new_date}")
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/leave/{leave_id}/status")
def admin_leave_status(request: Request, leave_id: int, status: str = Form(...), csrf: str = Form(...)):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    if status not in {"approved", "resolved", "rejected"}: raise HTTPException(400, "Invalid leave status")
    with connection() as con:
        leave=con.execute("SELECT * FROM leave_requests WHERE id=?",(leave_id,)).fetchone()
        if not leave: raise HTTPException(404,"Leave request not found")
        if status=="resolved" and affected_bookings(con,leave["doctor_username"],leave["leave_date"],leave["leave_type"]):
            raise HTTPException(409,"Reassign or reschedule affected bookings before resolving the leave request.")
        con.execute("UPDATE leave_requests SET status=? WHERE id=?", (status, leave_id))
        _staff_message(con,user["u"],leave["doctor_username"],"Leave request "+status,f"Your {leave['leave_type'].replace('_',' ')} leave request for {leave['leave_date']} was marked {status} by the hospital admin.","leave")
        audit(con, user["u"], user["r"], "leave_status_changed", None, f"leave={leave_id}; status={status}")
    return RedirectResponse("/admin", status_code=303)


@app.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request, tier: str = "", status: str = ""):
    try: require_user(request, "admin")
    except HTTPException as exc:
        if exc.status_code == 401: return redirect_login("/queue")
        raise
    clauses = ["approved_tier IS NOT NULL","c.is_archived=0"]; params = []
    if tier: clauses.append("approved_tier=?"); params.append(tier)
    if status: clauses.append("status=?"); params.append(status)
    with connection() as con:
        rows = con.execute(f"""SELECT c.*,a.scheduled_date,a.slot,CAST(julianday('now')-julianday(c.waiting_since) AS INTEGER) wait_days
            FROM cases c LEFT JOIN appointments a USING(case_id) WHERE {' AND '.join(clauses)}
            ORDER BY CASE approved_tier WHEN 'Tier 1' THEN 1 WHEN 'Tier 2' THEN 2 ELSE 3 END, wait_days DESC""", params).fetchall()
    return render(request, "queue.html", page="queue", cases=rows, filters={"tier":tier,"status":status})


@app.post("/queue/{case_id}/schedule")
def schedule(request: Request, case_id: str, scheduled_date: str = Form(...), slot: str = Form(...), csrf: str = Form(...)):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    validated_date(scheduled_date); valid_time(slot)
    patient=require_assignment(user,case_id)
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        row = _case(con, case_id)
        if not row["approved_tier"]:
            raise HTTPException(403, "Only doctor-approved cases can be scheduled.")
        if patient and not doctor_available(con,patient["doctor_username"],scheduled_date,slot):
            raise HTTPException(409,"The assigned doctor is unavailable at this consultation time.")
        con.execute("""INSERT INTO appointments(case_id,scheduled_date,slot,service,created_by,created_at) VALUES(?,?,?,?,?,datetime('now'))
            ON CONFLICT(case_id) DO UPDATE SET scheduled_date=excluded.scheduled_date,slot=excluded.slot,created_by=excluded.created_by,created_at=excluded.created_at""",
            (case_id, scheduled_date, slot, "Demo ophthalmology clinic", user["u"]))
        con.execute("UPDATE cases SET status='scheduled' WHERE case_id=?", (case_id,))
        audit(con, user["u"], user["r"], "schedule_changed", case_id, f"Synthetic appointment set for {scheduled_date} {slot}; approved tier unchanged ({row['approved_tier']}).")
    return RedirectResponse("/calendar", status_code=303)


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, kind: str = "meeting", month: str = ""):
    user=read_session(request)
    if not user: return redirect_login("/calendar")
    if kind not in {"meeting","surgery"}: raise HTTPException(400,"Unknown calendar")
    try: first=date.fromisoformat((month or date.today().strftime("%Y-%m"))+"-01")
    except ValueError: raise HTTPException(400,"Use a valid calendar month.")
    with connection() as con:
        meetings=[dict(r) for r in con.execute("SELECT a.*,c.patient_alias,c.approved_tier FROM appointments a JOIN cases c USING(case_id) WHERE c.is_archived=0 ORDER BY scheduled_date,slot")]
        surgeries=[dict(r) for r in con.execute("SELECT s.*,s.surgery_date scheduled_date,c.patient_alias,c.approved_tier FROM surgeries s JOIN cases c USING(case_id) WHERE s.status='confirmed' AND c.is_archived=0 ORDER BY surgery_date,slot")]
        capacity=con.execute("SELECT * FROM surgery_capacity WHERE id=1").fetchone()
        token=request.query_params.get("confirmation","")
        notice=con.execute("SELECT * FROM outbound_notifications WHERE confirmation_token=?"+("" if user["r"]=="admin" else " AND doctor_username=?"),(token,) if user["r"]=="admin" else (token,user["u"])).fetchone() if token else None
        surgery_confirmation=dict(notice) if notice else None
        if surgery_confirmation: surgery_confirmation["manual_link"]=communications.whatsapp_link(notice["recipient_phone"],notice["body"])
    with role_connection(DOCTOR_DB_PATH) as con:
        assignments={r["case_id"]:dict(r) for r in con.execute("SELECT * FROM patient_profiles")}
    for items in [meetings,surgeries]:
        for item in items:
            item["doctor_username"]=assignments.get(item["case_id"],{}).get("doctor_username","Unassigned")
    if user["r"]=="doctor":
        meetings=[x for x in meetings if x["doctor_username"]==user["u"]]
        surgeries=[x for x in surgeries if x["doctor_username"]==user["u"]]
    selected=meetings if kind=="meeting" else surgeries
    events=[x for x in selected if x["scheduled_date"].startswith(first.strftime("%Y-%m"))]
    grouped={}
    for event in events: grouped.setdefault(event["scheduled_date"],[]).append(event)
    weeks=month_calendar.Calendar(firstweekday=0).monthdatescalendar(first.year,first.month)
    previous=(first-timedelta(days=1)).strftime("%Y-%m")
    following=(first.replace(day=28)+timedelta(days=4)).strftime("%Y-%m")
    return render(request,"schedule_calendar.html",page="calendar",appointments=meetings,surgeries=surgeries,kind=kind,month=first,
        weeks=weeks,grouped=grouped,events=events,previous=previous,following=following,capacity=capacity,surgery_confirmation=surgery_confirmation)


@app.get("/model", response_class=HTMLResponse)
def model_page(request: Request):
    if not read_session(request): return redirect_login("/model")
    if read_session(request)["r"]=="doctor": return RedirectResponse("/doctor",status_code=303)
    metrics = {}
    for key, folder in (("multidata", "cataract_grade_multidata_real"), ("fusion", "clinical_fusion_catscreen_real")):
        path = ROOT / "models" / folder / "metrics.json"
        if path.exists():
            metrics[key] = json.loads(path.read_text(encoding="utf-8"))
    return render(request, "model.html", page="model", model_device=provider.device_label, real_device=real_provider.device_label, metrics=metrics)


@app.get("/real-lab", response_class=HTMLResponse)
def real_lab(request: Request):
    if not read_session(request): return redirect_login("/real-lab")
    if read_session(request)["r"]=="doctor": return RedirectResponse("/doctor",status_code=303)
    return render(request, "real_lab.html", page="real_lab", tabular_result=None, fusion_result=None, form={})


@app.post("/real-lab/tabular", response_class=HTMLResponse)
def real_lab_tabular(
    request: Request, age: float = Form(...), gender: float = Form(...), ucva_right: float = Form(...), bcva_right: float = Form(...),
    ucva_left: float = Form(...), bcva_left: float = Form(...), outdoor_hours: float = Form(...), sunlight_code: float = Form(...),
    glaucoma_code: float = Form(1), retinal_code: float = Form(1), myopia_code: float = Form(1), csrf: str = Form(...),
):
    require_user(request); verify_csrf(request, csrf)
    supplied = {
        "age": age, "gender": gender, "UCVA Right eye": ucva_right, "BCVA Right": bcva_right,
        "UCVA Left": ucva_left, "BCVA Left": bcva_left, "outdoor activity hours per day": outdoor_hours,
        "sunlight protection or not": sunlight_code, "R glaucoma(1 No 2 Yes)": glaucoma_code,
        "L glaucoma(1 No 2 Yes)": glaucoma_code, "R DR (1 No 2 Yes)": retinal_code, "L DR(1 No 2 Yes)": retinal_code,
        "high myopia(1 No 2 Yes)": myopia_code, "L high myopia(1 No 2 Yes)": myopia_code,
    }
    result = real_provider.analyze_tabular(supplied)
    return render(request, "real_lab.html", page="real_lab", tabular_result=result, fusion_result=None, form=request.query_params)


@app.post("/real-lab/fusion", response_class=HTMLResponse)
async def real_lab_fusion(
    request: Request, eye_side: str = Form("Right"), reflection: int = Form(0),
    image_quality: str = Form("Good"), illumination_type: str = Form("Diffuse Illumination"),
    image: UploadFile | None = File(None), csrf: str = Form(...),
):
    require_user(request); verify_csrf(request, csrf)
    image=await _image_upload(request,image)
    context = {"eye_side": eye_side, "reflection": int(bool(reflection)), "image_quality": image_quality,
               "slit_lamp_illumination_type": illumination_type}
    result = real_provider.analyze_fusion(await image.read(), "slit_lamp", context)
    return render(request, "real_lab.html", page="real_lab", tabular_result=None, fusion_result=result, form={})


@app.get("/real-reports/{model}/{filename}")
def real_report_asset(request: Request, model: str, filename: str):
    require_user(request)
    if model not in {"cataract_grade_multidata_real", "clinical_fusion_catscreen_real"} or filename not in {"training_curves.png", "tuning_history.png", "test_confusion_matrix.png", "metrics.json", "predictions_and_splits.csv"}:
        raise HTTPException(404, "Real model report not found")
    root = (ROOT / "models" / model).resolve(); target = (root / filename).resolve()
    if not target.is_relative_to(root) or not target.exists():
        raise HTTPException(404, "Real model report not found")
    media = {".png":"image/png", ".json":"application/json", ".csv":"text/csv"}[target.suffix.lower()]
    return Response(target.read_bytes(), media_type=media, headers={"Content-Disposition":"inline"})


@app.get("/simulation", response_class=HTMLResponse)
def simulation_lab(request: Request, scenario: int = 0):
    if not read_session(request):
        return redirect_login("/simulation")
    if read_session(request)["r"]=="doctor": return RedirectResponse("/doctor",status_code=303)
    scenario = max(0, min(11, scenario))
    synthetic_grade = scenario % 4
    seed = 9_000_000 + scenario * 7919
    result = synthetic_provider.predict(seed, synthetic_grade)
    result["grade_name"] = GRADE_NAMES[result["grade_prediction"]]
    result["fusion_name"] = GRADE_NAMES[result["fusion_prediction"]]
    result["truth_name"] = GRADE_NAMES[synthetic_grade]
    result["grade_rows"] = list(zip(GRADE_NAMES, result["grade_probabilities"]))
    result["fusion_rows"] = list(zip(GRADE_NAMES, result["fusion_probabilities"]))
    return render(request, "simulation.html", page="simulation", scenario=scenario, result=result, grade_names=GRADE_NAMES)


@app.get("/simulation/image/{scenario}.png")
def simulation_image(request: Request, scenario: int):
    require_user(request)
    scenario = max(0, min(11, scenario))
    return Response(synthetic_provider.image_png(9_000_000 + scenario * 7919, scenario % 4), media_type="image/png", headers={"Cache-Control":"private, max-age=3600"})


@app.get("/synthetic-reports/{model}/{filename}")
def synthetic_report_asset(request: Request, model: str, filename: str):
    require_user(request)
    if model not in {"cataract_grade_synthetic", "clinical_fusion_synthetic"} or filename not in {"training_curves.png","confusion_matrix.png","metrics.json","classification_report.json"}:
        raise HTTPException(404, "Synthetic report not found")
    root = (ROOT / "reports" / model).resolve(); target = (root / filename).resolve()
    if not target.is_relative_to(root) or not target.exists():
        raise HTTPException(404, "Synthetic report not found")
    media = "image/png" if target.suffix == ".png" else "application/json"
    return Response(target.read_bytes(), media_type=media, headers={"Content-Disposition":"inline"})


@app.get("/reports/{filename}")
def report_asset(request: Request, filename: str):
    require_user(request)
    if Path(filename).name != filename or Path(filename).suffix.lower() not in {".png", ".csv", ".md", ".html"}:
        raise HTTPException(404, "Report not found")
    target = (REPORT_DIR / filename).resolve()
    if not target.is_relative_to(REPORT_DIR.resolve()) or not target.exists():
        raise HTTPException(404, "Report not found")
    media = {".png":"image/png", ".csv":"text/csv", ".md":"text/markdown", ".html":"text/html"}[target.suffix.lower()]
    return Response(target.read_bytes(), media_type=media, headers={"Content-Disposition": "inline"})


@app.get("/evidence/{filename}")
def evidence_pdf(request: Request, filename: str):
    require_user(request)
    allowed = {"cataract_grade_multidata_model_readiness.pdf", "clinical_fusion_model_readiness.pdf", "fundus_v3_model_evidence.pdf", "synthetic_cataract_grade_model_evidence.pdf", "synthetic_clinical_fusion_model_evidence.pdf", "catatriage_full_agents_and_models_report.pdf", "real_models_and_agents_evidence.pdf"}
    if filename not in allowed:
        raise HTTPException(404, "Evidence report not found")
    target = (EVIDENCE_DIR / filename).resolve()
    if not target.is_relative_to(EVIDENCE_DIR.resolve()) or not target.exists():
        raise HTTPException(404, "Evidence report not found")
    return Response(target.read_bytes(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    if not read_session(request): return redirect_login("/audit")
    with connection() as con: rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 250").fetchall()
    return render(request, "audit.html", page="audit", entries=rows)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    if not read_session(request): return redirect_login("/about")
    return render(request, "about.html", page="about")


@app.get("/export/queue.csv")
def export_queue(request: Request):
    user = require_user(request, "admin")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["case_id","patient_alias","approved_tier","approved_by","waiting_since","status","scheduled_date","data_scope"])
    with connection() as con:
        rows = con.execute("SELECT c.case_id,c.patient_alias,c.approved_tier,c.approved_by,c.waiting_since,c.status,a.scheduled_date FROM cases c LEFT JOIN appointments a USING(case_id) WHERE c.approved_tier IS NOT NULL ORDER BY c.approved_tier,c.waiting_since").fetchall()
        for row in rows: writer.writerow([*row, "SIMULATED DEMO DATA"])
        audit(con, user["u"], user["r"], "queue_export", None, f"Exported {len(rows)} fictional queue rows.")
    return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=catatriage_demo_queue.csv"})


@app.get("/cases/{case_id}/print", response_class=HTMLResponse)
def print_case(request: Request, case_id: str):
    if not read_session(request): return redirect_login(request.url.path)
    require_assignment(read_session(request),case_id)
    with connection() as con: row = _case(con, case_id)
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    return render(request, "print_case.html", case=row, analysis=analysis)


@app.post("/admin/reset")
def reset_demo(request: Request, confirmation: str = Form(...), csrf: str = Form(...)):
    user = require_user(request, "admin"); verify_csrf(request, csrf)
    if os.getenv("CATATRIAGE_HOSTED")=="true":
        raise HTTPException(403,"Reset is disabled on the hosted demonstration.")
    if confirmation != "RESET DEMO":
        raise HTTPException(400, "Type RESET DEMO to confirm.")
    for item in UPLOAD_DIR.glob("*"):
        if item.is_file(): item.unlink()
    reset_database()
    initialize_role_databases(force_reset=True)
    with connection() as con: audit(con, user["u"], user["r"], "demo_reset", None, "Reset fictional database and removed demo uploads.")
    return RedirectResponse("/", status_code=303)


@app.post("/api/analyze")
async def api_analyze(request: Request, modality: str = Form(...), image: UploadFile | None = File(None), csrf: str = Form(...)):
    require_user(request); verify_csrf(request, csrf)
    image=await _image_upload(request,image)
    if modality not in {"fundus", "slit_lamp"}: raise HTTPException(400, "Unsupported modality")
    try:
        payload = await image.read()
        result = provider.analyze(payload, modality) if modality == "fundus" else real_provider.analyze_fusion(payload, modality, {})
    except ImageValidationError as exc: raise HTTPException(400, str(exc)) from exc
    return result

