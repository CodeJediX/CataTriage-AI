from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable


def run_workflow(image_bytes: bytes, modality: str, image_meta: dict, inference: Callable[[bytes, str], dict]) -> dict:
    """Run four deterministic, auditable stages; no stage assigns clinical priority."""
    stages = []
    quality_ok = bool(image_meta.get("width", 0) >= 128 and image_meta.get("height", 0) >= 128)
    stages.append({
        "agent": "Agent 1 — Data Preprocessing", "status": "passed" if quality_ok else "needs_review",
        "summary": f"Validated {image_meta.get('format')} image, {image_meta.get('width')}×{image_meta.get('height')} px; required fields checked.",
    })
    result = inference(image_bytes, modality) if quality_ok else {"status":"not_available","reason":"Image dimensions are below the technical quality threshold.","urgency":None}
    stages.append({
        "agent": "Agent 2 — Model Inference", "status": result.get("status", "not_available"),
        "summary": f"Ran the locked {result.get('model_scope', 'research model')}." if result.get("status") == "ok" else result.get("reason", "No validated model is available."),
    })
    flags = []
    if modality == "slit_lamp" and result.get("status") == "ok":
        flags.append("The slit-lamp result comes from a small public research snapshot and is not clinically validated.")
    elif modality != "fundus":
        flags.append("No compatible slit-lamp cataract-grade model is available.")
    if result.get("status") != "ok": flags.append("Inference is unavailable and must not be interpreted as a negative finding.")
    if result.get("uncertainty_warning"): flags.append("The model confidence is below the research display threshold.")
    if result.get("laterality_unknown"): flags.append(result["laterality_note"])
    flags.append("A clinician must review the image and choose any workflow tier manually.")
    stages.append({"agent":"Agent 3 — Safety & Rule Validation","status":"review_required","summary":" ".join(flags)})
    stages.append({
        "agent":"Agent 4 — Explanation & Reporting","status":"complete",
        "summary":"Prepared a research-only explanation with model scope, limitations, and clinician-review requirement; no diagnosis or treatment recommendation generated.",
    })
    result["agent_workflow"] = stages
    result["workflow_completed_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    result["clinical_priority"] = None
    result["requires_clinician_review"] = True
    return result
