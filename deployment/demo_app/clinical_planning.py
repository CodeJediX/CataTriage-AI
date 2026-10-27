"""Guideline-informed review prompts, not a validated medical timing model."""
from __future__ import annotations

import re
from datetime import date

SOURCES=[
    {"title":"NICE: cataract referral and preoperative assessment","url":"https://www.nice.org.uk/guidance/ng77/chapter/recommendations"},
    {"title":"National Eye Institute: cataract surgery","url":"https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/cataracts/cataract-surgery"},
    {"title":"NHS: sudden visual changes requiring urgent assessment","url":"https://www.nhs.uk/tests-and-treatments/cataract-surgery/"},
]
FEATURES={
    "blurred_vision":("Blurred or reduced vision",r"\b(?:blur(?:red|ry)?|reduced|poor|cloudy|worsening) (?:vision|eyesight)\b"),
    "gradual_change":("Gradual visual change",r"\b(?:gradual(?:ly)?|progressive(?:ly)?|over (?:several |many )?(?:months|years))\b"),
    "glare":("Glare or light sensitivity",r"\b(?:glare|halos?|light sensitiv(?:ity|e)|photophobia)\b"),
    "night_vision":("Difficulty seeing or driving at night",r"\b(?:night (?:vision|driving)|trouble seeing at night|difficulty (?:seeing|driving) at night)\b"),
    "reading_impact":("Reading affected",r"\b(?:difficulty|trouble|unable|cannot|can't|struggling|problems?)(?:\W+\w+){0,3}\W+read(?:ing)?\b|\bread(?:ing)? (?:difficulty|affected|impaired)\b"),
    "driving_impact":("Driving affected",r"\b(?:difficulty|trouble|unable|cannot|can't|unsafe|stopped)(?:\W+\w+){0,3}\W+driv(?:ing|e)\b|\bnight driving\b"),
    "daily_activities":("Daily activities affected",r"\b(?:daily (?:activities|life|tasks)|activities of daily living|ADLs?|functional (?:decline|limitation|impairment))\b"),
    "falls":("Falls or mobility concerns",r"\b(?:falls?|falling|mobility (?:problems?|limitation|concerns?))\b"),
    "sudden_vision_change":("Sudden visual loss or sudden blurring",r"\b(?:sudden(?:ly)?|acute|rapid)\W+(?:\w+\W+){0,3}(?:vision loss|loss of vision|visual loss|blur(?:red|ring)?(?: vision)?|reduction in vision)\b|\bvision (?:loss|change) (?:today|suddenly)\b"),
    "severe_eye_pain":("Severe eye pain",r"\b(?:severe|bad|intense)\W+(?:eye\W+)?pain\b|\beye pain(?: is)? severe\b"),
    "flashes":("Flashes of light",r"\bflashes?(?: of light)?\b"),
    "new_floaters":("New or increasing floaters",r"\b(?:new|sudden|increased|increasing|many)\W+(?:\w+\W+){0,2}floaters\b"),
    "curtain_shadow":("Curtain or shadow across vision",r"\b(?:curtain|dark shadow|visual field (?:loss|defect))\b"),
    "diabetes":("Diabetes mentioned",r"\bdiabet(?:es|ic)\b"),
    "hypertension":("Hypertension mentioned",r"\b(?:hypertension|high blood pressure)\b"),
    "retinal_disease":("Retinal comorbidity mentioned",r"\b(?:retinopathy|macular degeneration|retinal disease|AMD)\b"),
    "glaucoma":("Glaucoma mentioned",r"\bglaucoma\b"),
    "inflammation":("Eye infection or inflammation mentioned",r"\b(?:uveitis|eye infection|ocular infection|ocular inflammation|active inflammation)\b"),
    "anticoagulants":("Anticoagulant or antiplatelet use mentioned",r"\b(?:anticoagulan\w*|antiplatelet\w*|warfarin|apixaban|rivaroxaban|aspirin|clopidogrel)\b"),
    "only_functional_eye":("Only one functional eye mentioned",r"\b(?:only (?:one |a |the )?(?:functional|seeing|good) eye|monocular)\b"),
    "acuity_recorded":("Visual acuity is mentioned",r"\b(?:BCVA|UCVA|best.corrected visual acuity|visual acuity)\b"),
    "biometry_recorded":("Biometry is mentioned",r"\b(?:biometry|IOL calculation|axial length)\b"),
    "preoperative_pending":("Preoperative work is documented as pending",r"\b(?:biometry|IOL calculation|preoperative assessment|pre-operative assessment|consent)\s+(?:is\s+)?(?:pending|awaited|outstanding|incomplete)\b|\b(?:pending|awaiting)\s+(?:biometry|IOL calculation|preoperative assessment|pre-operative assessment|consent)\b"),
    "consent_discussed":("Consent or patient preference is mentioned",r"\b(?:consent|wants surgery|wishes (?:to have )?surgery|prefers surgery)\b"),
    "declines_surgery":("Patient declines surgery",r"\b(?:declines?|refuses?|does not want|doesn't want|not willing to have)\s+(?:cataract )?surgery\b"),
}
URGENT={"sudden_vision_change","severe_eye_pain","flashes","new_floaters","curtain_shadow"}
NEGATION=re.compile(r"\b(?:no|not|denies|denied|without|negative for|absence of)\b",re.I)


def _value(case,key):
    try: return str(case[key] or "")
    except (KeyError,IndexError): return ""


