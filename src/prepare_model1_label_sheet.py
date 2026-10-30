from pathlib import Path
import pandas as pd


# ==========================================================
# PATHS
# ==========================================================

LABEL_AUDIT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels\model1_label_audit.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\model1_clinician_label_sheet.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels\label_sheet_summary.txt"
)


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Model 1 Clinician Label Sheet")
    print("==============================================")
    print()

    if not LABEL_AUDIT_FILE.exists():
        print("ERROR:")
        print("Label audit file not found:")
        print(LABEL_AUDIT_FILE)
        return

    df = pd.read_csv(
        LABEL_AUDIT_FILE
    )

    # ------------------------------------------------------
    # KEEP IMPORTANT IDENTIFICATION FIELDS
    # ------------------------------------------------------

    columns_to_keep = [
        "registry_id",
        "group_id",
        "dataset_component",
        "source_path",
        "processed_path",
    ]

    label_df = df[
        columns_to_keep
    ].copy()

    # ------------------------------------------------------
    # ADD EMPTY CLINICIAN LABEL COLUMNS
    # ------------------------------------------------------

    label_df["clinical_image_usable"] = ""

    label_df["cataract_present"] = ""

    label_df["nuclear_opalescence_locs3"] = ""

    label_df["nuclear_color_locs3"] = ""

    label_df["cortical_locs3"] = ""

    label_df["psc_locs3"] = ""

    label_df["overall_severity"] = ""

    label_df["reviewer_id"] = ""

    label_df["review_date"] = ""

    label_df["comments"] = ""

    # ------------------------------------------------------
    # SAVE LABEL SHEET
    # ------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    label_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    nuclear_count = (
        label_df["dataset_component"]
        == "NUCLEAR_CATARACT"
    ).sum()

    temporal_count = (
        label_df["dataset_component"]
        == "TEMPORAL_SLIT_LAMP"
    ).sum()

    summary = f"""
CataTriage-AI Model 1 Clinician Label Sheet
===========================================

TOTAL IMAGES FOR REVIEW
{len(label_df)}

NUCLEAR CATARACT IMAGES
{nuclear_count}

TEMPORAL SLIT-LAMP IMAGES
{temporal_count}


LABEL FIELDS
============

clinical_image_usable
    YES / NO / UNSURE

cataract_present
    YES / NO / UNSURE

nuclear_opalescence_locs3
    Clinician LOCS III value if applicable

nuclear_color_locs3
    Clinician LOCS III value if applicable

cortical_locs3
    Clinician LOCS III value if applicable

psc_locs3
    Clinician LOCS III value if applicable

overall_severity
    NORMAL / MILD / MODERATE / SEVERE / UNSURE

reviewer_id
    Identifier for clinician/reviewer

review_date
    Date of review

comments
    Optional reviewer notes


IMPORTANT
=========

Do not infer labels from filenames.

Do not infer severity automatically.

Do not invent missing LOCS III values.

Urgency is NOT collected here.

Urgency labeling will be handled later for Model 2
using image results plus clinical information.
""".strip()

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
    print("----------------------------------------------")
    print("CLINICIAN LABEL SHEET CREATED")
    print("----------------------------------------------")

    print()
    print("Label sheet:")
    print(OUTPUT_FILE)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()