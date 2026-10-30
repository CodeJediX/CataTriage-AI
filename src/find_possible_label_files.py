from pathlib import Path
import csv


ROOT = Path(
    r"E:\Eye Project\data sets\Eye_Datasets_Organized"
)

OUTPUT = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels\possible_label_files.csv"
)


KEYWORDS = [
    "label",
    "labels",
    "grade",
    "grading",
    "severity",
    "locs",
    "locs3",
    "locs iii",
    "nuclear",
    "opalescence",
    "color",
    "annotation",
    "groundtruth",
    "ground_truth",
    "target"
]


INTERESTING_EXTENSIONS = {
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".txt",
    ".mat",
    ".xml",
    ".tsv"
}


def main():

    print()
    print("Searching for possible clinical label files...")
    print()

    results = []

    for path in ROOT.rglob("*"):

        if not path.is_file():
            continue

        name_lower = path.name.lower()

        keyword_matches = [
            keyword
            for keyword in KEYWORDS
            if keyword in name_lower
        ]

        extension_match = (
            path.suffix.lower()
            in INTERESTING_EXTENSIONS
        )

        if keyword_matches or extension_match:

            results.append({
                "filename": path.name,
                "extension": path.suffix.lower(),
                "matched_keywords": " | ".join(
                    keyword_matches
                ),
                "size_bytes": path.stat().st_size,
                "full_path": str(path)
            })

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=[
                "filename",
                "extension",
                "matched_keywords",
                "size_bytes",
                "full_path"
            ]
        )

        writer.writeheader()
        writer.writerows(results)

    print(
        f"Possible files found: {len(results)}"
    )

    print()
    print("Report:")
    print(OUTPUT)


if __name__ == "__main__":
    main()