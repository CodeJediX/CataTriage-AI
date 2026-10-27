from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import date, timedelta
from .hospital import doctor_available
from .settings import advisory_settings, model_label
from .clinical_planning import clinical_context, clinical_review


def _capacity(con) -> int:
    row = con.execute("SELECT max_surgeries_per_day FROM surgery_capacity WHERE id=1").fetchone()
    return int(row[0]) if row else 6


def _candidate_dates(con, start_after_days: int, doctor: str, count: int = 14) -> list[dict]:
    capacity = _capacity(con)
    candidates = []
    cursor = date.today() + timedelta(days=max(1, start_after_days))
    attempts = 0
    while len(candidates) < count and attempts < 120:
        attempts += 1
        if doctor_available(con, doctor, cursor.isoformat(), "09:00") or doctor_available(con, doctor, cursor.isoformat(), "15:00"):
            booked = con.execute(
                "SELECT COUNT(*) FROM surgeries WHERE surgery_date=? AND status IN ('confirmed','completed')",
                (cursor.isoformat(),),
            ).fetchone()[0]
            beds = con.execute("SELECT available_beds FROM surgery_capacity WHERE id=1").fetchone()[0]
            if booked < min(capacity,beds):
                times=[slot for slot in ("09:00","15:00") if doctor_available(con, doctor, cursor.isoformat(), slot)]
                candidates.append({"date": cursor.isoformat(), "booked": int(booked), "capacity": capacity,
                                   "available_beds": int(beds), "effective_capacity": min(capacity,int(beds)), "available_times": times})
        cursor += timedelta(days=1)
    return candidates


def _local_suggestion(case, analysis, con, doctor: str) -> dict:
    tier = case["approved_tier"] or "Pending"
    # Tier numbers do not define medically validated waiting periods. Present
    # working-day candidates; the clinician and clinical evidence govern timing.
    delay = 1
    earliest=clinical_context(case)["doctor_earliest_date"]
    if earliest:
        delay=max(delay,(date.fromisoformat(earliest)-date.today()).days)
    candidates = _candidate_dates(con, delay, doctor)
    if not candidates:
        return {"provider":"local_capacity_rules","suggested_date":None,"reason":"No available theatre, bed and doctor combination was found in the planning window.","candidates":[],"advisory_only":True,"external_data_sent":False}
    selected = candidates[0]
    confidence = (analysis or {}).get("confidence")
    score_note = f"The research model score is {float(confidence)*100:.1f}% and is context only." if confidence is not None else "No research model score is available for this case yet."
    reason = (
        f"Provisional available working day for doctor review ({tier.lower()}); available theatre capacity "
        f"({selected['booked']} of {selected['capacity']} slots currently used). "
        f"{score_note} The doctor must select the final date after clinical review."
    )
    return {"provider": "local_capacity_rules", "suggested_date": selected["date"], "reason": reason, "candidates": candidates,
            "planning_interval_days": delay,
            "advisory_only": True, "external_data_sent": False}


