from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image

from deployment.demo_app.database import DB_PATH, initialize_database
from deployment.demo_app.main import app
from deployment.demo_app.role_databases import DOCTOR_DB_PATH, TECHNICIAN_DB_PATH
from agents.workflow import run_workflow
from deployment.demo_app.model_provider import (
    CHECKPOINT,
    EXPECTED_CLASSES,
    ImageValidationError,
    RetinaModelProvider,
    validate_image_bytes,
)
from deployment.demo_app.synthetic_models import FUSION_CHECKPOINT, GRADE_CHECKPOINT, synthetic_provider

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from deployment.demo_app import database, role_databases, main, hospital, google_auth
    isolated_db = tmp_path / "hospital.sqlite3"
    doctor_db = tmp_path / "doctors.sqlite3"
    tech_db = tmp_path / "technicians.sqlite3"
    original_connection = database.connection
    isolated_connection = lambda db_path=None: original_connection(db_path or isolated_db)
    for module in (main,hospital,google_auth,database):
        monkeypatch.setattr(module,"connection",isolated_connection)
    for module in (main,hospital,role_databases):
        monkeypatch.setattr(module,"DOCTOR_DB_PATH",doctor_db)
    for module in (main,role_databases):
        monkeypatch.setattr(module,"TECHNICIAN_DB_PATH",tech_db)
    for name,value in (("DB_PATH",isolated_db),("DOCTOR_DB_PATH",doctor_db),("TECHNICIAN_DB_PATH",tech_db)):
        monkeypatch.setattr(sys.modules[__name__],name,value)
    monkeypatch.setattr(main,"initialize_database",lambda: initialize_database(isolated_db))
    monkeypatch.setattr(main,"reset_database",lambda: initialize_database(isolated_db,force_reset=True))
    uploads=tmp_path/"uploads"; uploads.mkdir()
    photos=tmp_path/"profiles"; photos.mkdir()
    monkeypatch.setattr(main,"UPLOAD_DIR",uploads)
    monkeypatch.setattr(main,"APP_DIR",tmp_path)
    monkeypatch.setattr(main,"DOCTOR_IMAGE_DIR",photos)
    monkeypatch.setattr(main,"SECRET_PATH",tmp_path/"session_secret")
    monkeypatch.delenv("QWEN_ENABLE",raising=False)
    for key in ("AI_ENABLE","AI_PROVIDER","OPENROUTER_API_KEY","OPENROUTER_API_KEY_FILE","OPENROUTER_MODEL","OPENROUTER_FALLBACK_MODELS"):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.delenv("WHATSAPP_ENABLE",raising=False)
    for key in ("GMAIL_APP_PASSWORD","GMAIL_APP_PASSWORD_FILE","GMAIL_OAUTH_JSON","GMAIL_OAUTH_JSON_FILE","FIREBASE_WEB_API_KEY","FIREBASE_MAIL_CONFIG_FILE"):
        monkeypatch.delenv(key,raising=False)
    initialize_database(isolated_db,force_reset=True)
    role_databases.initialize_role_databases(force_reset=True)
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username="dr.maya", password="demo-doctor"):
    response = client.get("/login")
    assert response.status_code == 200
    csrf = client.cookies.get("catatriage_csrf")
    result = client.post("/login", data={"username":username,"password":password,"csrf":csrf,"next_path":"/"})
    assert result.status_code == 200
    return csrf


def prepare_month_booking(client,day,case_id='DEMO-0001'):
    csrf=login(client)
    assert client.post('/doctor/review/'+case_id,data={'csrf':csrf,'decision':'approve','tier':'Tier 2','reason':'Independent clinical review for month planning.'}).status_code==200
    record=client.get('/api/mobile/patients/'+case_id).json()
    assert client.post('/api/mobile/patients/'+case_id+'/month',data={'csrf':csrf,'approved_month':day[:7],'reason':'The doctor assessed this planning month as appropriate.','attestation':'yes','evidence_hash':record['evidence_hash'],'functional_impact':'moderate','progression':'stable','planning_preference':'balanced'}).status_code==200
    return login(client,'admin.nila','demo-admin')


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (80, 120, 90)).save(buf, "PNG")
    return buf.getvalue()


