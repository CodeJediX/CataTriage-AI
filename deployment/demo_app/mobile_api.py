"""Native doctor API using the existing expiring sessions and real CSRF tokens.

Workflow writes delegate to the same business rules as the website. No server
credentials or provider keys are distributed to Android.
"""
import json
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

router=APIRouter(prefix="/api/mobile")


def core():
    from . import main
    return main


def doctor(request, allow_password_change=False):
    user=core().require_user(request,"doctor")
    if user.get("must_change") and not allow_password_change:
        raise HTTPException(403,"Change your temporary password before opening patient records.")
    return user


def response_context(response):
    if response.status_code>=400:
        context=getattr(response,"context",{})
        raise HTTPException(response.status_code,context.get("error") or context.get("booking_error") or "Request could not be completed.")
    return getattr(response,"context",{})


@router.get("/bootstrap")
def bootstrap(request:Request):
    m=core(); csrf=m.ensure_csrf(request)
    response=JSONResponse({"csrf":csrf,"api_version":1},headers={"Cache-Control":"no-store"})
    response.set_cookie("catatriage_csrf",csrf,httponly=True,samesite="strict",secure=request.url.scheme=="https")
    return response


@router.post("/login")
def login(request:Request,username:str=Form(...,max_length=80),password:str=Form(...,max_length=128),csrf:str=Form(...)):
    result=core().login(request,username,password,csrf,"/doctor","doctor")
    if result.status_code!=303:
        context=getattr(result,"context",{})
        raise HTTPException(429 if result.status_code==429 else 401,context.get("error") or "Doctor sign-in failed.")
    response=JSONResponse({"signed_in":True,"must_change":"password" in result.headers.get("location","")})
    for name,value in result.raw_headers:
        if name.lower()==b"set-cookie": response.raw_headers.append((name,value))
    return response


@router.get("/me")
def me(request:Request):
    user=doctor(request,True); m=core()
    with m.connection() as con:
        profile=con.execute("SELECT * FROM doctor_profiles WHERE username=?",(user["u"],)).fetchone()
    return {"username":user["u"],"name":user["n"],"must_change":user["must_change"],"profile":dict(profile) if profile else {}}


@router.post("/password")
def password(request:Request,username:str=Form(...,max_length=80),current_password:str=Form(...,max_length=128),new_password:str=Form(...,max_length=128),confirmation:str=Form(...,max_length=128),csrf:str=Form(...)):
    user=doctor(request,True)
    if username.strip().lower()!=user["u"]: raise HTTPException(403,"Change only your own password.")
    result=core().change_doctor_password(request,username,current_password,new_password,confirmation,csrf)
    response_context(result)
    response=JSONResponse({"changed":True,"message":"Password changed. Sign in again."})
    response.delete_cookie("catatriage_session")
    return response


def assigned(user):
    m=core()
    with m.role_connection(m.DOCTOR_DB_PATH) as con:
        patients=[dict(r) for r in con.execute("SELECT * FROM patient_profiles WHERE doctor_username=? ORDER BY full_name",(user["u"],))]
    active=m._active_case_ids()
    return [p for p in patients if p["case_id"] in active]