def _suggest_with_settings(case, analysis, con, doctor: str, settings: dict) -> dict:
    local = _local_suggestion(case, analysis, con, doctor)
    if not local["candidates"]: return local
    local["provider_label"]="Available-date suggestion"
    local["requested_provider"]=settings["provider"]
    if not settings["enabled"]:
        local["integration_status"] = f"{settings['label']} is not enabled; local availability rules used."
        return local
    api_key = settings["api_key"]
    base_url = settings["base_url"]
    if not api_key or not base_url:
        local["integration_status"] = settings.get("error") or f"{settings['label']} credentials or endpoint are missing; local availability rules used."
        return local
    safe_context = {
        "age_band": f"{(int(case['age']) // 10) * 10}s",
        "doctor_approved_tier": case["approved_tier"] or "pending",
        "waiting_days": max(0, (date.today() - date.fromisoformat(case["waiting_since"][:10])).days),
        "research_model_score_percent": round(float(analysis["confidence"])*100,1) if analysis and analysis.get("confidence") is not None else None,
        "available_dates": local["candidates"],
        "clinical_evidence":clinical_context(case),
        "eye_findings":(analysis or {}).get("eye_findings",[]),
    }
    prompt = (
        "Choose exactly one date from available_dates for an advisory eye-surgery planning suggestion. "
        "Consider the doctor's reported symptoms AND clinical notes through clinical_evidence: functional impact, progression, "
        "ocular/systemic comorbidities, patient preference and missing preoperative information. Respect the doctor-approved tier. "
        "The image findings and scores are research signals, not clinical confirmation. Dates already satisfy doctor/capacity checks. "
        "Return strict JSON: suggested_date, reason, date_reason_points (2-4 strings explaining how the supplied clinical evidence "
        "affects this provisional timing), clinical_considerations (2-5 concise medical review points specific to the evidence), "
        "and missing_information (strings). Refer to the source fields by name. If symptoms or notes are absent, say so; do not invent them. "
        "If no clinically supportable provisional date can be suggested, return suggested_date:null and planning_status:'needs_clinical_assessment'. "
        "Flag needed clinical assessment, but do not infer medical clearance, a confirmed diagnosis, an optimal waiting period or surgery indication. "
        "Do not prescribe drugs, doses or medicine changes. Do not override the doctor or patient consent. "
        "Use NICE cataract principles: vision/quality-of-life impact and patient preference, not visual acuity or model score alone; "
        "preoperative biometry and individual risk assessment require a clinician. A proposed date is always conditional on that review. Context: "
        + json.dumps(safe_context)
    )
    request_body = {"model": settings["model"], "messages": [
        {"role": "system", "content": "You assist an ophthalmologist with provisional scheduling and clinical review considerations. Use only the supplied structured clinical evidence. No diagnosis, treatment orders, surgical clearance or autonomous clinical priority."},
        {"role": "user", "content": prompt},
    ], "temperature": 0.1, "max_tokens": 1200}
    if settings["provider"]=="openrouter":
        request_body["response_format"]={"type":"json_object"}
        request_body["reasoning"]={"enabled":False}
        if settings["model"].endswith(":free"):
            request_body["provider"]={"max_price":{"prompt":0,"completion":0}}
    body = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        local["external_data_sent"]=True
        with urllib.request.urlopen(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("error"): raise ValueError("Provider returned an error")
        content = payload["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        parsed = json.loads(content)
        allowed = {item["date"] for item in local["candidates"]}
        deferred=parsed.get("suggested_date") is None and parsed.get("planning_status")=="needs_clinical_assessment"
        if (parsed.get("suggested_date") not in allowed and not deferred) or not isinstance(parsed.get("reason"),str) or not parsed["reason"].strip():
            raise ValueError("Provider returned an invalid scheduling response")
        if not _review_strings([parsed["reason"]]): raise ValueError("Provider returned inappropriate clinical certainty")
        local.update({"provider": settings["provider"]+"_api", "provider_label":settings["label"]+" scheduling suggestion",
                      "model":settings["model"],"suggested_date": parsed["suggested_date"], "reason": str(parsed["reason"])[:800],
                      "external_data_sent": True, "integration_status": f"Connected to {settings['label']}. Advisory suggestion only; doctor confirmation required."})
        local["ai_date_reason_points"]=_review_strings(parsed.get("date_reason_points"))
        local["ai_clinical_considerations"]=_review_strings(parsed.get("clinical_considerations"))
        local["ai_missing_information"]=_review_strings(parsed.get("missing_information"))
        local["planning_status"]="needs_clinical_assessment" if deferred else "provisional"
    except urllib.error.HTTPError as exc:
        if exc.code in {401,403}:
            detail="The API key was rejected or the account lacks model access."
        elif exc.code==429:
            detail="The provider's request limit was reached."
            try:
                error=json.loads(exc.read(64*1024).decode("utf-8")).get("error",{})
                raw=str(error.get("metadata",{}).get("raw","")).lower()
                if "upstream" in raw and ("rate-limit" in raw or "rate limit" in raw):
                    detail="The model provider is temporarily limiting requests to its free endpoint. Try again later."
            except (ValueError,AttributeError):
                pass
        elif exc.code==402:
            detail="The provider reports an account credit or budget restriction."
        else:
            detail=f"The provider returned HTTP {exc.code}."
        local["integration_status"]=f"{settings['label']} unavailable. {detail} Local availability rules used."
        local["connection_error"]=f"http_{exc.code}"
    except Exception as exc:
        local["integration_status"] = f"{settings['label']} did not return a valid suggestion; local availability rules used ({type(exc).__name__})."
        local["connection_error"]=type(exc).__name__
    return local


def _choose_surgery_date(case, analysis, con, doctor: str) -> dict:
    settings=advisory_settings()
    result=_suggest_with_settings(case,analysis,con,doctor,settings)
    result["primary_model"]=settings["model"]
    result["fallback_used"]=False
    result["attempted_models"]=[settings["model"]] if result.get("external_data_sent") else []
    if result.get("provider")!="local_capacity_rules" or not result.get("connection_error") or settings["provider"]!="openrouter":
        return result
    if result["connection_error"] in {"http_401","http_402","http_403"}:
        return result
    for fallback in settings.get("fallback_models",[]):
        if not fallback.endswith(":free") or fallback==settings["model"]:
            continue
        backup_settings={**settings,"model":fallback,"label":model_label(fallback)}
        backup=_suggest_with_settings(case,analysis,con,doctor,backup_settings)
        attempted=result["attempted_models"]+([fallback] if backup.get("external_data_sent") else [])
        backup.update({"primary_model":settings["model"],"fallback_used":backup.get("provider")=="openrouter_api",
            "primary_connection_error":result["connection_error"],"attempted_models":attempted})
        if backup.get("provider")=="openrouter_api":
            backup["integration_status"]=(
                f"{settings['label']} is temporarily unavailable. {backup_settings['label']} provided this explanation. "
                f"{settings['label']} remains the primary choice; doctor confirmation is required."
            )
            return backup
        backup["integration_status"]=f"Both configured AI models are unavailable. Local availability rules used. {backup['integration_status']}"
        result=backup
    return result


def suggest_surgery_date(case, analysis, con, doctor: str) -> dict:
    medical=clinical_review(case)
    if medical["surgery_hold"]:
        reason="Acute warning symptoms require prompt ophthalmology review before elective date planning." if medical["urgent_review"] else "The recorded patient preference requires discussion before proposing a surgery date."
        return {"provider":"clinical_review_rules","provider_label":"Clinical review required","suggested_date":None,
                "reason":reason,"reason_points":[reason,"The doctor must assess the original symptoms and notes; no surgery date or booking has been assigned."],
                "clinical_review":medical,"clinical_hold":True,"advisory_only":True,"external_data_sent":False,"fallback_used":False,"attempted_models":[]}
    result = _choose_surgery_date(case, analysis, con, doctor)
    selected = next((item for item in result.get("candidates", []) if item["date"] == result.get("suggested_date")), None)
    points = []
    if selected:
        tier = case["approved_tier"] or "Pending review"
        points.extend(result.get("ai_date_reason_points",[]))
        points.append(f"Priority: {tier}. A workflow tier is not a medical deadline; the examination, reported symptoms, clinical notes and patient preference determine appropriate timing.")
        waiting = max(0, (date.today()-date.fromisoformat(case["waiting_since"][:10])).days)
        points.append(f"Waiting time: this patient has been on the list for {waiting} days. Review any change in symptoms before confirming.")
        times = selected.get("available_times", [])
        result["suggested_time"] = times[0] if times else None
        points.append("Doctor availability: the assigned doctor's working schedule and recorded leave were checked." + (" Available check times: " + ", ".join(times) + "." if times else ""))
        booked, capacity = selected["booked"], selected["capacity"]
        limit = selected.get("effective_capacity", capacity)
        points.append(f"Theatre capacity: {booked} of {capacity} daily surgery slots are booked; {max(0,limit-booked)} place(s) remain within the current surgery and bed limit.")
        if "available_beds" in selected:
            points.append(f"Bed availability: the hospital currently reports {selected['available_beds']} available beds. This is a current capacity figure, not a guaranteed bed reservation for that date.")
        earliest = result["candidates"][0]["date"]
        points.append("Date choice: this is the earliest available day found after the planning interval." if selected["date"] == earliest else f"Date choice: the assistant selected an available candidate; an earlier candidate also exists on {earliest}.")
        points.append("Before booking: confirm the patient's availability, pre-operative assessment, and clinical suitability. Image model confidence does not establish fitness for surgery; no booking has been made by this suggestion.")
    else:
        points.append("Additional clinical assessment is needed before proposing a date." if result.get("planning_status")=="needs_clinical_assessment" else "No date met the current doctor, theatre and bed checks. Review capacity or select a date manually after clinical review.")
    result["reason_points"] = points
    if result.get("ai_clinical_considerations"):
        medical["advice"]=result["ai_clinical_considerations"]+medical["advice"]
        medical["provider_label"]=result.get("provider_label", "AI review")+" · with guideline-informed checks"
    medical["missing_information"]=list(dict.fromkeys(result.get("ai_missing_information",[])+medical["missing_information"]))
    result["clinical_review"]=medical
    result["clinical_hold"]=False
    return result


def _review_strings(value):
    import re
    if not isinstance(value,list): return []
    unsafe=re.compile(r"\b(?:medically cleared|fit for surgery|clinically optimal|guaranteed|no surgical risks|(?:stop|start|increase|decrease) (?:taking |the |your )?(?:medication|insulin|warfarin|aspirin)|\d+\s*mg\b)",re.I)
    return [item.strip()[:500] for item in value[:6] if isinstance(item,str) and item.strip() and not unsafe.search(item)]