def test_split_manifests_are_disjoint_and_expected_sizes():
    frames = {name: pd.read_csv(ROOT / "data_splits" / "retina_four_class" / f"{name}.csv") for name in ["train","validation","test"]}
    assert {k:len(v) for k,v in frames.items()} == {"train":420,"validation":90,"test":91}
    hashes = {k:set(v.sha256) for k,v in frames.items()}
    assert not hashes["train"] & hashes["validation"]
    assert not hashes["train"] & hashes["test"]
    assert not hashes["validation"] & hashes["test"]
    assert set().union(*hashes.values()) == set(pd.concat(frames.values()).sha256)


def test_checkpoint_metadata_and_state_dict_load():
    saved = torch.load(CHECKPOINT, map_location="cpu", weights_only=False)
    assert saved["class_names"] == EXPECTED_CLASSES
    assert saved["image_size"] == 224
    assert saved["epoch"] == 28
    provider = RetinaModelProvider()
    provider.load()
    assert provider.loaded


def test_known_local_image_inference_smoke_only():
    import os
    image_path = Path(pd.read_csv(ROOT / "data_splits" / "retina_four_class" / "test.csv").iloc[0].full_path)
    if os.getenv('CATATRIAGE_TEST_NO_RAW_DATA')=='1' or not image_path.is_file():
        pytest.skip('Optional raw-image smoke check: source datasets are not redistributed. Checkpoint and API tests still run.')
    provider = RetinaModelProvider()
    result = provider.analyze(image_path.read_bytes(), "fundus")
    assert result["status"] == "ok"
    assert list(result["probabilities"]) == EXPECTED_CLASSES
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-3
    assert result["urgency"] is None


def test_corrupt_and_wrong_modality_handling():
    with pytest.raises(ImageValidationError):
        validate_image_bytes(b"not-an-image")
    result = RetinaModelProvider().analyze(png_bytes(), "slit_lamp")
    assert result["status"] == "not_available"
    assert result["urgency"] is None
    assert "slit-lamp" in result["reason"]


def test_demo_seed_and_routes_render(client: TestClient):
    login(client)
    for path in ["/", "/cases", "/cases/new", "/calendar", "/doctor/leave", "/audit", "/about", "/cases/DEMO-0001", "/health"]:
        response = client.get(path)
        assert response.status_code == 200, path
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 16
        assert con.execute("SELECT COUNT(*) FROM cases WHERE case_id NOT LIKE 'DEMO-%'").fetchone()[0] == 0


def test_doctor_only_approval_and_admin_cannot_edit_tier(client: TestClient):
    csrf = login(client, "admin.nila", "demo-admin")
    assert client.get("/doctor/review/DEMO-0004").status_code == 403
    assert client.post("/doctor/review/DEMO-0004", data={"decision":"approve","tier":"Tier 1","reason":"Admin attempt","csrf":csrf}).status_code == 403
    client.post("/logout", data={"csrf":csrf})
    csrf = login(client)
    response = client.post("/doctor/review/DEMO-0007", data={"decision":"approve","tier":"Tier 2","reason":"Manual fictional clinician priority.","csrf":csrf}, follow_redirects=False)
    assert response.status_code == 303
    with sqlite3.connect(DB_PATH) as con:
        tier, approver = con.execute("SELECT approved_tier,approved_by FROM cases WHERE case_id='DEMO-0007'").fetchone()
        assert (tier,approver) == ("Tier 2","dr.maya")


def test_admin_schedule_requires_approved_tier(client: TestClient):
    csrf = login(client, "admin.nila", "demo-admin")
    response = client.post("/queue/DEMO-0007/schedule", data={"scheduled_date":"2026-11-12","slot":"10:00","csrf":csrf})
    assert response.status_code == 403
    response = client.post("/queue/DEMO-0001/schedule", data={"scheduled_date":"2026-11-12","slot":"10:00","csrf":csrf}, follow_redirects=False)
    assert response.status_code == 303
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT approved_tier FROM cases WHERE case_id='DEMO-0001'").fetchone()[0] == "Tier 1"


def test_export_and_reset(client: TestClient):
    csrf = login(client, "admin.nila", "demo-admin")
    export = client.get("/export/queue.csv")
    assert export.status_code == 200
    assert "SIMULATED DEMO DATA" in export.text
    response = client.post("/admin/reset", data={"confirmation":"RESET DEMO","csrf":csrf}, follow_redirects=False)
    assert response.status_code == 303
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 16


