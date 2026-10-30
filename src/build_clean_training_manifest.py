from pathlib import Path
import csv

# --------------------------------------------------
# PATHS
# --------------------------------------------------

REGISTRY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\master_dataset_registry.csv"
)

DUPLICATE_ACTIONS_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\duplicates\duplicate_training_actions.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\clean_image_training_manifest.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\duplicates\clean_manifest_summary.txt"
)


# --------------------------------------------------
# LOAD DUPLICATE ACTIONS
# --------------------------------------------------

def load_duplicate_actions():
    actions = {}

    with open(
        DUPLICATE_ACTIONS_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:
            actions[row["registry_id"]] = row["suggested_action"]

    return actions


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print()
    print("CataTriage-AI — Clean Training Manifest Builder")
    print("===============================================")

    if not REGISTRY_FILE.exists():
        print("ERROR: Master registry not found.")
        print(REGISTRY_FILE)
        return

    if not DUPLICATE_ACTIONS_FILE.exists():
        print("ERROR: Duplicate actions file not found.")
        print(DUPLICATE_ACTIONS_FILE)
        return

    duplicate_actions = load_duplicate_actions()

    output_rows = []

    total_images = 0
    include_unique = 0
    include_canonical = 0
    excluded_duplicate = 0
    excluded_dataset = 0

    with open(
        REGISTRY_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            # Only image files belong in this manifest.
            if row["file_type"].lower() != "image":
                continue

            total_images += 1

            registry_id = row["registry_id"]

            # --------------------------------------
            # EXCLUDED DATASET
            # --------------------------------------

            if row["dataset_status"] != "ACTIVE":

                training_status = "EXCLUDE"
                reason = "EXCLUDED_DATASET"
                excluded_dataset += 1

            # --------------------------------------
            # ACTIVE FILE
            # --------------------------------------

            else:

                duplicate_action = duplicate_actions.get(
                    registry_id
                )

                if duplicate_action == "EXCLUDE_DUPLICATE_FROM_TRAINING":

                    training_status = "EXCLUDE"
                    reason = "DUPLICATE_ACTIVE_COPY"
                    excluded_duplicate += 1

                elif duplicate_action == "KEEP_CANONICAL":

                    training_status = "INCLUDE"
                    reason = "CANONICAL_DUPLICATE_COPY"
                    include_canonical += 1

                else:

                    training_status = "INCLUDE"
                    reason = "UNIQUE_IMAGE"
                    include_unique += 1

            output_rows.append({
                "registry_id": row["registry_id"],
                "training_status": training_status,
                "training_reason": reason,
                "dataset_status": row["dataset_status"],
                "dataset_group": row["dataset_group"],
                "dataset_name": row["dataset_name"],
                "class_hint": row["class_hint"],
                "split_hint_original": row["split_hint"],
                "filename": row["filename"],
                "full_path": row["full_path"],
                "sha256": row["sha256"],
            })

    # --------------------------------------------------
    # WRITE CLEAN MANIFEST
    # --------------------------------------------------

    fieldnames = [
        "registry_id",
        "training_status",
        "training_reason",
        "dataset_status",
        "dataset_group",
        "dataset_name",
        "class_hint",
        "split_hint_original",
        "filename",
        "full_path",
        "sha256",
    ]

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(output_rows)

    total_included = include_unique + include_canonical
    total_excluded = excluded_duplicate + excluded_dataset

    summary = f"""
CataTriage-AI Clean Training Manifest
=====================================

TOTAL IMAGE FILES
{total_images}

INCLUDED UNIQUE IMAGES
{include_unique}

INCLUDED CANONICAL DUPLICATE COPIES
{include_canonical}

TOTAL INCLUDED FOR LATER PROCESSING
{total_included}

EXCLUDED ACTIVE DUPLICATE COPIES
{excluded_duplicate}

EXCLUDED DATASET IMAGES
{excluded_dataset}

TOTAL EXCLUDED
{total_excluded}

IMPORTANT
=========

No original images were deleted or moved.

training_status = INCLUDE
    File may proceed to later preprocessing stages.

training_status = EXCLUDE
    File must not be used as an independent training sample.

The original supplied train/test split is NOT trusted yet.
New train/validation/test splits will be created later after
patient/eye/sequence grouping.
""".strip()

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(summary)

    print()
    print(summary)

    print()
    print("Clean manifest created:")
    print(OUTPUT_FILE)

    print()
    print("Summary created:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()
