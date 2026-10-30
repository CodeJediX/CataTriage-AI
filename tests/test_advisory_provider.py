from __future__ import annotations

import copy
import io
import json
import urllib.error

import pytest

from deployment.demo_app import advisory, settings


@pytest.fixture()
def provider(monkeypatch):
    local={"provider":"local_capacity_rules","suggested_date":"2026-11-02","reason":"Local capacity selection",
        "candidates":[{"date":"2026-11-02","booked":0,"capacity":6},{"date":"2026-11-03","booked":1,"capacity":6}],
        "advisory_only":True,"external_data_sent":False}
    monkeypatch.setattr(advisory,"_local_suggestion",lambda *args:copy.deepcopy(local))
    config={"enabled":True,"provider":"openrouter","label":"Gemma via OpenRouter","api_key":"test-key-only",
        "base_url":"https://openrouter.ai/api/v1","model":"google/gemma-4-31b-it:free","error":None}
    monkeypatch.setattr(advisory,"advisory_settings",lambda:config)
    return config


CASE={"age":67,"approved_tier":"Tier 2","waiting_since":"2026-10-01","patient_alias":"Private Patient",
    "phone":"PRIVATE_PHONE","address":"PRIVATE_ADDRESS","notes":"PRIVATE_NARRATIVE","case_id":"PRIVATE_IDENTIFIER"}


def test_openrouter_success_uses_gemma_and_excludes_identifiers(provider,monkeypatch):
    requests=[]
    def reply(request,timeout):
        requests.append(request)
        return io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps({
            "suggested_date":"2026-11-03","reason":"An available day for the doctor's review."})}}]}).encode())
    monkeypatch.setattr(advisory.urllib.request,"urlopen",reply)
    result=advisory.suggest_surgery_date(CASE,{"confidence":0.72},None,"dr.maya")
    assert result["provider"]=="openrouter_api"
    assert result["suggested_date"]=="2026-11-03" and result["advisory_only"] is True
    request=requests[0]
    assert request.full_url=="https://openrouter.ai/api/v1/chat/completions"
    payload=json.loads(request.data)
    assert payload["model"]=="google/gemma-4-31b-it:free"
    assert payload["response_format"]=={"type":"json_object"}
    serialized=json.dumps(payload)
    assert all(secret not in serialized for secret in ["Private Patient","PRIVATE_PHONE","PRIVATE_ADDRESS","PRIVATE_NARRATIVE","PRIVATE_IDENTIFIER"])
    assert "test-key-only" not in json.dumps(result)


@pytest.mark.parametrize("code",[401,402,403,429,503])
def test_provider_errors_keep_local_plan_without_secrets(provider,monkeypatch,code):
    def fail(*args,**kwargs):
        raise urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions",code,"private upstream content",{},None)
    monkeypatch.setattr(advisory.urllib.request,"urlopen",fail)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert result["provider"]=="local_capacity_rules"
    assert result["connection_error"]==f"http_{code}"
    assert "private upstream content" not in json.dumps(result)


def test_out_of_candidate_date_is_rejected(provider,monkeypatch):
    def reply(*args,**kwargs):
        return io.BytesIO(json.dumps({"choices":[{"message":{"content":'{"suggested_date":"2030-01-01","reason":"Override"}'}}]}).encode())
    monkeypatch.setattr(advisory.urllib.request,"urlopen",reply)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert result["provider"]=="local_capacity_rules"
    assert result["suggested_date"]=="2026-11-02"


def test_disabled_provider_makes_no_external_call(provider,monkeypatch):
    provider["enabled"]=False
    def unexpected(*args,**kwargs): pytest.fail("Disabled provider attempted a request")
    monkeypatch.setattr(advisory.urllib.request,"urlopen",unexpected)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert not result["external_data_sent"]
    assert "Gemma" in result["integration_status"]


def test_plain_key_file_loads_without_copying_key(tmp_path,monkeypatch):
    key_file=tmp_path/"api-key.txt"
    key_file.write_text("sk-or-TEST-ONLY-NOT-A-CREDENTIAL",encoding="utf-8")
    monkeypatch.setenv("AI_PROVIDER","openrouter")
    monkeypatch.setenv("AI_ENABLE","true")
    monkeypatch.delenv("OPENROUTER_API_KEY",raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY_FILE",str(key_file))
    config=settings.advisory_settings()
    assert config["enabled"] and config["api_key"]=="sk-or-TEST-ONLY-NOT-A-CREDENTIAL"
    assert config["base_url"]=="https://openrouter.ai/api/v1"


def test_upstream_rate_limit_is_identified_without_exposing_raw_response(provider,monkeypatch):
    def fail(*args,**kwargs):
        body=io.BytesIO(json.dumps({"error":{"metadata":{"raw":"Model is temporarily rate-limited upstream. PRIVATE_DETAILS"}}}).encode())
        raise urllib.error.HTTPError("https://openrouter.ai/api/v1/chat/completions",429,"error",{},body)
    monkeypatch.setattr(advisory.urllib.request,"urlopen",fail)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert "temporarily limiting" in result["integration_status"]
    assert "PRIVATE_DETAILS" not in json.dumps(result)


BACKUP="nvidia/nemotron-3.5-super-vl:free"


def json_reply():
    return io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps({
        "suggested_date":"2026-11-03","reason":"Available capacity on the selected working day."})}}]}).encode())