@router.get("/workspace")
def workspace(request:Request):
    m=core(); user=doctor(request); patients=assigned(user); ids={p["case_id"] for p in patients}
    with m.connection() as con:
        cases={r["case_id"]:dict(r) for r in con.execute("SELECT case_id,age,eye,modality,status,approved_tier,analysis_status,waiting_since FROM cases WHERE is_archived=0") if r["case_id"] in ids}
        appointments=[{**dict(r),"kind":"Consultation"} for r in con.execute("SELECT a.*,c.patient_alias FROM appointments a JOIN cases c USING(case_id) ORDER BY scheduled_date,slot") if r["case_id"] in ids]
        appointments += [{**dict(r),"scheduled_date":r["surgery_date"],"kind":"Surgery"} for r in con.execute("SELECT s.*,c.patient_alias FROM surgeries s JOIN cases c USING(case_id) WHERE s.status='confirmed' ORDER BY surgery_date,slot") if r["case_id"] in ids]
        staff=[dict(r) for r in con.execute("SELECT u.username,u.display_name,u.role FROM users u LEFT JOIN doctor_profiles d USING(username) WHERE u.role='admin' OR (u.role='doctor' AND d.is_active=1) ORDER BY u.display_name")]
        unread=con.execute("SELECT COUNT(*) FROM staff_messages WHERE recipient=? AND read_at IS NULL",(user["u"],)).fetchone()[0]
        leaves=[dict(r) for r in con.execute("SELECT * FROM leave_requests WHERE doctor_username=? ORDER BY leave_date DESC",(user["u"],))]
    with m.role_connection(m.DOCTOR_DB_PATH) as con:
        notifications=[dict(r) for r in con.execute("SELECT * FROM notifications WHERE doctor_username=? ORDER BY is_read,due_date",(user["u"],))]
        directory=[dict(r) for r in con.execute("SELECT * FROM doctor_directory ORDER BY display_name") if r["username"] in {s["username"] for s in staff}]
    return {"patients":[{**p,**cases.get(p["case_id"],{})} for p in patients],"appointments":sorted(appointments,key=lambda a:(a["scheduled_date"],a["slot"])),"staff":staff,"directory":directory,"notifications":notifications,"unread":unread,"leaves":leaves,"today":m.date.today().isoformat()}


@router.get("/patients/{case_id}")
def patient(request:Request,case_id:str):
    m=core(); user=doctor(request); profile=m.require_assignment(user,case_id)
    with m.connection() as con:
        record=dict(m._case(con,case_id))
        images=[dict(r) for r in con.execute("SELECT id,case_id,eye_side,analysis_json,created_at FROM case_images WHERE case_id=? ORDER BY id DESC",(case_id,))]
        history=[dict(r) for r in con.execute("SELECT action,timestamp,details FROM audit_log WHERE case_id=? ORDER BY id DESC LIMIT 40",(case_id,))]
        surgery=con.execute("SELECT * FROM surgeries WHERE case_id=?",(case_id,)).fetchone()
    analysis=json.loads(record.pop("analysis_json") or "{}")
    record.pop("image_path",None); record.pop("image_sha256",None)
    summary=m.summarize_eyes(images,analysis); current,older=m.partition_images(images,analysis)
    for item in images: item["analysis"]=json.loads(item.pop("analysis_json") or "{}")
    with m.role_connection(m.DOCTOR_DB_PATH) as con:
        assessments=[dict(r) for r in con.execute("SELECT * FROM self_assessments WHERE case_id=? ORDER BY id DESC",(case_id,))]
        messages=[dict(r) for r in con.execute("SELECT * FROM messages WHERE case_id=? ORDER BY id DESC LIMIT 50",(case_id,))]
    return {"patient":dict(profile),"case":record,"analysis":analysis,"images":current,"older_images":older,"eye_summary":summary,"history":history,"assessments":assessments,"messages":messages,"surgery":dict(surgery) if surgery else None}


@router.get("/images/{image_id}")
def image(request:Request,image_id:int):
    doctor(request)
    return core().clinical_image(request,image_id)


@router.get("/mailbox")
def mailbox(request:Request,box:str="inbox"):
    doctor(request)
    context=core().mailbox(request,box).context
    return {key:context[key] for key in ("messages","unread")}


@router.post("/messages")
def send(request:Request,recipient:str=Form(...),subject:str=Form(...,min_length=2,max_length=120),body:str=Form(...,min_length=2,max_length=5000),category:str=Form("other"),csrf:str=Form(...)):
    doctor(request)
    response_context(core().send_mailbox_message(request,recipient,subject,body,category,"",csrf))
    return {"saved":True}


@router.post("/messages/{message_id}/read")
def read(request:Request,message_id:int,csrf:str=Form(...)):
    doctor(request); core().read_mailbox_message(request,message_id,csrf)
    return {"read":True}


@router.post("/patients/{case_id}/notes")
def notes(request:Request,case_id:str,symptoms:str=Form("",max_length=20000),notes:str=Form("",max_length=20000),csrf:str=Form(...)):
    m=core(); user=doctor(request); m.verify_csrf(request,csrf); m.require_assignment(user,case_id)
    with m.connection() as con:
        con.execute("UPDATE cases SET symptoms=?,notes=? WHERE case_id=?",(symptoms.strip(),notes.strip(),case_id))
        m.audit(con,user["u"],"doctor","clinical_context_updated",case_id,"Doctor updated symptoms and clinical notes using Android.")
    return {"saved":True}


