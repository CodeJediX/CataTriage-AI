"""Summarise upload-labelled eyes without inferring anatomical laterality."""
from __future__ import annotations

import json


def summarize_eyes(images: list[dict], current_analysis: dict | None) -> dict:
    batch = (current_analysis or {}).get("observation_group")
    records = []
    for image in images:
        result = image.get("analysis") or json.loads(image.get("analysis_json") or "{}")
        if batch and result.get("observation_group") != batch:
            continue
        records.append({**image, "analysis": result})
    # Legacy uploads have no encounter identifier: use only the most recent
    # image for each label, and explicitly explain the possible date difference.
    if not batch:
        latest = {}
        for record in sorted(records, key=lambda item: item.get("id", 0), reverse=True):
            latest.setdefault(record["eye_side"], record)
        records = list(latest.values())
    entries = []
    for side, label in (("Left", "Left eye"), ("Right", "Right eye"), ("Not recorded", "Eye side unknown"), ("Both", "Eye side not individually labelled")):
        group = [item for item in records if item["eye_side"] == side]
        if not group:
            continue
        valid = [item for item in group if item["analysis"].get("status") == "ok"]
        positive = [item for item in valid if str(item["analysis"].get("top_class", "")).lower() == "cataract"]
        uncertain = any(item["analysis"].get("uncertainty_warning") for item in valid)
        if positive:
            status = "Cataract prediction"
            detail = f"{len(positive)} of {len(group)} uploaded images have cataract as the top model class."
            if len(positive) < len(valid):
                status = "Mixed predictions · cataract signal present"
                detail += " Results disagree across views; inspect every image."
        elif valid:
            status = "No top-class cataract prediction"
            detail = "This does not rule out cataract. Review the images and other model findings."
        else:
            status = "Analysis unavailable"
            detail = "No usable prediction is available; this is not a negative finding."
        if len(valid) < len(group) and valid:
            detail += f" {len(group)-len(valid)} image(s) could not be analysed."
        if uncertain:
            detail += " At least one result has low model confidence."
        if side not in {"Left", "Right"}:
            detail += " Left or right cannot be identified from the upload label."
        entries.append({"side": side, "label": label, "status": status, "detail": detail,
                        "cataract_signal": bool(positive), "count": len(group)})
    affected = [item["label"].lower() for item in entries if item["cataract_signal"]]
    headline = "Cataract prediction: " + " and ".join(affected) + "." if affected else "No top-class cataract prediction in the analysed views."
    if not any(item["analysis"].get("status") == "ok" for item in records):
        headline = "No usable image prediction is available."
    return {"entries": entries, "headline": headline,
            "scope": "Results from this intake only. Earlier images remain in the history." if batch else "Latest image per eye label; these may come from different visits. Check image dates."}