def test_gemma_is_always_tried_before_free_backup(provider,monkeypatch):
    provider["fallback_models"]=[BACKUP]
    models=[]
    def reply(request,timeout):
        payload=json.loads(request.data)
        assert payload["provider"]["max_price"]=={"prompt":0,"completion":0}
        models.append(payload["model"])
        if len(models)==1:
            raise urllib.error.HTTPError(request.full_url,429,"unavailable",{},None)
        return json_reply()
    monkeypatch.setattr(advisory.urllib.request,"urlopen",reply)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert models==["google/gemma-4-31b-it:free",BACKUP]
    assert result["model"]==BACKUP and result["fallback_used"]
    assert result["primary_model"]=="google/gemma-4-31b-it:free"
    assert "NVIDIA" in result["provider_label"]
    assert "remains the primary" in result["integration_status"]


def test_gemma_recovery_skips_backup(provider,monkeypatch):
    provider["fallback_models"]=[BACKUP]
    models=[]
    def reply(request,timeout):
        models.append(json.loads(request.data)["model"])
        return json_reply()
    monkeypatch.setattr(advisory.urllib.request,"urlopen",reply)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert models==["google/gemma-4-31b-it:free"]
    assert result["model"]=="google/gemma-4-31b-it:free" and not result["fallback_used"]


def test_authentication_error_does_not_retry_backup(provider,monkeypatch):
    provider["fallback_models"]=[BACKUP]
    requests=[]
    def fail(request,timeout):
        requests.append(request)
        raise urllib.error.HTTPError(request.full_url,401,"error",{},None)
    monkeypatch.setattr(advisory.urllib.request,"urlopen",fail)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert len(requests)==1 and result["provider"]=="local_capacity_rules"


def test_paid_backup_is_ignored(provider,monkeypatch):
    provider["fallback_models"]=["paid/model"]
    requests=[]
    def fail(request,timeout):
        requests.append(request)
        raise urllib.error.HTTPError(request.full_url,429,"error",{},None)
    monkeypatch.setattr(advisory.urllib.request,"urlopen",fail)
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert len(requests)==1 and result["provider"]=="local_capacity_rules"


def test_clinical_inputs_influence_both_explanations_without_sending_raw_notes(provider,monkeypatch):
    requests=[]
    def reply(request,timeout):
        requests.append(json.loads(request.data))
        content={"suggested_date":"2026-11-03","reason":"Provisional timing after clinical review of the reported functional impact.",
            "date_reason_points":["Reported symptoms include difficulty reading; discuss functional impact when confirming timing."],
            "clinical_considerations":["Clinical notes mention diabetes; review retinal findings before planning."],
            "missing_information":["Confirm the preoperative examination."]}
        return io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps(content)}}]}).encode())
    monkeypatch.setattr(advisory.urllib.request,"urlopen",reply)
    result=advisory.suggest_surgery_date({**CASE,"symptoms":"PRIVATE_PERSON difficulty reading for 3 months.","notes":"PRIVATE_NARRATIVE diabetes."},None,None,"dr.maya")
    context=json.loads(requests[0]["messages"][1]["content"].split("Context: ")[1])
    assert "reading_impact" in context["clinical_evidence"]["reported_features"]
    assert "diabetes" in context["clinical_evidence"]["reported_features"]
    assert "PRIVATE" not in json.dumps(context)
    assert any("functional impact" in point for point in result["reason_points"])
    assert "diabetes" in result["clinical_review"]["advice"][0]


def test_urgent_context_pauses_date_without_external_call(provider,monkeypatch):
    monkeypatch.setattr(advisory.urllib.request,"urlopen",lambda *a,**kw:pytest.fail("Acute warning bypassed"))
    result=advisory.suggest_surgery_date({**CASE,"symptoms":"Sudden loss of vision."},None,None,"dr.maya")
    assert result["suggested_date"] is None and result["clinical_hold"]
    assert result["external_data_sent"] is False


def test_provider_can_defer_date_for_missing_clinical_assessment(provider,monkeypatch):
    content={"suggested_date":None,"planning_status":"needs_clinical_assessment","reason":"Clinical examination is required before a provisional date can be supported."}
    monkeypatch.setattr(advisory.urllib.request,"urlopen",lambda *a,**kw:io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps(content)}}]}).encode()))
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert result["provider"]=="openrouter_api" and result["suggested_date"] is None
    assert result["planning_status"]=="needs_clinical_assessment"


def test_provider_cannot_claim_surgical_clearance(provider,monkeypatch):
    content={"suggested_date":"2026-11-03","reason":"The patient is medically cleared and fit for surgery."}
    monkeypatch.setattr(advisory.urllib.request,"urlopen",lambda *a,**kw:io.BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps(content)}}]}).encode()))
    result=advisory.suggest_surgery_date(CASE,None,None,"dr.maya")
    assert result["provider"]=="local_capacity_rules"
    assert "medically cleared" not in result["reason"]