@router.post("/patients/{case_id}/review")
def review(request:Request,case_id:str,decision:str=Form(...),tier:str=Form(""),reason:str=Form(...,min_length=8,max_length=20000),csrf:str=Form(...)):
    doctor(request); core().review_case(request,case_id,decision,tier,reason,csrf)
    return {"saved":True}


@router.post("/patients/{case_id}/suggestion")
def suggestion(request:Request,case_id:str,symptoms:str=Form("",max_length=20000),notes:str=Form("",max_length=20000),csrf:str=Form(...)):
    doctor(request)
    return {"suggestion":response_context(core().surgery_suggestion(request,case_id,csrf,"1",symptoms,notes))["suggestion"]}


@router.post("/patients/{case_id}/surgery")
def surgery(request:Request,case_id:str,surgery_date:str=Form(...),slot:str=Form(...),rationale:str=Form(...,min_length=8,max_length=20000),csrf:str=Form(...)):
    m=core(); user=doctor(request)
    result=m.confirm_surgery(request,case_id,surgery_date,slot,rationale,csrf); response_context(result)
    from urllib.parse import urlparse,parse_qs
    token=parse_qs(urlparse(result.headers["location"]).query)["confirmation"][0]
    with m.connection() as con:
        notice=dict(con.execute("SELECT * FROM outbound_notifications WHERE confirmation_token=? AND doctor_username=?",(token,user["u"])).fetchone())
    return {"confirmed":True,"message":notice["body"],"delivery_status":notice["delivery_status"],"delivery_detail":notice["delivery_detail"],"manual_link":m.communications.whatsapp_link(notice["recipient_phone"],notice["body"])}


@router.post("/intake")
async def intake(request:Request,case_id:str=Form(...),modality:str=Form(...),symptoms:str=Form("",max_length=20000),notes:str=Form("",max_length=20000),illumination_type:str=Form("Diffuse Illumination"),left_images:list[UploadFile]=File([]),right_images:list[UploadFile]=File([]),unknown_images:list[UploadFile]=File([]),csrf:str=Form(...)):
    doctor(request)
    await core().registered_intake(request,case_id,modality,symptoms,notes,illumination_type,left_images,right_images,unknown_images,csrf)
    return {"saved":True}


@router.post("/leave")
def leave(request:Request,leave_date:str=Form(...),leave_type:str=Form(...),confirmed:str=Form(""),csrf:str=Form(...)):
    doctor(request)
    result=core().submit_leave(request,leave_date,leave_type,confirmed,csrf)
    context=response_context(result)
    if result.status_code==200: return {"needs_confirmation":True,"affected":[dict(r) for r in context["affected"]]}
    return {"saved":True}


@router.post("/grade")
def grade(request:Request,age:float=Form(...),gender:float=Form(...),ucva_right:float=Form(...),bcva_right:float=Form(...),ucva_left:float=Form(...),bcva_left:float=Form(...),outdoor_hours:float=Form(...),sunlight_code:float=Form(...),glaucoma_code:float=Form(...),retinal_code:float=Form(...),myopia_code:float=Form(...),csrf:str=Form(...)):
    doctor(request)
    result=core().real_lab_tabular(request,age,gender,ucva_right,bcva_right,ucva_left,bcva_left,outdoor_hours,sunlight_code,glaucoma_code,retinal_code,myopia_code,csrf)
    return {"analysis":response_context(result)["tabular_result"]}


@router.get("/models")
def models(request:Request):
    doctor(request); m=core()
    return {"models":[{"name":name,"metrics":json.loads((m.ROOT/"models"/folder/"metrics.json").read_text())} for name,folder in (("Multi-data grade model","cataract_grade_multidata_real"),("Clinical fusion imaging model","clinical_fusion_catscreen_real"))]}


@router.post("/logout")
def logout(request:Request,csrf:str=Form(...)):
    core().verify_csrf(request,csrf)
    response=JSONResponse({"signed_out":True}); response.delete_cookie("catatriage_session")
    return response
