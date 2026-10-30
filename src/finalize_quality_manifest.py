from pathlib import Path
import pandas as pd


# ==========================================================
# PATHS
# ==========================================================

INPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality\image_quality_report.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\final_quality_manifest.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality\final_quality_summary.txt"
)


# ==========================================================
# CLASSIFY EACH IMAGE
# ==========================================================

def classify_image(row):

    path = str(row["full_path"]).lower()

    # ------------------------------------------------------
    # 1. TECHNICAL FAILURE
    # ------------------------------------------------------

    if row["decode_status"] != "PASS":

        return pd.Series({
            "final_quality_status": "EXCLUDE_TECHNICAL_FAILURE",
            "primary_model1_status": "EXCLUDE",
            "modality": "UNKNOWN",
            "final_quality_note":
                "Image could not be decoded."
        })

    # ------------------------------------------------------
    # 2. SUPPORTING MASKS
    # ------------------------------------------------------

    if row["data_role"] == "SUPPORTING_MASK":

        return pd.Series({
            "final_quality_status": "SUPPORTING_ONLY",
            "primary_model1_status": "NOT_PRIMARY_INPUT",
            "modality": "SEGMENTATION_MASK",
            "final_quality_note":
                "Supporting cornea mask; not a clinical input image."
        })

    # ------------------------------------------------------
    # 3. NUCLEAR CATARACT SLIT-LAMP
    # ------------------------------------------------------

    if "nuclear cataract dataset" in path:

        return pd.Series({
            "final_quality_status": "KEEP",
            "primary_model1_status": "PRIMARY_CANDIDATE",
            "modality": "SLIT_LAMP",
            "final_quality_note":
                "Dark background is expected for this slit-lamp "
                "acquisition style. Initial global brightness/blur "
                "flags are not used as automatic exclusion criteria."
        })

    # ------------------------------------------------------
    # 4. TEMPORAL SLIT-LAMP
    # ------------------------------------------------------

    if "ophthalmic_slit_lamp_60" in path:

        return pd.Series({
            "final_quality_status": "KEEP_WITH_WARNING",
            "primary_model1_status": "PRIMARY_CANDIDATE",
            "modality": "SLIT_LAMP",
            "final_quality_note":
                "Valid temporal slit-lamp frame; lower resolution "
                "than the Nuclear Cataract dataset. Keep sequence "
                "grouping during later splitting."
        })

    # ------------------------------------------------------
    # 5. RETINA FOUR-CLASS
    # ------------------------------------------------------

    if row["dataset_name"] == "retina_four_class":

        return pd.Series({
            "final_quality_status": "KEEP_SECONDARY",
            "primary_model1_status": "NOT_PRIMARY_SLIT_LAMP",
            "modality": "FUNDUS_RETINA",
            "final_quality_note":
                "Valid retinal/fundus image but different modality "
                "from the primary slit-lamp Model 1 input."
        })

    # ------------------------------------------------------
    # 6. BINARY CATARACT
    # ------------------------------------------------------

    if row["dataset_name"] == "binary_cataract_unknown_source":

        return pd.Series({
            "final_quality_status": "HOLD_DATASET_REVIEW",
            "primary_model1_status": "HOLD",
            "modality": "HETEROGENEOUS_EYE_IMAGE",
            "final_quality_note":
                "Highly variable image source, resolution and "
                "acquisition style. Source/license is unresolved. "
                "Do not use for the primary clinical model yet."
        })

    # ------------------------------------------------------
    # 7. FALLBACK
    # ------------------------------------------------------

    return pd.Series({
        "final_quality_status": "MANUAL_REVIEW",
        "primary_model1_status": "HOLD",
        "modality": "UNKNOWN",
        "final_quality_note":
            "Dataset or modality requires manual review."
    })


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Final Quality Manifest")
    print("======================================")
    print()

    if not INPUT_FILE.exists():

        print("ERROR:")
        print("Image quality report not found:")
        print(INPUT_FILE)
        return

    df = pd.read_csv(
        INPUT_FILE
    )

    # Add final decisions
    final_columns = df.apply(
        classify_image,
        axis=1
    )

    df = pd.concat(
        [df, final_columns],
        axis=1
    )

    # ------------------------------------------------------
    # SAVE MANIFEST
    # ------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    quality_counts = (
        df["final_quality_status"]
        .value_counts()
        .sort_index()
    )

    model_counts = (
        df["primary_model1_status"]
        .value_counts()
        .sort_index()
    )

    modality_counts = (
        df["modality"]
        .value_counts()
        .sort_index()
    )

    lines = []

    lines.append(
        "CataTriage-AI Final Quality Summary"
    )

    lines.append(
        "=================================="
    )

    lines.append("")

    lines.append(
        f"TOTAL IMAGES: {len(df)}"
    )

    lines.append("")

    lines.append(
        "FINAL QUALITY STATUS:"
    )

    for status, count in quality_counts.items():

        lines.append(
            f"- {status}: {count}"
        )

    lines.append("")

    lines.append(
        "PRIMARY MODEL 1 STATUS:"
    )

    for status, count in model_counts.items():

        lines.append(
            f"- {status}: {count}"
        )

    lines.append("")

    lines.append(
        "MODALITIES:"
    )

    for modality, count in modality_counts.items():

        lines.append(
            f"- {modality}: {count}"
        )

    lines.append("")
    lines.append(
        "IMPORTANT:"
    )

    lines.append(
        "- No original image was deleted."
    )

    lines.append(
        "- No original image was moved."
    )

    lines.append(
        "- No original image was resized."
    )

    lines.append(
        "- No image was rejected only because it was dark."
    )

    lines.append(
        "- No image was rejected only because of the "
        "initial blur metric."
    )

    lines.append(
        "- Nuclear and temporal slit-lamp data remain "
        "primary Model 1 candidates."
    )

    lines.append(
        "- Retina fundus data is preserved separately."
    )

    lines.append(
        "- Binary cataract data remains on hold for the "
        "primary clinical model."
    )

    summary = "\n".join(
        lines
    )

    SUMMARY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary)

    print(summary)

    print()
    print("--------------------------------------")
    print("FINAL QUALITY MANIFEST CREATED")
    print("--------------------------------------")

    print()
    print("Manifest:")
    print(OUTPUT_FILE)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()