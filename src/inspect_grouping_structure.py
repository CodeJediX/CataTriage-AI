from pathlib import Path
import csv
from collections import defaultdict, Counter


# ==========================================================
# PATHS
# ==========================================================

MANIFEST_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\clean_image_training_manifest.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\grouping"
)

DATASET_REPORT = OUTPUT_DIR / "dataset_grouping_audit.csv"

SUMMARY_REPORT = OUTPUT_DIR / "grouping_audit_summary.txt"


# ==========================================================
# READ INCLUDED IMAGES
# ==========================================================

def read_manifest():

    rows = []

    with open(
        MANIFEST_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            if row["training_status"] != "INCLUDE":
                continue

            rows.append(row)

    return rows


# ==========================================================
# BUILD DATASET SUMMARY
# ==========================================================

def analyze_datasets(rows):

    grouped = defaultdict(list)

    for row in rows:

        key = (
            row["dataset_group"],
            row["dataset_name"]
        )

        grouped[key].append(row)

    report_rows = []

    for (dataset_group, dataset_name), items in sorted(grouped.items()):

        filenames = [
            row["filename"]
            for row in items
        ]

        paths = [
            Path(row["full_path"])
            for row in items
        ]

        parent_folders = Counter(
            str(path.parent)
            for path in paths
        )

        extensions = Counter(
            path.suffix.lower()
            for path in paths
        )

        class_hints = Counter(
            row["class_hint"]
            for row in items
            if row["class_hint"]
        )

        split_hints = Counter(
            row["split_hint_original"]
            for row in items
            if row["split_hint_original"]
        )

        sample_names = filenames[:10]

        sample_parents = list(parent_folders.keys())[:10]

        report_rows.append({
            "dataset_group": dataset_group,
            "dataset_name": dataset_name,
            "image_count": len(items),
            "unique_parent_folders": len(parent_folders),
            "extensions": dict(extensions),
            "class_hints": dict(class_hints),
            "original_split_hints": dict(split_hints),
            "sample_filenames": " | ".join(sample_names),
            "sample_parent_folders": " | ".join(sample_parents),
        })

    return report_rows


# ==========================================================
# WRITE REPORT
# ==========================================================

def write_reports(rows, report_rows):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    fields = [
        "dataset_group",
        "dataset_name",
        "image_count",
        "unique_parent_folders",
        "extensions",
        "class_hints",
        "original_split_hints",
        "sample_filenames",
        "sample_parent_folders",
    ]

    with open(
        DATASET_REPORT,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(report_rows)

    total_images = len(rows)

    summary_lines = []

    summary_lines.append(
        "CataTriage-AI Grouping Audit"
    )

    summary_lines.append(
        "============================"
    )

    summary_lines.append("")

    summary_lines.append(
        f"TOTAL INCLUDED IMAGES: {total_images}"
    )

    summary_lines.append("")

    summary_lines.append(
        f"DATASET ENTRIES FOUND: {len(report_rows)}"
    )

    summary_lines.append("")

    summary_lines.append(
        "DATASETS:"
    )

    for row in report_rows:

        summary_lines.append(
            f"- {row['dataset_group']} / "
            f"{row['dataset_name']}: "
            f"{row['image_count']} images"
        )

    summary_lines.append("")

    summary_lines.append(
        "IMPORTANT:"
    )

    summary_lines.append(
        "This step only inspects filenames and folder structure."
    )

    summary_lines.append(
        "No grouping IDs were assigned yet."
    )

    summary_lines.append(
        "No train/validation/test split was created."
    )

    summary_lines.append(
        "No dataset files were changed."
    )

    summary = "\n".join(summary_lines)

    with open(
        SUMMARY_REPORT,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary)

    return summary


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Grouping Structure Inspector")
    print("=============================================")
    print()

    if not MANIFEST_FILE.exists():

        print("ERROR:")
        print("Clean training manifest was not found:")
        print(MANIFEST_FILE)

        return

    print("Reading clean training manifest...")

    rows = read_manifest()

    print(
        f"Included images loaded: {len(rows)}"
    )

    print()
    print("Inspecting dataset structure...")

    report_rows = analyze_datasets(rows)

    summary = write_reports(
        rows,
        report_rows
    )

    print()
    print(summary)

    print()
    print("---------------------------------------------")
    print("GROUPING AUDIT COMPLETE")
    print("---------------------------------------------")

    print()
    print("Detailed report:")
    print(DATASET_REPORT)

    print()
    print("Summary:")
    print(SUMMARY_REPORT)


if __name__ == "__main__":
    main()