def _findings(text):
    found={}
    for code,(label,pattern) in FEATURES.items():
        states=[]
        for clause in re.split(r"[.!?;,\n]|\bbut\b",text[:20000],flags=re.I):
            for match in re.finditer(pattern,clause,re.I):
                before=" ".join(clause[:match.start()].split()[-5:])
                after=clause[match.end():match.end()+25]
                denied=bool(NEGATION.search(before) or re.match(r"\s*(?:denied|absent|not present)\b",after,re.I))
                states.append("explicitly_denied" if denied else "reported")
        if states: found[code]={"code":code,"label":label,"state":"reported" if "reported" in states else "explicitly_denied"}
    return list(found.values())


def clinical_context(case):
    fields={}
    for key in ("symptoms","notes"):
        text=_value(case,key).strip()
        durations=[{"value":int(match.group(1)),"unit":match.group(2).lower()} for match in re.finditer(r"\b(?:for|over|since|duration[: ]*)\s+(\d{1,3})\s*(days?|weeks?|months?|years?)\b",text,re.I)]
        fields[key]={"provided":bool(text),"findings":_findings(text),"duration_mentions":durations[:5]}
    reported={item["code"] for value in fields.values() for item in value["findings"] if item["state"]=="reported"}
    urgent=sorted(reported & URGENT)
    earliest=[]
    for key in ("symptoms","notes"):
        for match in re.finditer(r"\b(?:not before|earliest surgery date[: ]*)\s*(\d{4}-\d{2}-\d{2})\b",_value(case,key),re.I):
            try: earliest.append(date.fromisoformat(match.group(1)).isoformat())
            except ValueError: pass
    return {"doctor_reported_symptoms":fields["symptoms"],"doctor_clinical_notes":fields["notes"],
            "reported_features":sorted(reported),"urgent_features":urgent,
            "doctor_earliest_date":max(earliest) if earliest else None,
            "extraction_limit":"Keyword-based summary of the doctor's text; it may miss context. Verify against the original record. No raw notes or identifiers are sent."}


def clinical_review(case):
    context=clinical_context(case)
    reported=set(context["reported_features"])
    evidence=[]
    for key,title in (("doctor_reported_symptoms","Reported symptoms"),("doctor_clinical_notes","Clinical notes")):
        field=context[key]
        if not field["provided"]: evidence.append(title+": not provided.")
        elif not field["findings"]: evidence.append(title+": provided, but no supported clinical features were recognised. The doctor must interpret the original text.")
        else:
            evidence.extend(title+": "+item["label"]+(" (explicitly denied)." if item["state"]=="explicitly_denied" else " (reported; verify).") for item in field["findings"])
    advice=[]
    if context["urgent_features"]:
        advice.append("Prompt same-day ophthalmology assessment is needed for the flagged acute symptoms. Do not treat an elective cataract date as the response to sudden vision changes or severe eye pain.")
    if "declines_surgery" in reported:
        advice.append("The record indicates that the patient declines surgery. Respect this preference and discuss options; do not treat an AI-proposed date as consent.")
    if reported & {"reading_impact","driving_impact","daily_activities","night_vision","glare","falls"}:
        advice.append("Discuss how the reported visual symptoms affect reading, driving, mobility and daily life, and whether the patient wants surgery. Use this discussion with the examination when considering timing and the approved tier.")
    if "driving_impact" in reported or "night_vision" in reported:
        advice.append("Ask the patient to avoid driving when vision feels unsafe and arrange an assessment of visual function and driving suitability.")
    if reported & {"diabetes","retinal_disease","glaucoma","only_functional_eye"}:
        advice.append("Review the mentioned ocular or systemic conditions, retinal findings and individual complication risks before deciding the surgical plan. An image class alone cannot establish the expected benefit.")
    if "inflammation" in reported:
        advice.append("Clarify whether the documented eye infection or inflammation is active before considering elective surgery timing.")
    if "anticoagulants" in reported:
        advice.append("Review the documented medicines with the surgical team. This report does not instruct the patient to stop or change any medicine.")
    if "preoperative_pending" in reported:
        advice.append("The notes describe pending preoperative work. Confirm its completion and review the results before confirming a surgical plan.")
    missing=[]
    if not context["doctor_reported_symptoms"]["provided"]: missing.append("Doctor-reported symptoms and impact on daily life.")
    if not context["doctor_clinical_notes"]["provided"]: missing.append("Clinical examination notes and relevant medical history.")
    if "acuity_recorded" not in reported: missing.append("Documented visual acuity and examination findings; acuity alone must not decide access to surgery.")
    if "biometry_recorded" not in reported or "preoperative_pending" in reported: missing.append("Preoperative biometry/IOL planning and individual risk assessment.")
    if "consent_discussed" not in reported: missing.append("Patient preference, informed consent and postoperative support arrangements.")
    advice.append("The doctor must confirm the affected eye, examination findings, preoperative assessment and patient agreement before confirming a surgery date.")
    return {"context":context,"evidence":evidence,"advice":advice,"missing_information":missing,
            "urgent_review":bool(context["urgent_features"]),"surgery_hold":bool(context["urgent_features"] or "declines_surgery" in reported),"provider_label":"Guideline-informed review checks",
            "status":"Urgent assessment before elective planning" if context["urgent_features"] else "Doctor review required",
            "sources":SOURCES,"limitations":"This is a review aid, not a diagnosis, medical clearance or a validated prediction of the best surgery date."}
