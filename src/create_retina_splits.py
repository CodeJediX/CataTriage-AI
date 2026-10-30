from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split


# ==========================================================
# PATHS
# ==========================================================

INPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\final_quality_manifest.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\data_splits\retina_four_class"
)

FULL_SPLIT_FILE = OUTPUT_DIR / "retina_split_manifest.csv"

TRAIN_FILE = OUTPUT_DIR / "train.csv"

VAL_FILE = OUTPUT_DIR / "validation.csv"

TEST_FILE = OUTPUT_DIR / "test.csv"

SUMMARY_FILE = OUTPUT_DIR / "split_summary.txt"


# ==========================================================
# SETTINGS
# ==========================================================

RANDOM_SEED = 42


# ==========================================================
# GET CLASS LABEL FROM FOLDER
# ==========================================================

def get_retina_label(path_string):

    path = Path(path_string)

    parent = path.parent.name.lower().strip()

    valid_labels = {
        "normal",
        "cataract",
        "glaucoma",
        "retinal_disease"
    }

    if parent in valid_labels:
        return parent

    return "UNKNOWN"


# ==========================================================
# CHECK SHA256 OVERLAP
# ==========================================================

def get_hash_set(df):

    return set(
        df["sha256"]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Retina Four-Class Split")
    print("=======================================")
    print()

    if not INPUT_FILE.exists():

        print("ERROR:")
        print("Final quality manifest not found:")
        print(INPUT_FILE)

        return

    df = pd.read_csv(
        INPUT_FILE
    )

    # ------------------------------------------------------
    # SELECT RETINA FOUR-CLASS DATA
    # ------------------------------------------------------

    retina = df[
        df["dataset_name"]
        == "retina_four_class"
    ].copy()

    print(
        f"Retina images found: {len(retina)}"
    )

    if len(retina) == 0:

        print("ERROR:")
        print("No retina_four_class images were found.")

        return

    # ------------------------------------------------------
    # CREATE CLASS LABEL
    # ------------------------------------------------------

    retina["label"] = retina[
        "full_path"
    ].apply(
        get_retina_label
    )

    # ------------------------------------------------------
    # VERIFY LABELS
    # ------------------------------------------------------

    unknown = retina[
        retina["label"] == "UNKNOWN"
    ]

    if len(unknown) > 0:

        print()
        print("ERROR:")
        print(
            f"{len(unknown)} images have unknown labels."
        )

        print(
            "Do not continue until they are reviewed."
        )

        return

    # ------------------------------------------------------
    # SHOW ORIGINAL CLASS COUNTS
    # ------------------------------------------------------

    print()
    print("Original class counts:")

    for label, count in (
        retina["label"]
        .value_counts()
        .sort_index()
        .items()
    ):

        print(
            f"  {label}: {count}"
        )

    # ------------------------------------------------------
    # SPLIT 1
    #
    # 70% train
    # 30% temporary
    # ------------------------------------------------------

    train_df, temp_df = train_test_split(
        retina,
        test_size=0.30,
        random_state=RANDOM_SEED,
        stratify=retina["label"]
    )

    # ------------------------------------------------------
    # SPLIT 2
    #
    # 30% temporary becomes:
    #
    # 15% validation
    # 15% test
    # ------------------------------------------------------

    val_df, test_df = train_test_split(
        temp_df,
        test_size=0.50,
        random_state=RANDOM_SEED,
        stratify=temp_df["label"]
    )

    # ------------------------------------------------------
    # ADD FINAL SPLIT COLUMN
    # ------------------------------------------------------

    train_df = train_df.copy()

    val_df = val_df.copy()

    test_df = test_df.copy()

    train_df["final_split"] = "train"

    val_df["final_split"] = "validation"

    test_df["final_split"] = "test"

    # ------------------------------------------------------
    # CHECK HASH OVERLAP
    # ------------------------------------------------------

    train_hashes = get_hash_set(
        train_df
    )

    val_hashes = get_hash_set(
        val_df
    )

    test_hashes = get_hash_set(
        test_df
    )

    train_val_overlap = (
        train_hashes
        & val_hashes
    )

    train_test_overlap = (
        train_hashes
        & test_hashes
    )

    val_test_overlap = (
        val_hashes
        & test_hashes
    )

    if (
        len(train_val_overlap) > 0
        or len(train_test_overlap) > 0
        or len(val_test_overlap) > 0
    ):

        print()
        print("ERROR:")
        print(
            "Duplicate SHA256 values were found "
            "between splits."
        )

        return

    # ------------------------------------------------------
    # COMBINE MANIFEST
    # ------------------------------------------------------

    full_df = pd.concat(
        [
            train_df,
            val_df,
            test_df
        ],
        ignore_index=True
    )

    # ------------------------------------------------------
    # CREATE OUTPUT FOLDER
    # ------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # ------------------------------------------------------
    # SAVE CSV FILES
    # ------------------------------------------------------

    full_df.to_csv(
        FULL_SPLIT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    train_df.to_csv(
        TRAIN_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    val_df.to_csv(
        VAL_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    test_df.to_csv(
        TEST_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    # ------------------------------------------------------
    # BUILD SUMMARY
    # ------------------------------------------------------

    lines = []

    lines.append(
        "CataTriage-AI Retina Four-Class Split"
    )

    lines.append(
        "====================================="
    )

    lines.append("")

    lines.append(
        f"TOTAL IMAGES: {len(full_df)}"
    )

    lines.append("")

    lines.append(
        f"TRAIN: {len(train_df)}"
    )

    lines.append(
        f"VALIDATION: {len(val_df)}"
    )

    lines.append(
        f"TEST: {len(test_df)}"
    )

    lines.append("")

    lines.append(
        "ORIGINAL CLASS COUNTS:"
    )

    for label, count in (
        retina["label"]
        .value_counts()
        .sort_index()
        .items()
    ):

        lines.append(
            f"- {label}: {count}"
        )

    lines.append("")

    lines.append(
        "TRAIN CLASS COUNTS:"
    )

    for label, count in (
        train_df["label"]
        .value_counts()
        .sort_index()
        .items()
    ):

        lines.append(
            f"- {label}: {count}"
        )

    lines.append("")

    lines.append(
        "VALIDATION CLASS COUNTS:"
    )

    for label, count in (
        val_df["label"]
        .value_counts()
        .sort_index()
        .items()
    ):

        lines.append(
            f"- {label}: {count}"
        )

    lines.append("")

    lines.append(
        "TEST CLASS COUNTS:"
    )

    for label, count in (
        test_df["label"]
        .value_counts()
        .sort_index()
        .items()
    ):

        lines.append(
            f"- {label}: {count}"
        )

    lines.append("")

    lines.append(
        "DUPLICATE HASH OVERLAP:"
    )

    lines.append(
        f"- Train vs Validation: "
        f"{len(train_val_overlap)}"
    )

    lines.append(
        f"- Train vs Test: "
        f"{len(train_test_overlap)}"
    )

    lines.append(
        f"- Validation vs Test: "
        f"{len(val_test_overlap)}"
    )

    lines.append("")

    lines.append(
        "IMPORTANT:"
    )

    lines.append(
        "- Split ratio is approximately 70/15/15."
    )

    lines.append(
        "- Split is stratified by class."
    )

    lines.append(
        "- Random seed = 42."
    )

    lines.append(
        "- Exact duplicate hashes do not cross splits."
    )

    lines.append(
        "- Original images were not moved."
    )

    lines.append(
        "- Original images were not modified."
    )

    lines.append(
        "- Test split must remain isolated until "
        "final evaluation."
    )

    lines.append(
        "- Reliable patient IDs are not available "
        "for this dataset, so this is an image-level "
        "stratified split."
    )

    summary = "\n".join(
        lines
    )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            summary
        )

    # ------------------------------------------------------
    # TERMINAL OUTPUT
    # ------------------------------------------------------

    print()
    print(summary)

    print()
    print("--------------------------------------")
    print("STEP 8A COMPLETE")
    print("--------------------------------------")

    print()
    print("Output folder:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()