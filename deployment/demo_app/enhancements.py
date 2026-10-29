"""Doctor account editing and doctor-month / admin-date handoff."""
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter,File,Form,HTTPException,Request,UploadFile
from fastapi.responses import JSONResponse,RedirectResponse
from . import doctor_account,month_planning,surgery_alerts

router=APIRouter()


def core():
    from . import main
    return main


def doctor(request):
    from .mobile_api import doctor as require_doctor
    return require_doctor(request)


def profile_context(m,user):
    with m.connection() as con:
        profile=dict(con.execute('SELECT * FROM doctor_profiles WHERE username=?',(user['u'],)).fetchone())
        name=doctor_account.login_name(con,user['u'])
    return {'profile':profile,'login_name':name,'username':user['u']}


@router.get('/doctor/profile')
def profile_page(request:Request):
    m=core();user=doctor(request)
    return m.render(request,'doctor_profile.html',page='profile',**profile_context(m,user),saved=request.query_params.get('saved')=='1')


@router.get('/api/mobile/profile')
def profile_api(request:Request): return profile_context(core(),doctor(request))


@router.get('/api/surgery/pending')
def pending_summary(request:Request):
    user=core().require_user(request)
    rows=surgery_alerts.for_request(request,user)
    return JSONResponse({'count':len(rows),'href':'/surgery/pending'},headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/surgery/pending')
def pending_surgery_page(request:Request):
    m=core();user=m.require_user(request)
    rows=surgery_alerts.for_request(request,user)
    with m.connection() as con:
        for row in rows:
            plan=month_planning.current_plan(con,m._case(con,row['case_id']),row['doctor_username'])
            row['needs_review']=not plan or not plan['is_current']
    return m.render(request,'pending_surgeries.html',page='calendar',pending_cases=rows)


@router.get('/api/mobile/profile/image')
def mobile_profile_image(request:Request):
    user=doctor(request)
    return core().doctor_profile_image(request,user['u'])


@router.post('/doctor/profile')
@router.post('/api/mobile/profile')
async def save_profile(request:Request,new_login_name:str=Form(...,max_length=60),current_password:str=Form('',max_length=128),csrf:str=Form(...),username:str=Form(''),profile_image:UploadFile|None=File(None)):
    m=core();user=doctor(request);m.verify_csrf(request,csrf)
    if username!=user['u']: raise HTTPException(403,'You may edit only your own profile.')
    upload=await m._image_upload(request,profile_image,'profile_image',required=False)
    payload=None;image_name=None
    if upload and upload.filename:
        payload=await upload.read(8*1024*1024+1);_,meta=m.validate_image_bytes(payload)
        image_name=uuid4().hex+'.'+{'JPEG':'jpg','PNG':'png','WEBP':'webp'}[meta['format']]
    # Password verification and uniqueness checks happen before any file is written.
    with m.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        try: renamed=doctor_account.update_login(con,user['u'],new_login_name,current_password)
        except HTTPException as error:
            if error.status_code==400 and 'current password' in str(error.detail):
                m.account_security.failed(con,'profile-rename:'+user['u'])
                # Return normally so the rate-limit update commits.
                return JSONResponse({'error':str(error.detail)},status_code=400) if request.url.path.startswith('/api/') else m.render(request,'error.html',response_status=400,status_code=400,message=str(error.detail))
            raise
        if image_name and not m.cloud_database.enabled(): m.DOCTOR_IMAGE_DIR.mkdir(parents=True,exist_ok=True)
        if image_name:
            m.file_store.write(m.DOCTOR_IMAGE_DIR/image_name,payload)
            con.execute('UPDATE doctor_profiles SET profile_image=? WHERE username=?',(image_name,user['u']))
        m.audit(con,user['u'],'doctor','doctor_profile_updated',None,f'login_name_changed={renamed}; profile_image_changed={bool(image_name)}; internal ownership unchanged')
    if image_name: m.sync_doctor_directory()
    if request.url.path.startswith('/api/'):
        response=JSONResponse({'saved':True,'renamed':renamed,'login_name':new_login_name.strip().lower()})
    else: response=RedirectResponse('/login/doctor?username='+m.quote(new_login_name.strip().lower()) if renamed else '/doctor/profile?saved=1',status_code=303)
    if renamed: response.delete_cookie('catatriage_session')
    return response


def month_context(m,user,case):
    with m.connection() as con: plan=month_planning.current_plan(con,case,user['u'])
    inputs=json.loads(plan['assessment_json']) if plan else {'functional_impact':'unknown','progression':'unknown','planning_preference':'balanced'}
    return {'month_plan':plan,'month_assessment':inputs,'evidence_hash':month_planning.evidence_hash(case)}


def month_suggestion(request,case_id,csrf,symptoms,notes,impact,progression,preference):
    m=core();user=doctor(request);m.verify_csrf(request,csrf);m.require_assignment(user,case_id)
    inputs=month_planning.assessment(impact,progression,preference)
    with m.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('UPDATE cases SET symptoms=?,notes=? WHERE case_id=?',(symptoms.strip(),notes.strip(),case_id))
        case=dict(m._case(con,case_id))
    # Provider calls happen outside a database transaction that writes patient records.
    digest=month_planning.evidence_hash(case)
    with m.connection() as con: result=month_planning.suggest_month(case,con,user['u'],inputs)
    result['evidence_hash']=digest
    with m.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if month_planning.evidence_hash(m._case(con,case_id))!=digest: raise HTTPException(409,'Clinical evidence changed. Refresh the case before planning.')
        existing=month_planning.current_plan(con,case,user['u'])
        keep=existing and existing['is_current'] and existing['assessment_json']==json.dumps(inputs)
        con.execute('''INSERT INTO surgery_month_plans(case_id,doctor_username,suggested_month,evidence_hash,assessment_json,suggestion_json) VALUES(?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET doctor_username=excluded.doctor_username,suggested_month=excluded.suggested_month,evidence_hash=excluded.evidence_hash,assessment_json=excluded.assessment_json,suggestion_json=excluded.suggestion_json''',(case_id,user['u'],result.get('suggested_month'),digest,json.dumps(inputs),json.dumps(result)))
        if not keep: con.execute("UPDATE surgery_month_plans SET approved_month=NULL,approved_by=NULL,approved_at=NULL,approval_reason='' WHERE case_id=?",(case_id,))
        m.audit(con,user['u'],'doctor','surgery_month_suggested',case_id,f"provider={result['provider']}; month={result.get('suggested_month')}; model_confidence_not_used_for_delay=true")
    return result


@router.post('/doctor/review/{case_id}/month')
@router.post('/api/mobile/patients/{case_id}/month')
def approve_month(request:Request,case_id:str,approved_month:str=Form(...),reason:str=Form(...,min_length=8,max_length=5000),attestation:str=Form(...),evidence_hash:str=Form(...),functional_impact:str=Form(...),progression:str=Form(...),planning_preference:str=Form(...),csrf:str=Form(...)):
    m=core();user=doctor(request);m.verify_csrf(request,csrf);m.require_assignment(user,case_id)
    month_planning.month_value(approved_month);inputs=month_planning.assessment(functional_impact,progression,planning_preference)
    if len(reason.strip())<8: raise HTTPException(400,'Enter a meaningful clinical reason for the month.')
    if attestation!='yes' or inputs['functional_impact']=='unknown' or inputs['progression']=='unknown': raise HTTPException(400,'Record your assessment and confirm that this elective planning month is appropriate.')
    with m.connection() as con:
        con.execute('BEGIN IMMEDIATE');case=dict(m._case(con,case_id));digest=month_planning.evidence_hash(case)
        if digest!=evidence_hash: raise HTTPException(409,'Clinical evidence changed. Review the latest record before approving a month.')
        if not case['approved_tier'] or m.clinical_review(case)['surgery_hold']: raise HTTPException(409,'Record an independent priority review and resolve acute warnings or refusal before approving a month.')
        slots=month_planning.free_slots(con,user['u'],approved_month,case_id)
        earliest=m.clinical_context(case)['doctor_earliest_date']
        if earliest: slots=[x for x in slots if x['date']>=earliest]
        if not slots: raise HTTPException(409,'No working slot is currently available in this month. Review availability before approving.')
        con.execute('''INSERT INTO surgery_month_plans(case_id,doctor_username,approved_month,approval_reason,approved_by,approved_at,evidence_hash,assessment_json) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(case_id) DO UPDATE SET doctor_username=excluded.doctor_username,approved_month=excluded.approved_month,approval_reason=excluded.approval_reason,approved_by=excluded.approved_by,approved_at=excluded.approved_at,evidence_hash=excluded.evidence_hash,assessment_json=excluded.assessment_json''',(case_id,user['u'],approved_month,reason.strip(),user['u'],m.now_iso(),digest,json.dumps(inputs)))
        m.audit(con,user['u'],'doctor','surgery_month_approved',case_id,'Doctor approved '+approved_month+'; exact date reserved for admin; '+reason.strip())
    return {'approved':True,'approved_month':approved_month} if request.url.path.startswith('/api/') else RedirectResponse('/doctor/review/'+case_id,status_code=303)


@router.get('/admin/surgery')
def planning_board(request:Request):
    m=core();m.require_user(request,'admin')
    with m.role_connection(m.DOCTOR_DB_PATH) as con: assignments={r['case_id']:dict(r) for r in con.execute('SELECT * FROM patient_profiles')}
    with m.connection() as con:
        cases=[dict(r) for r in con.execute("SELECT * FROM cases WHERE is_archived=0 AND approved_tier IS NOT NULL ORDER BY approved_tier,waiting_since")]
        for case in cases:
            case['patient']=assignments.get(case['case_id'],{})
            case['plan']=month_planning.current_plan(con,case,case['patient'].get('doctor_username',''))
    return m.render(request,'month_board.html',page='queue',cases=cases)


@router.get('/admin/surgery/{case_id}')
@router.post('/admin/surgery/{case_id}/assistant')
def admin_calendar(request:Request,case_id:str,csrf:str=Form('')):
    m=core();user=m.require_user(request,'admin');patient=m.require_assignment(user,case_id)
    if request.method=='POST': m.verify_csrf(request,csrf)
    with m.connection() as con:
        case=dict(m._case(con,case_id));plan=month_planning.require_approved(con,case,patient['doctor_username'])
        if request.method=='POST': suggestion=month_planning.admin_suggestion(con,case,patient['doctor_username'])
        else: suggestion={'selected':None,'candidates':month_planning.free_slots(con,patient['doctor_username'],plan['approved_month'],case_id),'reason_points':[]}
    return m.render(request,'admin_month_calendar.html',page='calendar',case=case,patient=patient,plan=plan,suggestion=suggestion)
