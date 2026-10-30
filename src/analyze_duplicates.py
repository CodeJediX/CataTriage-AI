from pathlib import Path
import csv
from collections import defaultdict


# ==========================================================
# PATHS
# ==========================================================

REGISTRY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\master_dataset_registry.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\duplicates"
)

GROUP_REPORT = OUTPUT_DIR / "duplicate_groups.csv"

ACTION_REPORT = OUTPUT_DIR / "duplicate_training_actions.csv"

SUMMARY_REPORT = OUTPUT_DIR / "duplicate_summary.txt"


# ==========================================================
# READ REGISTRY
# ==========================================================

def read_registry():
    records = []

    with open(
        REGISTRY_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            # We only care about image files in this step.
            if row["file_type"].lower() != "image":
                continue

            # Ignore invalid/error hashes if any.
            sha256 = row["sha256"].strip()

            if not sha256:
                continue

            if sha256.startswith("ERROR"):
                continue

            records.append(row)

    return records


# ==========================================================
# GROUP FILES BY SHA-256
# ==========================================================

def build_duplicate_groups(records):
    groups = defaultdict(list)

    for row in records:
        groups[row["sha256"]].append(row)

    duplicate_groups = {
        sha256: group
        for sha256, group in groups.items()
        if len(group) > 1
    }

    return groups, duplicate_groups


# ==========================================================
# PICK CANONICAL FILE
# ==========================================================

def choose_canonical(group):
    """
    Priority:
    1. ACTIVE file
    2. Alphabetically first path
    """

    active_files = [
        row
        for row in group
        if row["dataset_status"] == "ACTIVE"
    ]

    if active_files:
        return sorted(
            active_files,
            key=lambda x: x["full_path"].lower()
        )[0]

    return sorted(
        group,
        key=lambda x: x["full_path"].lower()
    )[0]


# ==========================================================
# CREATE REPORTS
# ==========================================================

def create_reports(records, all_hash_groups, duplicate_groups):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    group_rows = []
    action_rows = []

    duplicate_group_number = 0

    groups_with_active_duplicates = 0
    cross_split_groups = 0
    class_conflict_groups = 0
    active_and_excluded_groups = 0

    active_duplicate_files_to_exclude = 0
    excluded_files_seen = 0

    for sha256, group in sorted(
        duplicate_groups.items(),
        key=lambda x: x[0]
    ):

        duplicate_group_number += 1

        group_id = f"DUP_{duplicate_group_number:05d}"

        canonical = choose_canonical(group)

        statuses = {
            row["dataset_status"]
            for row in group
        }

        active_members = [
            row for row in group
            if row["dataset_status"] == "ACTIVE"
        ]

        excluded_members = [
            row for row in group
            if row["dataset_status"] != "ACTIVE"
        ]

        if len(active_members) > 1:
            groups_with_active_duplicates += 1

        if active_members and excluded_members:
            active_and_excluded_groups += 1

        split_values = {
            row["split_hint"].strip().lower()
            for row in group
            if row["split_hint"].strip()
        }

        cross_split = len(split_values) > 1

        if cross_split:
            cross_split_groups += 1

        class_values = {
            row["class_hint"].strip().lower()
            for row in group
            if row["class_hint"].strip()
        }

        class_conflict = len(class_values) > 1

        if class_conflict:
            class_conflict_groups += 1

        for row in group:

            is_canonical = (
                row["full_path"] == canonical["full_path"]
            )

            if row["dataset_status"] == "EXCLUDED_DO_NOT_TRAIN":
                suggested_action = "KEEP_EXCLUDED_DO_NOT_TRAIN"
                excluded_files_seen += 1

            elif is_canonical:
                suggested_action = "KEEP_CANONICAL"

            else:
                suggested_action = "EXCLUDE_DUPLICATE_FROM_TRAINING"
                active_duplicate_files_to_exclude += 1

            group_rows.append({
                "duplicate_group_id": group_id,
                "sha256": sha256,
                "group_size": len(group),
                "active_count": len(active_members),
                "excluded_count": len(excluded_members),
                "cross_split_duplicate": "YES" if cross_split else "NO",
                "class_conflict": "YES" if class_conflict else "NO",
                "dataset_status": row["dataset_status"],
                "dataset_group": row["dataset_group"],
                "dataset_name": row["dataset_name"],
                "class_hint": row["class_hint"],
                "split_hint": row["split_hint"],
                "filename": row["filename"],
                "full_path": row["full_path"],
                "canonical_file": canonical["full_path"],
                "suggested_action": suggested_action,
            })

            action_rows.append({
                "duplicate_group_id": group_id,
                "registry_id": row["registry_id"],
                "sha256": sha256,
                "dataset_status": row["dataset_status"],
                "class_hint": row["class_hint"],
                "split_hint": row["split_hint"],
                "full_path": row["full_path"],
                "suggested_action": suggested_action,
            })

    # ------------------------------------------------------
    # WRITE DUPLICATE GROUP REPORT
    # ------------------------------------------------------

    group_fields = [
        "duplicate_group_id",
        "sha256",
        "group_size",
        "active_count",
        "excluded_count",
        "cross_split_duplicate",
        "class_conflict",
        "dataset_status",
        "dataset_group",
        "dataset_name",
        "class_hint",
        "split_hint",
        "filename",
        "full_path",
        "canonical_file",
        "suggested_action",
    ]

    with open(
        GROUP_REPORT,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=group_fields
        )

        writer.writeheader()
        writer.writerows(group_rows)

    # ------------------------------------------------------
    # WRITE TRAINING ACTION REPORT
    # ------------------------------------------------------

    action_fields = [
        "duplicate_group_id",
        "registry_id",
        "sha256",
        "dataset_status",
        "class_hint",
        "split_hint",
        "full_path",
        "suggested_action",
    ]

    with open(
        ACTION_REPORT,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=action_fields
        )

        writer.writeheader()
        writer.writerows(action_rows)

    # ------------------------------------------------------
    # CALCULATE SUMMARY
    # ------------------------------------------------------

    total_images = len(records)

    unique_image_hashes = len(all_hash_groups)

    duplicate_groups_count = len(duplicate_groups)

    duplicate_file_occurrences = sum(
        len(group)
        for group in duplicate_groups.values()
    )

    duplicate_surplus = (
        total_images - unique_image_hashes
    )

    summary = f"""
CataTriage-AI Duplicate Analysis
================================

TOTAL IMAGE FILES SCANNED
{total_images}

UNIQUE IMAGE CONTENTS
{unique_image_hashes}

DUPLICATE GROUPS
{duplicate_groups_count}

FILES BELONGING TO DUPLICATE GROUPS
{duplicate_file_occurrences}

EXTRA DUPLICATE COPIES
{duplicate_surplus}

GROUPS WITH MORE THAN ONE ACTIVE FILE
{groups_with_active_duplicates}

GROUPS CONTAINING ACTIVE + EXCLUDED COPIES
{active_and_excluded_groups}

CROSS-SPLIT DUPLICATE GROUPS
{cross_split_groups}

CLASS-CONFLICT DUPLICATE GROUPS
{class_conflict_groups}

ACTIVE DUPLICATE FILES SUGGESTED FOR EXCLUSION
{active_duplicate_files_to_exclude}

EXCLUDED_DO_NOT_TRAIN FILES FOUND INSIDE DUPLICATE GROUPS
{excluded_files_seen}


IMPORTANT
=========

No files were deleted.
No files were moved.
No dataset files were modified.

This step only created reports.

KEEP_CANONICAL
    One selected copy of identical content.

EXCLUDE_DUPLICATE_FROM_TRAINING
    Active duplicate that should not be used as another
    independent training sample.

KEEP_EXCLUDED_DO_NOT_TRAIN
    File already located in the excluded review dataset.

CLASS-CONFLICT
    Identical image content appears under different class labels.
    This must be manually reviewed before training.

CROSS-SPLIT DUPLICATE
    Identical image content appears in more than one supplied
    train/validation/test split.
    The supplied split must not be trusted for final evaluation.
"""

    with open(
        SUMMARY_REPORT,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary.strip())

    return summary


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Duplicate Analysis")
    print("==================================")
    print()

    if not REGISTRY_FILE.exists():
        print("ERROR:")
        print("Registry file was not found:")
        print(REGISTRY_FILE)
        return

    print("Reading master dataset registry...")

    records = read_registry()

    print(
        f"Image records loaded: {len(records)}"
    )

    print()
    print("Grouping images using SHA-256...")

    all_hash_groups, duplicate_groups = (
        build_duplicate_groups(records)
    )

    print(
        f"Duplicate groups found: "
        f"{len(duplicate_groups)}"
    )

    print()
    print("Creating duplicate reports...")

    summary = create_reports(
        records,
        all_hash_groups,
        duplicate_groups
    )

    print(summary)

    print()
    print("----------------------------------")
    print("STEP 3 ANALYSIS COMPLETE")
    print("----------------------------------")
    print()
    print("Reports created in:")
    print(OUTPUT_DIR)
    print()
    print("DO NOT DELETE ANY FILES YET.")


if __name__ == "__main__":
    main()
