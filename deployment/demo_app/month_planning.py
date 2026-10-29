"""Two-stage elective planning. Months are proposals, never validated waiting deadlines."""
import calendar
import hashlib
import json
from datetime import date,datetime,timedelta
from fastapi import HTTPException
from .clinical_planning import clinical_context,clinical_review
from .hospital import doctor_available,validated_date,valid_time
from . import planning_ai


def month_value(value):
    try:
        parsed=datetime.strptime(value,'%Y-%m')
        if parsed.strftime('%Y-%m')!=value: raise ValueError()
    except (ValueError,TypeError): raise HTTPException(400,'Choose a valid month in YYYY-MM format.')
    today=date.today(); maximum=shift_month(today.strftime('%Y-%m'),12)
    if value<today.strftime('%Y-%m') or value>maximum: raise HTTPException(400,'Choose this month or a month in the next 12 months.')
    return value


def shift_month(month,offset):
    y,m=map(int,month.split('-'));index=y*12+m-1+offset
    return f'{index//12:04d}-{index%12+1:02d}'


def evidence_hash(case):
    from . import main as m
    fields=('case_id','age','modality','eye','symptoms','notes','approved_tier','approval_reason','review_state','analysis_json','is_archived')
    evidence={key:case[key] for key in fields}
    with m.role_connection(m.DOCTOR_DB_PATH) as con:
        profile=con.execute('SELECT doctor_username,medical_history FROM patient_profiles WHERE case_id=?',(case['case_id'],)).fetchone()
    evidence['assignment_and_medical_history']=list(profile) if profile and not isinstance(profile,dict) else [profile['doctor_username'],profile['medical_history']] if profile else []
    return hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()


def assessment(impact,progression,preference):
    if impact not in {'unknown','mild','moderate','severe'} or progression not in {'unknown','stable','progressive'} or preference not in {'soon','balanced','later'}:
        raise HTTPException(400,'Choose the impact, progression and planning preference.')
    return {'functional_impact':impact,'progression':progression,'planning_preference':preference}


def conflict(con,doctor,day,slot,case_id):
    from . import main as m
    with m.role_connection(m.DOCTOR_DB_PATH) as dcon:
        ids={r[0] for r in dcon.execute('SELECT case_id FROM patient_profiles WHERE doctor_username=?',(doctor,))}
    for table,column in (('appointments','scheduled_date'),('surgeries','surgery_date')):
        extra=" AND status='confirmed'" if table=='surgeries' else ''
        if any(r[0] in ids for r in con.execute(f'SELECT case_id FROM {table} WHERE {column}=? AND slot=? AND case_id<>?{extra}',(day,slot,case_id))): return True
    return False


def free_slots(con,doctor,month,case_id):
    from . import main as m
    month_value(month);year,number=map(int,month.split('-'));capacity=con.execute('SELECT * FROM surgery_capacity WHERE id=1').fetchone()
    limit=min(capacity['max_surgeries_per_day'],capacity['available_beds'])
    profile=con.execute('SELECT * FROM doctor_profiles WHERE username=? AND is_active=1',(doctor,)).fetchone()
    if not profile: return []
    with m.role_connection(m.DOCTOR_DB_PATH) as dcon:
        ids={r[0] for r in dcon.execute('SELECT case_id FROM patient_profiles WHERE doctor_username=?',(doctor,))}
    busy=set()
    for table,column in (('appointments','scheduled_date'),('surgeries','surgery_date')):
        extra=" AND status='confirmed'" if table=='surgeries' else ''
        for row in con.execute(f'SELECT case_id,{column},slot FROM {table} WHERE {column} LIKE ? AND case_id<>?{extra}',(month+'%',case_id)):
            if row[0] in ids: busy.add((row[1],row[2]))
    leaves=[dict(r) for r in con.execute("SELECT leave_date,leave_type FROM leave_requests WHERE doctor_username=? AND leave_date LIKE ? AND status IN ('pending','approved','resolved')",(doctor,month+'%'))]
    counts={r[0]:r[1] for r in con.execute("SELECT surgery_date,COUNT(*) FROM surgeries WHERE surgery_date LIKE ? AND case_id<>? AND status='confirmed' GROUP BY surgery_date",(month+'%',case_id))}
    result=[]
    for day_number in range(1,calendar.monthrange(year,number)[1]+1):
        day=date(year,number,day_number)
        if day<date.today() or day.strftime('%a') not in profile['working_days'].split(','): continue
        occupied=counts.get(day.isoformat(),0)
        if occupied>=limit: continue
        start=datetime.strptime(profile['work_start'],'%H:%M');end=datetime.strptime(profile['work_end'],'%H:%M')
        while start<end:
            slot=start.strftime('%H:%M');start+=timedelta(minutes=30)
            from .hospital import leave_covers
            on_leave=any(x['leave_date']==day.isoformat() and leave_covers(x['leave_type'],slot) for x in leaves)
            if not on_leave and (day.isoformat(),slot) not in busy:
                result.append({'date':day.isoformat(),'slot':slot,'booked':int(occupied),'remaining_daily_capacity':int(limit-occupied)})
    return result


