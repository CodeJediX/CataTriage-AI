from pathlib import Path
import pandas as pd


# ==========================================================
# PATHS
# ==========================================================

STANDARDIZED_MANIFEST = Path(
    r"E:\Eye Project\CataTriage_AI\data_processed\model1_slit_lamp_384_manifest.csv"
)

FINAL_QUALITY_MANIFEST = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\final_quality_manifest.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels\model1_label_audit.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels\model1_label_audit_summary.txt"
)


# ==========================================================
# LABEL AUDIT
# ==========================================================

def classify_label_status(row):

    path = str(row["source_path"]).lower()

    # ------------------------------------------------------
    # NUCLEAR CATARACT DATASET
    # ------------------------------------------------------

    if "nuclear cataract dataset" in path:

        return pd.Series({
            "dataset_component": "NUCLEAR_CATARACT",
            "detection_label_status": "UNVERIFIED",
            "severity_label_status": "MISSING",
            "urgency_label_status": "MISSING",
            "label_source": "NONE_USABLE_YET",
            "label_note":
                "LOCS III grading workbook is not currently available. "
                "Do not infer severity from folder names or filenames."
        })

    # ------------------------------------------------------
    # TEMPORAL SLIT-LAMP DATASET
    # ------------------------------------------------------

    if "ophthalmic_slit_lamp_60" in path:

        return pd.Series({
            "dataset_component": "TEMPORAL_SLIT_LAMP",
            "detection_label_status": "UNVERIFIED",
            "severity_label_status": "MISSING",
            "urgency_label_status": "MISSING",
            "label_source": "NONE_USABLE_YET",
            "label_note":
                "Temporal sequence grouping is known, but reliable "
                "clinical cataract severity and urgency labels are not "
                "present in the current processed manifest."
        })

    # ------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------

    return pd.Series({
        "dataset_component": "UNKNOWN",
        "detection_label_status": "UNVERIFIED",
        "severity_label_status": "UNVERIFIED",
        "urgency_label_status": "UNVERIFIED",
        "label_source": "UNKNOWN",
        "label_note":
            "Manual dataset review required."
    })


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Model 1 Label Audit")
    print("===================================")
    print()

    if not STANDARDIZED_MANIFEST.exists():

        print("ERROR:")
        print("Standardized manifest not found:")
        print(STANDARDIZED_MANIFEST)
        return

    df = pd.read_csv(
        STANDARDIZED_MANIFEST
    )

    print(
        f"Standardized Model 1 images: {len(df)}"
    )

    audit_cols = df.apply(
        classify_label_status,
        axis=1
    )

    df = pd.concat(
        [df, audit_cols],
        axis=1
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    component_counts = (
        df["dataset_component"]
        .value_counts()
        .sort_index()
    )

    detection_counts = (
        df["detection_label_status"]
        .value_counts()
        .sort_index()
    )

    severity_counts = (
        df["severity_label_status"]
        .value_counts()
        .sort_index()
    )

    urgency_counts = (
        df["urgency_label_status"]
        .value_counts()
        .sort_index()
    )

    lines = []

    lines.append(
        "CataTriage-AI Model 1 Label Audit"
    )

    lines.append(
        "================================="
    )

    lines.append("")

    lines.append(
        f"TOTAL STANDARDIZED IMAGES: {len(df)}"
    )

    lines.append("")

    lines.append(
        "DATASET COMPONENTS:"
    )

    for name, count in component_counts.items():
        lines.append(
            f"- {name}: {count}"
        )

    lines.append("")

    lines.append(
        "DETECTION LABEL STATUS:"
    )

    for name, count in detection_counts.items():
        lines.append(
            f"- {name}: {count}"
        )

    lines.append("")

    lines.append(
        "SEVERITY LABEL STATUS:"
    )

    for name, count in severity_counts.items():
        lines.append(
            f"- {name}: {count}"
        )

    lines.append("")

    lines.append(
        "URGENCY LABEL STATUS:"
    )

    for name, count in urgency_counts.items():
        lines.append(
            f"- {name}: {count}"
        )

    lines.append("")

    lines.append(
        "IMPORTANT:"
    )

    lines.append(
        "- No labels were invented."
    )

    lines.append(
        "- No severity was inferred from filenames."
    )

    lines.append(
        "- No urgency was inferred from image appearance."
    )

    lines.append(
        "- Missing clinician labels must be obtained or "
        "created before supervised severity/urgency training."
    )

    summary = "\n".join(lines)

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
    print("-----------------------------------")
    print("LABEL AUDIT COMPLETE")
    print("-----------------------------------")

    print()
    print("Detailed audit:")
    print(OUTPUT_FILE)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()