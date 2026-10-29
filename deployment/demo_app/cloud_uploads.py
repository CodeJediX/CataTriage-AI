"""Authenticated chunk uploads keep each Vercel request below its payload limit."""
import io
import json
import math
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from . import cloud_database

router=APIRouter()
CHUNK_SIZE=1024*1024


def _user(request):
    from .main import require_user, verify_csrf
    if not cloud_database.enabled(): raise HTTPException(404,"Cloud uploads are disabled.")
    user=require_user(request)
    if request.url.path.startswith('/api/mobile/'):
        from .mobile_api import doctor
        doctor(request)
    verify_csrf(request,request.headers.get("X-CSRF-Token", ""))
    return user


@router.post("/uploads/prepare")
@router.post("/api/mobile/uploads/prepare")
async def prepare(request:Request):
    from .hospital import require_assignment
    user=_user(request)
    data=await request.json()
    action=data.get("action",""); target=str(data.get("target", "")); field=data.get("field","")
    allowed={"/intake":{"left_images","right_images","unknown_images"},"/api/mobile/intake":{"left_images","right_images","unknown_images"},"/admin/doctors":{"profile_image"},
             "/doctor/profile":{"profile_image"},"/api/mobile/profile":{"profile_image"},
             "/support/quality-check":{"image"},"/real-lab/fusion":{"image"},"/api/analyze":{"image"}}
    if action.startswith("/cases/") and action.endswith("/analysis"):
        if target!=action.split("/")[2]: raise HTTPException(400,"Image target does not match this case.")
        require_assignment(user,target); allowed[action]={"image"}
    elif action in {"/intake","/api/mobile/intake"}:
        if user["r"]=="admin": raise HTTPException(403,"Clinical role required.")
        require_assignment(user,target)
    elif action in {'/doctor/profile','/api/mobile/profile'}:
        if user['r']!='doctor' or target!=user['u']: raise HTTPException(403,'Edit only your own profile.')
    elif action=="/admin/doctors":
        if user["r"]!="admin": raise HTTPException(403,"Administrator required.")
    elif action=="/support/quality-check":
        if user["r"]!="technician": raise HTTPException(403,"Technician required.")
    if action not in allowed or field not in allowed[action]: raise HTTPException(400,"Unsupported upload destination.")
    size=data.get("size")
    if not isinstance(size,int) or not 1<=size<=8388608: raise HTTPException(400,"Image must be 8 MB or smaller.")
    name=str(data.get("name","image"))[:180]
    identifier=uuid4().hex
    with cloud_database.connection() as con:
        con.execute("DELETE FROM pending_uploads WHERE expires_at<?",(int(time.time()),))
        if con.execute("SELECT COUNT(*) FROM pending_uploads WHERE owner_name=?",(user["u"],)).fetchone()[0]>=12:
            raise HTTPException(429,"Finish the current upload before starting another.")
        con.execute("INSERT INTO pending_uploads VALUES(?,?,?,?,?,?,?,?)",(identifier,user["u"],action,target,field,name,size,int(time.time())+1800))
    return {"id":identifier,"chunk_size":CHUNK_SIZE}


@router.post("/uploads/{identifier}/chunks/{index}")
@router.post("/api/mobile/uploads/{identifier}/chunks/{index}")
async def chunk(request:Request,identifier:str,index:int):
    user=_user(request)
    payload=await request.body()
    if len(payload)>CHUNK_SIZE: raise HTTPException(413,"Upload chunk is too large.")
    with cloud_database.connection() as con:
        row=con.execute("SELECT * FROM pending_uploads WHERE id=? AND owner_name=? AND expires_at>?",(identifier,user["u"],int(time.time()))).fetchone()
        if not row: raise HTTPException(404,"Upload expired or was not found.")
        count=math.ceil(row["expected_size"]/CHUNK_SIZE)
        expected=CHUNK_SIZE if index<count-1 else row["expected_size"]-index*CHUNK_SIZE
        if not 0<=index<count or len(payload)!=expected: raise HTTPException(400,"Invalid upload chunk.")
        con.execute("INSERT INTO upload_chunks VALUES(?,?,?) ON CONFLICT(upload_id,chunk_index) DO UPDATE SET content=excluded.content",(identifier,index,payload))
    return {"accepted":True}


async def restore(request:Request) -> dict:
    from .main import require_user, verify_csrf
    form=await request.form()
    raw=form.get("cloud_uploads", "")
    if not raw: return {}
    if not cloud_database.enabled(): raise HTTPException(400,"Cloud upload tokens are not supported here.")
    user=require_user(request); verify_csrf(request,str(form.get("csrf", "")))
    try:
        identifiers=json.loads(raw)
        if not isinstance(identifiers,list) or len(identifiers)>12 or len(set(identifiers))!=len(identifiers): raise ValueError()
    except (ValueError,TypeError): raise HTTPException(400,"Invalid upload list.")
    result={}
    target=str(form.get("case_id") or form.get("username") or "")
    if request.url.path.startswith("/cases/") and request.url.path.endswith("/analysis"): target=request.url.path.split("/")[2]
    with cloud_database.connection() as con:
        for identifier in identifiers:
            row=con.execute("SELECT * FROM pending_uploads WHERE id=? AND owner_name=? AND expires_at>?",(identifier,user["u"],int(time.time()))).fetchone()
            if not row or row["action_path"]!=request.url.path or row["target_id"]!=target:
                raise HTTPException(403,"Upload does not belong to this form or user.")
            chunks=con.execute("SELECT content FROM upload_chunks WHERE upload_id=? ORDER BY chunk_index",(identifier,)).fetchall()
            payload=b"".join(bytes(item[0]) for item in chunks)
            if len(payload)!=row["expected_size"]: raise HTTPException(400,"Upload is incomplete. Please select the image again.")
            result.setdefault(row["field_name"],[]).append(UploadFile(filename=row["original_name"],file=io.BytesIO(payload)))
            con.execute("DELETE FROM pending_uploads WHERE id=?",(identifier,))
    return result
