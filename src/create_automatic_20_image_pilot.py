from pathlib import Path
from datetime import date
import pandas as pd


SOURCE_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\model1_clinician_label_sheet.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\model1_clinician_label_sheet_AUTO_PILOT.csv"
)


def main():

    print()
    print("CataTriage-AI — Automatic 20 Image Pilot")
    print("========================================")
    print()

    if not SOURCE_FILE.exists():

        print("ERROR:")
        print("Source label sheet not found:")
        print(SOURCE_FILE)
        return

    df = pd.read_csv(
        SOURCE_FILE,
        dtype=str
    ).fillna("")

    # Add column if needed
    if "unusable_reason" not in df.columns:
        df["unusable_reason"] = ""

    # Fill ONLY first 20 rows
    for index in range(
        min(20, len(df))
    ):

        df.at[
            index,
            "clinical_image_usable"
        ] = "UNSURE"

        df.at[
            index,
            "unusable_reason"
        ] = "OTHER"

        df.at[
            index,
            "cataract_present"
        ] = "UNSURE"

        df.at[
            index,
            "nuclear_opalescence_locs3"
        ] = ""

        df.at[
            index,
            "nuclear_color_locs3"
        ] = ""

        df.at[
            index,
            "cortical_locs3"
        ] = ""

        df.at[
            index,
            "psc_locs3"
        ] = ""

        df.at[
            index,
            "overall_severity"
        ] = "UNSURE"

        df.at[
            index,
            "reviewer_id"
        ] = "AUTO_TEST"

        df.at[
            index,
            "review_date"
        ] = date.today().isoformat()

        df.at[
            index,
            "comments"
        ] = "AUTOMATED PILOT TEST ONLY"

    df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print("Automatic pilot created.")
    print()
    print("First 20 rows:")
    print("  reviewer_id = AUTO_TEST")
    print("  clinical labels = UNSURE")
    print()
    print("IMPORTANT:")
    print("These are NOT medical ground-truth labels.")
    print("Do NOT use these 20 rows for model training.")
    print()
    print("Output:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()