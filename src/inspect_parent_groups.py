from pathlib import Path
import csv
from collections import defaultdict


MANIFEST_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\clean_image_training_manifest.csv"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\grouping\parent_folder_audit.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\grouping\parent_folder_summary.txt"
)


def main():

    print()
    print("CataTriage-AI — Parent Folder Inspector")
    print("=======================================")
    print()

    if not MANIFEST_FILE.exists():
        print("ERROR: Clean manifest not found:")
        print(MANIFEST_FILE)
        return

    groups = defaultdict(list)

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

            path = Path(row["full_path"])

            key = (
                row["dataset_group"],
                row["dataset_name"],
                str(path.parent)
            )

            groups[key].append(row)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_rows = []

    for (
        dataset_group,
        dataset_name,
        parent_folder
    ), items in sorted(groups.items()):

        filenames = [
            row["filename"]
            for row in items
        ]

        output_rows.append({
            "dataset_group": dataset_group,
            "dataset_name": dataset_name,
            "parent_folder": parent_folder,
            "image_count": len(items),
            "sample_filenames": " | ".join(
                filenames[:15]
            )
        })

    fields = [
        "dataset_group",
        "dataset_name",
        "parent_folder",
        "image_count",
        "sample_filenames",
    ]

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
        writer.writerows(output_rows)

    dataset_counts = defaultdict(int)

    for row in output_rows:
        dataset_counts[
            (
                row["dataset_group"],
                row["dataset_name"]
            )
        ] += 1

    summary_lines = []

    summary_lines.append(
        "CataTriage-AI Parent Folder Audit"
    )

    summary_lines.append(
        "================================"
    )

    summary_lines.append("")

    summary_lines.append(
        f"TOTAL PARENT FOLDERS: {len(output_rows)}"
    )

    summary_lines.append("")

    summary_lines.append(
        "PARENT FOLDERS BY DATASET:"
    )

    for key, count in sorted(
        dataset_counts.items()
    ):
        summary_lines.append(
            f"- {key[0]} / {key[1]}: "
            f"{count} parent folders"
        )

    summary_lines.append("")
    summary_lines.append(
        "No files were moved or modified."
    )

    summary_lines.append(
        "No group IDs were assigned yet."
    )

    summary = "\n".join(summary_lines)

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary)

    print(summary)

    print()
    print("Detailed report created:")
    print(OUTPUT_FILE)

    print()
    print("Summary created:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()