def suggest_month(case,con,doctor,inputs):
    medical=clinical_review(case)
    base={'suggested_month':None,'suggested_month_label':'Clinical assessment required','suggested_date':None,'advisory_only':True,'clinical_review':medical,'clinical_hold':medical['surgery_hold'],'assessment':inputs,'provider':'clinical_review_rules','provider_label':'Clinical review checks','external_data_sent':False,'candidate_months':[],'reason_points':[]}
    if medical['surgery_hold']:
        base['reason_points']=['Acute warning symptoms or a recorded refusal require clinician discussion before elective month planning.','No month or booking has been approved.'];return base
    if inputs['functional_impact']=='unknown' or inputs['progression']=='unknown' or not case['approved_tier']:
        base['reason_points']=['Record an independent priority tier, functional impact and progression before requesting a month.','An image percentage does not establish severity or how long the patient can safely wait.'];return base
    later=inputs['functional_impact']=='mild' and inputs['progression']=='stable' and inputs['planning_preference']=='later' and case['approved_tier']=='Tier 3'
    offset=3 if later else 0 if inputs['functional_impact']=='severe' or inputs['progression']=='progressive' or case['approved_tier']=='Tier 1' else 1
    months=[]
    earliest=clinical_context(case)['doctor_earliest_date']
    for index in range(offset,min(offset+4,13)):
        month=shift_month(date.today().strftime('%Y-%m'),index)
        if earliest and month<earliest[:7]: continue
        slots=free_slots(con,doctor,month,case['case_id'])
        if earliest: slots=[x for x in slots if x['date']>=earliest]
        if slots: months.append({'month':month,'free_days':len({x['date'] for x in slots}),'free_grid_slots':len(slots)})
    base['candidate_months']=months
    if not months: base['reason_points']=['No available month was found in the selected planning window. Review staffing, leave, beds and theatre capacity.'];return base
    selected=months[0]['month']
    points=[f"Doctor-recorded functional impact: {inputs['functional_impact']}; progression: {inputs['progression']}.",f"Doctor-approved priority: {case['approved_tier']}; planning preference: {inputs['planning_preference']}."]
    points.append('A later planning window was considered because the doctor recorded mild, stable impact, routine priority and a preference for later elective planning. This leaves near-term capacity visible for higher-priority patients.' if later else 'The planning window reflects the doctor-recorded impact, progression and priority rather than automatically choosing the closest month.')
    points += ['Doctor working days, leave, existing bookings, theatre capacity and available beds were checked.','The month is an operational proposal, not a medically validated safe waiting time. Reassess changing symptoms; the doctor must confirm suitability.','Image model confidence was not used to postpone care.']
    context={'assessment':inputs,'approved_tier':case['approved_tier'],'clinical_evidence':clinical_context(case),'candidate_months':months}
    ai=planning_ai.choose('Choose suggested_month from candidate_months. Explain only the supplied doctor-recorded evidence and capacity in 2–4 reason_points. Later mild/stable routine planning is an operational preference, never a guaranteed safe delay. Do not output an exact date.',context,'suggested_month',{x['month'] for x in months})
    selected=ai.get('suggested_month',selected)
    return {**base,**ai,'suggested_month':selected,'suggested_month_label':datetime.strptime(selected,'%Y-%m').strftime('%B %Y'),'reason_points':ai.get('reason_points',[])+points,'reason':'Month proposal for independent doctor approval. Exact dates are reserved for the hospital admin.'}


def current_plan(con,case,doctor):
    row=con.execute('SELECT * FROM surgery_month_plans WHERE case_id=?',(case['case_id'],)).fetchone()
    if not row: return None
    result=dict(row);result['is_current']=row['evidence_hash']==evidence_hash(case) and row['doctor_username']==doctor
    return result


def require_approved(con,case,doctor,day=None):
    plan=current_plan(con,case,doctor)
    if not plan or not plan['approved_month'] or not plan['is_current']: raise HTTPException(409,'A current doctor-approved surgery month is required. Changed clinical evidence or reassignment requires fresh approval.')
    if clinical_review(case)['surgery_hold']: raise HTTPException(409,'Clinical warning symptoms or patient refusal require doctor review first.')
    if day and day[:7]!=plan['approved_month']: raise HTTPException(409,'Choose a date within the doctor-approved month.')
    return plan


def admin_suggestion(con,case,doctor):
    plan=require_approved(con,case,doctor)
    slots=free_slots(con,doctor,plan['approved_month'],case['case_id'])
    earliest=clinical_context(case)['doctor_earliest_date']
    if earliest: slots=[x for x in slots if x['date']>=earliest]
    if case['approved_tier']=='Tier 1': slots.sort(key=lambda x:(x['date'],x['slot']))
    else: slots.sort(key=lambda x:(x['booked'],x['date'],x['slot']))
    if not slots: return {'selected':None,'candidates':[],'reason_points':['No free slot remains in the approved month. Ask the doctor to review the month; the admin cannot move it independently.']}
    candidates=slots[:80];allowed={x['date']+'T'+x['slot'] for x in candidates}
    ai=planning_ai.choose('Choose selected_slot (YYYY-MM-DDTHH:MM) from available_slots. Explain doctor availability, leave, workload, bed/theatre capacity and doctor-approved month using 2–4 reason_points. Do not change the month or priority. For higher priority consider earlier slots; otherwise distribute workload.',{'approved_month':plan['approved_month'],'doctor_approved_tier':case['approved_tier'],'available_slots':candidates},'selected_slot',allowed)
    chosen=ai.get('selected_slot',candidates[0]['date']+'T'+candidates[0]['slot']);selected=next(x for x in candidates if x['date']+'T'+x['slot']==chosen)
    return {**ai,'selected':selected,'candidates':slots,'reason_points':ai.get('reason_points',[])+[f"Within the doctor-approved month: {plan['approved_month']}.",'Assigned doctor is working and has no recorded leave or conflicting appointment at this time.',f"Current daily bookings: {selected['booked']}; remaining bed/theatre capacity: {selected['remaining_daily_capacity']}.",'The administrator must confirm; availability is checked again during booking.']}
