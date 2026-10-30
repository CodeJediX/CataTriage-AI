from pathlib import Path, PureWindowsPath
import csv
from collections import Counter, defaultdict


# ==========================================================
# PATHS
# ==========================================================

INPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\clean_image_training_manifest.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\grouped_image_manifest.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\grouping\group_assignment_summary.txt"
)

AUDIT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\grouping\group_assignment_audit.csv"
)


# ==========================================================
# HELPERS
# ==========================================================

def get_part_after(parts, target):
    """
    Return the folder immediately after target.
    Comparison is case-insensitive.
    """

    lowered = [part.lower() for part in parts]

    try:
        index = lowered.index(target.lower())

        if index + 1 < len(parts):
            return parts[index + 1]

    except ValueError:
        pass

    return ""


def get_part_after_n(parts, target, offset):
    lowered = [part.lower() for part in parts]

    try:
        index = lowered.index(target.lower())

        wanted = index + offset

        if wanted < len(parts):
            return parts[wanted]

    except ValueError:
        pass

    return ""


# ==========================================================
# GROUPING LOGIC
# ==========================================================

def assign_group(row):

    path = PureWindowsPath(row["full_path"])
    parts = list(path.parts)

    full_lower = row["full_path"].lower()

    registry_id = row["registry_id"]

    # ------------------------------------------------------
    # 1. NUCLEAR CATARACT DATABASE
    # ------------------------------------------------------

    if "nuclear cataract dataset" in full_lower:

        source_subject = get_part_after(
            parts,
            "Nuclear Cataract Dataset"
        )

        eye_folder = get_part_after_n(
            parts,
            "Nuclear Cataract Dataset",
            2
        )

        # Normalize numeric folder only for the group ID
        try:
            subject_normalized = f"{int(source_subject):03d}"
        except ValueError:
            subject_normalized = source_subject

        group_id = (
            f"NUCLEAR_SOURCE_SUBJECT_{subject_normalized}"
        )

        return {
            "group_id": group_id,
            "group_type": "SOURCE_SUBJECT_FOLDER",
            "group_basis": (
                "Numbered source folder under "
                "Nuclear Cataract Dataset; "
                "DER and IZQ kept together"
            ),
            "source_subject_or_sequence": source_subject,
            "eye_or_subfolder_hint": eye_folder,
            "grouping_confidence": "HIGH_STRUCTURE_BASED",
            "grouping_warning": "",
            "data_role": "IMAGE_CANDIDATE",
        }

    # ------------------------------------------------------
    # 2. TEMPORAL SLIT-LAMP SEQUENCES
    # ------------------------------------------------------

    if "ophthalmic_slit_lamp_60" in full_lower:

        sequence_id = path.parent.name

        group_id = (
            f"TEMPORAL_SEQUENCE_{sequence_id}"
        )

        return {
            "group_id": group_id,
            "group_type": "SEQUENCE",
            "group_basis": (
                "All images inside one temporal "
                "sequence folder remain together"
            ),
            "source_subject_or_sequence": sequence_id,
            "eye_or_subfolder_hint": "",
            "grouping_confidence": "HIGH_STRUCTURE_BASED",
            "grouping_warning": "",
            "data_role": "IMAGE_CANDIDATE",
        }

    # ------------------------------------------------------
    # 3. SUSTECH CORNEA LABEL MASKS
    # ------------------------------------------------------

    if "sustech_sysu" in full_lower:

        return {
            "group_id": f"SUSTECH_MASK_{registry_id}",
            "group_type": "MASK_ONLY_UNRESOLVED_PATIENT",
            "group_basis": (
                "Individual mask file; patient identity "
                "not available from current local structure"
            ),
            "source_subject_or_sequence": "",
            "eye_or_subfolder_hint": "",
            "grouping_confidence": "LIMITED",
            "grouping_warning": (
                "Current local package contains cornea label "
                "masks; do not treat these masks as normal "
                "Model-1 input images."
            ),
            "data_role": "SUPPORTING_MASK",
        }

    # ------------------------------------------------------
    # 4. BINARY CATARACT DATASET
    # ------------------------------------------------------

    if row["dataset_name"] == "binary_cataract_unknown_source":

        return {
            "group_id": f"BINARY_UNRESOLVED_{registry_id}",
            "group_type": "UNRESOLVED_PATIENT_SINGLE_IMAGE",
            "group_basis": (
                "No reliable patient/eye/sequence identifier "
                "available; exact duplicates already removed"
            ),
            "source_subject_or_sequence": "",
            "eye_or_subfolder_hint": "",
            "grouping_confidence": "LIMITED",
            "grouping_warning": (
                "Patient-level grouping cannot be verified "
                "from the available dataset structure."
            ),
            "data_role": "IMAGE_CANDIDATE_REVIEW",
        }

    # ------------------------------------------------------
    # 5. FOUR-CLASS RETINA DATASET
    # ------------------------------------------------------

    if row["dataset_name"] == "retina_four_class":

        return {
            "group_id": f"RETINA_UNRESOLVED_{registry_id}",
            "group_type": "UNRESOLVED_PATIENT_SINGLE_IMAGE",
            "group_basis": (
                "No patient/eye/sequence identifier available "
                "from current folder structure"
            ),
            "source_subject_or_sequence": "",
            "eye_or_subfolder_hint": "",
            "grouping_confidence": "LIMITED",
            "grouping_warning": (
                "Patient-level grouping cannot be verified "
                "from the available dataset structure."
            ),
            "data_role": "IMAGE_CANDIDATE_REVIEW",
        }

    # ------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------

    return {
        "group_id": f"UNRESOLVED_{registry_id}",
        "group_type": "UNRESOLVED_SINGLE_IMAGE",
        "group_basis": (
            "No supported grouping identifier found"
        ),
        "source_subject_or_sequence": "",
        "eye_or_subfolder_hint": "",
        "grouping_confidence": "LIMITED",
        "grouping_warning": (
            "Manual review required before splitting."
        ),
        "data_role": "REVIEW_REQUIRED",
    }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Group ID Assignment")
    print("===================================")
    print()

    if not INPUT_FILE.exists():

        print("ERROR:")
        print("Input manifest not found:")
        print(INPUT_FILE)

        return

    rows_out = []

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            # Only images allowed for later processing
            if row["training_status"] != "INCLUDE":
                continue

            grouping = assign_group(row)

            new_row = dict(row)

            new_row.update(grouping)

            rows_out.append(new_row)

    # ------------------------------------------------------
    # WRITE GROUPED MANIFEST
    # ------------------------------------------------------

    fields = [
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

        "group_id",
        "group_type",
        "group_basis",
        "source_subject_or_sequence",
        "eye_or_subfolder_hint",
        "grouping_confidence",
        "grouping_warning",
        "data_role",
    ]

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()

        for row in rows_out:
            writer.writerow({
                field: row.get(field, "")
                for field in fields
            })

    # ------------------------------------------------------
    # BUILD COUNTS
    # ------------------------------------------------------

    group_ids = defaultdict(list)

    group_type_counts = Counter()
    image_role_counts = Counter()

    for row in rows_out:

        group_ids[row["group_id"]].append(row)

        group_type_counts[
            row["group_type"]
        ] += 1

        image_role_counts[
            row["data_role"]
        ] += 1

    # Unique group counts by type
    unique_groups_by_type = defaultdict(set)

    for row in rows_out:
        unique_groups_by_type[
            row["group_type"]
        ].add(
            row["group_id"]
        )

    # ------------------------------------------------------
    # CREATE AUDIT FILE
    # ------------------------------------------------------

    audit_rows = []

    for group_id, members in sorted(
        group_ids.items()
    ):

        datasets = sorted({
            row["dataset_name"]
            for row in members
        })

        group_types = sorted({
            row["group_type"]
            for row in members
        })

        filenames = [
            row["filename"]
            for row in members
        ]

        audit_rows.append({
            "group_id": group_id,
            "group_type": " | ".join(group_types),
            "image_count": len(members),
            "datasets": " | ".join(datasets),
            "sample_filenames": " | ".join(
                filenames[:15]
            )
        })

    audit_fields = [
        "group_id",
        "group_type",
        "image_count",
        "datasets",
        "sample_filenames",
    ]

    with open(
        AUDIT_FILE,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=audit_fields
        )

        writer.writeheader()
        writer.writerows(audit_rows)

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    summary = []

    summary.append(
        "CataTriage-AI Group Assignment Summary"
    )

    summary.append(
        "====================================="
    )

    summary.append("")

    summary.append(
        f"TOTAL INCLUDED IMAGES: {len(rows_out)}"
    )

    summary.append(
        f"TOTAL UNIQUE GROUP IDs: {len(group_ids)}"
    )

    summary.append("")

    summary.append(
        "GROUP TYPES:"
    )

    for group_type in sorted(
        unique_groups_by_type
    ):

        image_count = group_type_counts[
            group_type
        ]

        group_count = len(
            unique_groups_by_type[group_type]
        )

        summary.append(
            f"- {group_type}: "
            f"{image_count} images / "
            f"{group_count} groups"
        )

    summary.append("")

    summary.append(
        "DATA ROLES:"
    )

    for role, count in sorted(
        image_role_counts.items()
    ):

        summary.append(
            f"- {role}: {count} images"
        )

    summary.append("")
    summary.append(
        "IMPORTANT:"
    )

    summary.append(
        "- No original files were moved."
    )

    summary.append(
        "- No original files were modified."
    )

    summary.append(
        "- No train/validation/test split was created."
    )

    summary.append(
        "- Nuclear DER/IZQ images from the same "
        "numbered source folder were grouped together."
    )

    summary.append(
        "- Temporal images from the same sequence "
        "folder were grouped together."
    )

    summary.append(
        "- Datasets without reliable patient IDs "
        "remain marked as unresolved."
    )

    summary.append(
        "- SUSTech cornea label masks are marked "
        "as supporting masks, not normal Model-1 inputs."
    )

    summary_text = "\n".join(summary)

    SUMMARY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary_text)

    print(summary_text)

    print()
    print("-----------------------------------")
    print("GROUP ASSIGNMENT COMPLETE")
    print("-----------------------------------")

    print()
    print("Grouped manifest:")
    print(OUTPUT_FILE)

    print()
    print("Audit report:")
    print(AUDIT_FILE)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()
