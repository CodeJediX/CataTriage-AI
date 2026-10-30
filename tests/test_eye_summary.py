from deployment.demo_app.eye_summary import summarize_eyes, partition_images


def image(id, side, top="normal", batch="visit", status="ok"):
    return {"id": id, "eye_side": side, "analysis": {"status": status, "top_class": top, "observation_group": batch}}


def test_one_affected_eye_does_not_use_the_last_uploaded_eye_as_patient_result():
    result = summarize_eyes([image(2,"Right"), image(1,"Left","cataract")], {"observation_group":"visit"})
    assert result["headline"] == "Cataract prediction: left eye."
    assert result["entries"][1]["status"] == "No top-class cataract prediction"
    assert "does not rule out" in result["entries"][1]["detail"]


def test_unknown_and_disagreement_and_failed_images_are_not_negative_results():
    result = summarize_eyes([image(1,"Not recorded","cataract"), image(2,"Left","cataract"),
                             image(3,"Left"), image(4,"Right", status="not_available")], {"observation_group":"visit"})
    assert "Mixed predictions" in result["entries"][0]["status"]
    assert result["entries"][1]["status"] == "Analysis unavailable"
    assert "cannot be identified" in result["entries"][2]["detail"]
    assert "eye side unknown" in result["headline"]


def test_new_visit_does_not_reuse_positive_image_from_old_visit():
    result = summarize_eyes([image(1,"Left","cataract","old"), image(2,"Right",batch="new")], {"observation_group":"new"})
    assert len(result["entries"]) == 1
    assert result["entries"][0]["side"] == "Right"
    assert "Cataract prediction:" not in result["headline"]


def test_round_partition_never_fills_missing_eye_with_an_older_upload():
    records=[image(1,"Not recorded","cataract","old"),image(2,"Left",batch="new"),image(3,"Right",batch="new")]
    current,older=partition_images(records,{"observation_group":"new"})
    assert [item["eye_side"] for item in current]==["Right","Left"]
    assert [item["id"] for item in older]==[1]
    empty,history=partition_images(records,{"status":"not_run","observation_group":"empty-round"})
    assert empty==[] and len(history)==3


def test_legacy_images_do_not_invent_a_bilateral_visit():
    current,older=partition_images([image(1,"Left","cataract","old"),image(2,"Right",batch="new")],None)
    assert [item["id"] for item in current]==[2] and [item["id"] for item in older]==[1]


def test_unknown_eye_real_model_keeps_laterality_unknown():
    import io
    from PIL import Image
    from deployment.demo_app.real_models import real_provider
    image_buffer = io.BytesIO()
    Image.new("RGB", (256,256), (90,120,100)).save(image_buffer, "PNG")
    result = real_provider.analyze_fusion(image_buffer.getvalue(), "slit_lamp", {"eye_side":"Not recorded"})
    assert result["status"] == "ok"
    assert result["laterality_unknown"] is True
    assert result["context_used"]["eye_side"] == "Not recorded"
    assert abs(sum(result["probabilities"].values())-1) < 0.0001
    assert "does not identify the eye" in result["laterality_note"]