def test_api_never_returns_urgency(client: TestClient):
    csrf = login(client)
    response = client.post("/api/analyze", data={"modality":"slit_lamp","csrf":csrf}, files={"image":("sample.png",png_bytes(),"image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_id"] == "clinical_fusion_catscreen_real_v2"
    assert body["urgency"] is None


def test_invalid_upload_returns_clear_error(client: TestClient):
    csrf = login(client)
    response = client.post("/api/analyze", data={"modality":"fundus","csrf":csrf}, files={"image":("bad.png",b"bad","image/png")})
    assert response.status_code == 400
    assert "valid" in response.json()["error"].lower()


def test_slit_lamp_intake_persists_real_research_result(client: TestClient):
    csrf = login(client)
    response = client.post(
        "/intake",
        data={"case_id":"DEMO-0001","modality":"slit_lamp","symptoms":"Synthetic QA symptoms","notes":"Test fixture","csrf":csrf},
        files={"left_images":("sample.png",png_bytes(),"image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with sqlite3.connect(DB_PATH) as con:
        status, payload, image_path = con.execute("SELECT analysis_status,analysis_json,image_path FROM cases WHERE case_id='DEMO-0001'").fetchone()
    result = json.loads(payload)
    assert status == "ok"
    assert result["model_id"] == "clinical_fusion_catscreen_real_v2"
    assert result["urgency"] is None
    assert image_path.endswith(".png")


def test_three_role_portals_and_role_isolation(client: TestClient):
    assert client.get("/login/doctor").status_code == 200
    assert client.get("/login/admin").status_code == 200
    assert client.get("/login/technician").status_code == 200
    csrf = login(client, "tech.alex", "demo-tech")
    assert client.get("/support").status_code == 200
    assert client.get("/doctor").status_code == 403
    assert client.get("/queue").status_code == 403
    assert DOCTOR_DB_PATH.exists() and TECHNICIAN_DB_PATH.exists() and DB_PATH.exists()


def test_doctor_workspace_search_and_local_message(client: TestClient):
    csrf = login(client)
    page = client.get("/doctor?q=Nethmi&scope=mine")
    assert page.status_code == 200
    assert "Nethmi Perera" in page.text
    sent = client.post("/doctor/messages", data={"case_id":"DEMO-0001","body":"Synthetic follow-up message","csrf":csrf}, follow_redirects=False)
    assert sent.status_code == 303
    with sqlite3.connect(DOCTOR_DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM messages WHERE body='Synthetic follow-up message'").fetchone()[0] == 1


def test_four_agent_workflow_never_sets_priority():
    _, meta = validate_image_bytes(png_bytes())
    result = run_workflow(png_bytes(), "slit_lamp", meta, RetinaModelProvider().analyze)
    assert [s["agent"].split(" — ")[0] for s in result["agent_workflow"]] == ["Agent 1", "Agent 2", "Agent 3", "Agent 4"]
    assert result["clinical_priority"] is None
    assert result["requires_clinician_review"] is True


def test_synthetic_gpu_model_artifacts_and_simulation_route(client: TestClient):
    for path in (GRADE_CHECKPOINT, FUSION_CHECKPOINT):
        saved = torch.load(path, map_location="cpu", weights_only=False)
        assert saved["synthetic_only"] is True
        assert saved["class_names"][0].startswith("Grade 0")
    csrf = login(client,"admin.nila","demo-admin")
    page = client.get("/simulation?scenario=7")
    assert page.status_code == 200
    assert "These are not human results" in page.text
    assert "SIMULATED" in page.text
    assert client.get("/simulation/image/7.png").headers["content-type"] == "image/png"
    result = synthetic_provider.predict(9_000_000 + 7 * 7919, 3)
    assert result["synthetic_ground_truth"] == 3
    assert result["grade_prediction"] in range(4)
    assert result["fusion_prediction"] in range(4)


def future_workday(offset=14):
    day=date.today()+timedelta(days=offset)
    while day.weekday()>4: day+=timedelta(days=1)
    return day.isoformat()


def test_hospital_registration_hours_profile_and_role_boundary(client,monkeypatch):
    from deployment.demo_app import communications
    monkeypatch.setattr(communications,"temporary_password",lambda:"test-doctor-123")
    csrf=login(client,"admin.nila","demo-admin")
    assert client.get("/admin").status_code==200
    result=client.post("/admin/doctors",data={"username":"dr.anjali","display_name":"Dr Anjali Senanayake","mobile":"+94771234567",
        "work_start":"08:00","work_end":"17:00","working_days":["Mon","Tue","Wed","Thu","Fri"],"email":"anjali@example.invalid","csrf":csrf},
        files={"profile_image":("doctor.png",png_bytes(),"image/png")},follow_redirects=False)
    assert result.status_code==303
    assert client.get("/doctor-profile/dr.anjali").status_code==200
    result=client.post("/admin/patients",data={"full_name":"Sanduni Perera","address":"12 Lake Road, Kandy","mobile":"+94771111222",
        "doctor_username":"dr.anjali","age":"55","csrf":csrf},follow_redirects=False)
    assert result.status_code==303
    client.post("/logout",data={"csrf":csrf})
    login(client,"dr.anjali","test-doctor-123")
    client.post("/login/doctor/password",data={"username":"dr.anjali","current_password":"test-doctor-123","new_password":"test-doctor-new-123","confirmation":"test-doctor-new-123","csrf":csrf})
    login(client,"dr.anjali","test-doctor-new-123")
    page=client.get("/doctor")
    assert "Sanduni Perera" in page.text and "/doctor-profile/dr.anjali" in page.text
    assert client.get("/admin").status_code==403
    assert client.get("/cases/DEMO-0001").status_code==403


def test_leave_confirmation_and_admin_rescheduling(client):
    day=future_workday()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO appointments(case_id,scheduled_date,slot,service,created_by,created_at) VALUES(?,?,?,?,?,?)",
            ("DEMO-0001",day,"09:00","Consultation","admin.nila","test"))
    csrf=login(client)
    request={"leave_date":day,"leave_type":"full_day","csrf":csrf}
    check=client.post("/doctor/leave",data=request)
    assert check.status_code==200 and "Confirm leave request" in check.text
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]==0
    sent=client.post("/doctor/leave",data={**request,"confirmed":"yes"},follow_redirects=False)
    assert sent.status_code==303
    with sqlite3.connect(DB_PATH) as con:
        leave_id=con.execute("SELECT id FROM leave_requests").fetchone()[0]
    client.post("/logout",data={"csrf":csrf})
    csrf=login(client,"admin.nila","demo-admin")
    page=client.get("/admin")
    assert "data-auto-dialog" in page.text and "Nethmi Perera" in page.text
    rejected=client.post(f"/admin/leave/{leave_id}/patient/DEMO-0001",data={"action":"reassign","doctor_username":"dr.kamal","csrf":csrf})
    assert rejected.status_code==409
    result=client.post(f"/admin/leave/{leave_id}/patient/DEMO-0001",data={"action":"reschedule","new_date":future_workday(21),"csrf":csrf},follow_redirects=False)
    assert result.status_code==303
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT scheduled_date FROM appointments WHERE case_id='DEMO-0001'").fetchone()[0]==future_workday(21)


def test_surgery_capacity_leave_and_advisory_never_autobook(client):
    csrf=login(client)
    suggestion=client.post("/doctor/review/DEMO-0001/suggestion",data={"csrf":csrf})
    assert suggestion.status_code==200 and "Suggest a surgery month" in suggestion.text
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM surgeries").fetchone()[0]==0
        con.execute("UPDATE surgery_capacity SET max_surgeries_per_day=1,available_beds=1 WHERE id=1")
    data={"surgery_date":future_workday(),"slot":"09:00","rationale":"Clinician reviewed the patient and confirmed this plan.","csrf":csrf}
    prepare_month_booking(client,future_workday())
    first=client.post("/admin/surgery/DEMO-0001/confirm",data=data,follow_redirects=False)
    assert first.status_code==303
    prepare_month_booking(client,future_workday(),"DEMO-0003")
    full=client.post("/admin/surgery/DEMO-0003/confirm",data=data)
    assert full.status_code==409 and "slot is no longer free" in full.text
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM surgeries").fetchone()[0]==1
    assert "Nethmi Perera" in client.get("/calendar?kind=surgery&month="+future_workday()[:7]).text
    login(client)
    rejected=client.post("/doctor/review/DEMO-0001",data={"decision":"reject","tier":"","reason":"Return for additional clinical review.","csrf":csrf},follow_redirects=False)
    assert rejected.status_code==303
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT status FROM surgeries WHERE case_id='DEMO-0001'").fetchone()[0]=="cancelled"


def test_intake_assignment_multi_images_and_failed_delivery_state(client):
    csrf=login(client)
    denied=client.post("/intake",data={"case_id":"DEMO-0002","modality":"slit_lamp","csrf":csrf},follow_redirects=False)
    assert denied.status_code==403
    saved=client.post("/intake",data={"case_id":"DEMO-0001","modality":"slit_lamp","csrf":csrf},
        files=[("left_images",("left.png",png_bytes(),"image/png")),("right_images",("right.png",png_bytes(),"image/png"))],follow_redirects=False)
    assert saved.status_code==303
    with sqlite3.connect(DB_PATH) as con:
        sides=con.execute("SELECT eye_side FROM case_images WHERE case_id='DEMO-0001' ORDER BY id").fetchall()
    assert sides==[("Left",),("Right",)]
    assert "Left &amp; right eye views" in client.get("/cases/DEMO-0001").text
    result=client.post("/doctor/messages",data={"case_id":"DEMO-0001","body":"Your appointment information.","channel":"whatsapp","csrf":csrf})
    assert "credentials are not configured" in result.text
    with sqlite3.connect(DOCTOR_DB_PATH) as con:
        assert con.execute("SELECT delivery_status FROM messages ORDER BY id DESC LIMIT 1").fetchone()[0]=="stored_not_sent"


def test_google_callback_rejects_invalid_state(client):
    result=client.get("/auth/google/callback?code=fake&state=forged")
    assert result.status_code==400


def test_unknown_eye_upload_keeps_unknown_label_and_own_results(client, monkeypatch):
    from deployment.demo_app import main
    contexts=[]
    def inference(data,kind,context):
        contexts.append(context.copy())
        return {"status":"ok","top_class":"cataract","confidence":0.7,"probabilities":{"cataract":0.7,"normal":0.3},"device":"test"}
    monkeypatch.setattr(main.real_provider,"analyze_fusion",inference)
    csrf=login(client)
    result=client.post("/intake",data={"case_id":"DEMO-0001","modality":"slit_lamp","csrf":csrf},
        files={"unknown_images":("unlabelled.png",png_bytes(),"image/png")},follow_redirects=False)
    assert result.status_code==303 and contexts[0]["eye_side"]=="Not recorded"
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT eye FROM cases WHERE case_id='DEMO-0001'").fetchone()[0]=="Not recorded"
        saved=con.execute("SELECT eye_side,analysis_json FROM case_images WHERE case_id='DEMO-0001'").fetchone()
        assert saved[0]=="Not recorded" and json.loads(saved[1])["observation_group"]
    page=client.get("/cases/DEMO-0001")
    assert "Cataract prediction: eye side unknown." in page.text
    assert "Left or right cannot be identified" in page.text


def test_suggestion_has_grounded_bullet_reasons_and_tier_guide(client):
    csrf=login(client)
    client.post('/doctor/review/DEMO-0001',data={'csrf':csrf,'decision':'approve','tier':'Tier 3','reason':'Independent clinical assessment.'})
    page=client.post('/doctor/review/DEMO-0001/suggestion',data={'csrf':csrf,'functional_impact':'mild','progression':'stable','planning_preference':'later','symptoms':'Gradual blurred vision','notes':'Stable routine elective planning.'})
    assert page.status_code==200
    for text in ('Tier 1 · Higher priority','Tier 2 · Intermediate priority','Tier 3 · Routine priority','schedule-reasons','Doctor-recorded functional impact','Doctor working days','not a medically validated safe waiting time','Image model confidence was not used'):
        assert text in page.text


def test_new_round_does_not_show_old_unknown_image_as_current(client,monkeypatch):
    from deployment.demo_app import main
    import re
    monkeypatch.setattr(main.real_provider,"analyze_fusion",lambda *a,**kw:{"status":"ok","top_class":"normal","confidence":0.6,"probabilities":{"normal":0.6,"cataract":0.4},"device":"test"})
    csrf=login(client)
    data={"case_id":"DEMO-0001","modality":"slit_lamp","csrf":csrf}
    assert client.post("/intake",data=data,files={"unknown_images":("old.png",png_bytes(),"image/png")}).status_code==200
    result=client.post("/intake",data=data,files=[("left_images",("left.png",png_bytes(),"image/png")),("right_images",("right.png",png_bytes(),"image/png"))])
    current,history=result.text.split('<details class="panel image-history">',1)
    assert re.findall(r'<img[^>]*alt="([^"]*uploaded image)"',current)==["Right eye uploaded image","Left eye uploaded image"]
    assert len(re.findall(r'<img[^>]*alt="[^"]*uploaded image"',history))==1
    empty=client.post("/intake",data=data)
    assert "No images were uploaded in this round." in empty.text
    assert "No image analysis has been run." in empty.text
    assert len(re.findall(r'<img[^>]*alt="[^"]*uploaded image"',empty.text.split('<details class="panel image-history">',1)[1]))==3
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT image_path,analysis_status FROM cases WHERE case_id='DEMO-0001'").fetchone()==(None,"not_run")


def test_planning_form_saves_clinical_inputs_and_shows_separate_review(client):
    csrf=login(client)
    symptoms="Gradual blurred vision and difficulty reading for 4 months."
    notes="Diabetes mentioned. Preoperative assessment pending."
    response=client.post("/doctor/review/DEMO-0001/suggestion",data={"csrf":csrf,"clinical_context_submitted":"1","symptoms":symptoms,"notes":notes})
    assert response.status_code==200
    for text in ("Clinical advice for doctor review","Reported symptoms: Reading affected","Clinical notes: Diabetes mentioned","Information to confirm","Provisional month suggestion"):
        assert text in response.text
    with sqlite3.connect(DB_PATH) as con:
        assert con.execute("SELECT symptoms,notes FROM cases WHERE case_id='DEMO-0001'").fetchone()==(symptoms,notes)
        assert con.execute("SELECT COUNT(*) FROM case_images").fetchone()[0]==0
        assert con.execute("SELECT COUNT(*) FROM surgeries").fetchone()[0]==0
    assert client.post("/doctor/review/DEMO-0002/suggestion",data={"csrf":csrf,"clinical_context_submitted":"1","notes":"overwrite"}).status_code==403


def test_acute_symptoms_show_hold_and_no_prefilled_date(client):
    csrf=login(client)
    response=client.post("/doctor/review/DEMO-0001/suggestion",data={"csrf":csrf,"clinical_context_submitted":"1","symptoms":"Sudden loss of vision.","notes":""})
    assert response.status_code==200
    assert "Clinical assessment required" in response.text
    assert "Elective month suggestion paused" in response.text
    assert "same-day ophthalmology" in response.text
    assert 'name="surgery_date"' not in response.text


def test_hosted_demo_hides_passwords_and_disables_reset(client, monkeypatch):
    monkeypatch.setenv("CATATRIAGE_HOSTED","true")
    page=client.get("/login/doctor")
    assert 'name="password" type="password" autocomplete="current-password" required value=""' in page.text
    assert "dr.maya / demo-doctor" not in page.text
    csrf=login(client,"admin.nila","demo-admin")
    assert client.post("/admin/reset",data={"csrf":csrf,"confirmation":"RESET DEMO"}).status_code==403


def test_hosted_seed_requires_private_passwords(monkeypatch):
    from deployment.demo_app.database import _initial_password
    monkeypatch.setenv("CATATRIAGE_HOSTED","true")
    monkeypatch.delenv("CATATRIAGE_DOCTOR_PASSWORD",raising=False)
    with pytest.raises(RuntimeError): _initial_password("doctor","demo-doctor")
    monkeypatch.setenv("CATATRIAGE_DOCTOR_PASSWORD","test-private-password-only")
    assert _initial_password("doctor","demo-doctor")=="test-private-password-only"


def test_cloud_chunk_upload_binding_and_persistent_bytes(client,monkeypatch,tmp_path):
    from deployment.demo_app import cloud_database, main, file_store
    csrf=login(client)
    with main.connection() as con:
        con.executescript("""
        CREATE TABLE file_objects(object_key TEXT PRIMARY KEY,content BLOB NOT NULL);
        CREATE TABLE pending_uploads(id TEXT PRIMARY KEY,owner_name TEXT,action_path TEXT,target_id TEXT,field_name TEXT,original_name TEXT,expected_size INTEGER,expires_at INTEGER);
        CREATE TABLE upload_chunks(upload_id TEXT REFERENCES pending_uploads(id) ON DELETE CASCADE,chunk_index INTEGER,content BLOB,PRIMARY KEY(upload_id,chunk_index));
        """)
    monkeypatch.setattr(cloud_database,"enabled",lambda:True)
    monkeypatch.setattr(cloud_database,"connection",lambda namespace="hospital":main.connection({"doctor":main.DOCTOR_DB_PATH,"technician":main.TECHNICIAN_DB_PATH}.get(namespace)))
    # SQLite locks an entire file, unlike Postgres. Use an independent file for
    # blob persistence so this unit fixture can model concurrent table writes.
    from types import SimpleNamespace
    blob_path=tmp_path/"cloud-blobs.sqlite3"
    with main.connection(blob_path) as con:
        con.execute("CREATE TABLE file_objects(object_key TEXT PRIMARY KEY,content BLOB NOT NULL)")
    monkeypatch.setattr(file_store,"cloud_database",SimpleNamespace(enabled=lambda:True,connection=lambda:main.connection(blob_path)))
    monkeypatch.setattr(file_store,"APP_DIR",main.APP_DIR)
    headers={"X-CSRF-Token":csrf}
    payload=png_bytes()
    specification={"action":"/intake","target":"DEMO-0002","field":"unknown_images","name":"test.png","size":len(payload)}
    assert client.post("/uploads/prepare",json=specification,headers=headers).status_code==403
    specification["target"]="DEMO-0001"
    assert client.post("/uploads/prepare",json=specification,headers={"X-CSRF-Token":"wrong"}).status_code==403
    result=client.post("/uploads/prepare",json=specification,headers=headers)
    identifier=result.json()["id"]
    assert client.post(f"/uploads/{identifier}/chunks/8",content=b"x",headers=headers).status_code==400
    assert client.post(f"/uploads/{identifier}/chunks/0",content=payload,headers=headers).status_code==200
    assert client.post("/intake",data={"case_id":"DEMO-0003","modality":"slit_lamp","csrf":csrf,"cloud_uploads":json.dumps([identifier])}).status_code==403
    result=client.post("/intake",data={"case_id":"DEMO-0001","modality":"slit_lamp","csrf":csrf,"cloud_uploads":json.dumps([identifier])})
    assert result.status_code==200 and "eye side unknown" in result.text
    with main.connection(blob_path) as con:
        assert bytes(con.execute("SELECT content FROM file_objects").fetchone()[0])==payload
    with main.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM pending_uploads").fetchone()[0]==0


def test_cloud_session_secret_survives_instance_changes(monkeypatch):
    from deployment.demo_app import main
    monkeypatch.setenv("CATATRIAGE_SESSION_SECRET","test-stable-session-secret-"*3)
    first=main._sign("a session from an earlier instance")
    monkeypatch.setattr(main,"SECRET_PATH",ROOT/"tmp/a-different-instance-secret")
    assert main._sign("a session from an earlier instance")==first
    monkeypatch.setenv("CATATRIAGE_SESSION_SECRET","too-short")
    with pytest.raises(RuntimeError): main._secret()


def test_concurrent_surgery_bookings_share_the_same_limit(client):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from deployment.demo_app.hospital import reserve_surgery
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE surgery_capacity SET max_surgeries_per_day=1,available_beds=1")
    def book(case_id):
        con=sqlite3.connect(DB_PATH,timeout=10)
        con.row_factory=sqlite3.Row
        try:
            con.execute("BEGIN IMMEDIATE")
            reserve_surgery(con,case_id,future_workday(),"09:00","dr.maya","Concurrent capacity test")
            con.commit()
            return "confirmed"
        except HTTPException:
            con.rollback()
            return "full"
        finally:
            con.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(book,["DEMO-0001","DEMO-0003"]))
    assert sorted(statuses)==["confirmed","full"]


def test_doctor_interface_hides_removed_labs_and_blocks_unassigned_review(client):
    login(client)
    page=client.get("/doctor")
    nav=page.text.split('<nav aria-label="Primary">')[1].split("</nav>")[0]
    assert "/real-lab" not in nav and "/simulation" not in nav and 'href="/model"' not in nav
    assert client.get("/real-lab",follow_redirects=False).status_code==303
    assert client.get("/doctor/review/DEMO-0002").status_code==403
