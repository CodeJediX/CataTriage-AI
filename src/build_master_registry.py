from pathlib import Path
import csv
import hashlib

# --------------------------------------------------
# PROJECT PATHS
# --------------------------------------------------

ACTIVE_DATASET = Path(
    r"E:\Eye Project\data sets\Eye_Datasets_Organized"
)

EXCLUDED_DATASET = Path(
    r"E:\Eye Project\data sets\Excluded_Items_Review"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\master_dataset_registry.csv"
)


# --------------------------------------------------
# FILE TYPES WE CARE ABOUT
# --------------------------------------------------

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"
}

TABLE_EXTENSIONS = {
    ".csv", ".xlsx", ".xls"
}

DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md"
}


# --------------------------------------------------
# SMALL HELPER FUNCTIONS
# --------------------------------------------------

def classify_file_type(extension):
    extension = extension.lower()

    if extension in IMAGE_EXTENSIONS:
        return "image"

    if extension in TABLE_EXTENSIONS:
        return "table"

    if extension in DOCUMENT_EXTENSIONS:
        return "document"

    return "other"


def detect_dataset_group(relative_path):
    parts = relative_path.parts

    if not parts:
        return "unknown"

    return parts[0]


def detect_dataset_name(relative_path):
    parts = relative_path.parts

    if len(parts) >= 2:
        return parts[1]

    return parts[0] if parts else "unknown"


def detect_class_hint(relative_path):
    known_classes = {
        "normal",
        "cataract",
        "glaucoma",
        "retinal_disease",
    }

    for part in relative_path.parts:
        if part.lower() in known_classes:
            return part.lower()

    return ""


def detect_split_hint(relative_path):
    for part in relative_path.parts:
        value = part.lower()

        if value in {"train", "training"}:
            return "train"

        if value in {"val", "valid", "validation"}:
            return "validation"

        if value in {"test", "testing"}:
            return "test"

    return ""


def calculate_sha256(file_path, chunk_size=1024 * 1024):
    sha256 = hashlib.sha256()

    try:
        with open(file_path, "rb") as file:
            while True:
                chunk = file.read(chunk_size)

                if not chunk:
                    break

                sha256.update(chunk)

        return sha256.hexdigest()

    except Exception as error:
        return f"ERROR: {error}"


# --------------------------------------------------
# SCAN ONE DATASET FOLDER
# --------------------------------------------------

def scan_folder(root_folder, dataset_status):
    records = []

    for file_path in root_folder.rglob("*"):

        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(root_folder)

        extension = file_path.suffix.lower()

        record = {
            "dataset_status": dataset_status,
            "dataset_root": str(root_folder),
            "relative_path": str(relative_path),
            "full_path": str(file_path),
            "filename": file_path.name,
            "extension": extension,
            "file_type": classify_file_type(extension),
            "dataset_group": detect_dataset_group(relative_path),
            "dataset_name": detect_dataset_name(relative_path),
            "class_hint": detect_class_hint(relative_path),
            "split_hint": detect_split_hint(relative_path),
            "size_bytes": file_path.stat().st_size,
            "sha256": calculate_sha256(file_path),
        }

        records.append(record)

    return records


# --------------------------------------------------
# MAIN PROGRAM
# --------------------------------------------------

def main():

    print("CataTriage-AI — Master Dataset Registry Builder")
    print("----------------------------------------------")

    if not ACTIVE_DATASET.exists():
        print("ERROR: Active dataset folder was not found:")
        print(ACTIVE_DATASET)
        return

    if not EXCLUDED_DATASET.exists():
        print("ERROR: Excluded dataset folder was not found:")
        print(EXCLUDED_DATASET)
        return

    print()
    print("Scanning active dataset...")
    active_records = scan_folder(
        ACTIVE_DATASET,
        "ACTIVE"
    )

    print(
        f"Active files found: {len(active_records)}"
    )

    print()
    print("Scanning excluded review dataset...")

    excluded_records = scan_folder(
        EXCLUDED_DATASET,
        "EXCLUDED_DO_NOT_TRAIN"
    )

    print(
        f"Excluded files found: {len(excluded_records)}"
    )

    all_records = active_records + excluded_records

    fieldnames = [
        "registry_id",
        "dataset_status",
        "dataset_root",
        "dataset_group",
        "dataset_name",
        "relative_path",
        "full_path",
        "filename",
        "extension",
        "file_type",
        "class_hint",
        "split_hint",
        "size_bytes",
        "sha256",
    ]

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for index, record in enumerate(
            all_records,
            start=1
        ):
            record["registry_id"] = (
                f"FILE_{index:06d}"
            )

            writer.writerow(record)

    print()
    print("----------------------------------------------")
    print("DONE")
    print()
    print(f"Total files indexed: {len(all_records)}")
    print()
    print("Registry created at:")
    print(OUTPUT_FILE)
    print()
    print(
        "Important: EXCLUDED_DO_NOT_TRAIN files "
        "must never enter model training."
    )


if __name__ == "__main__":
    main()
