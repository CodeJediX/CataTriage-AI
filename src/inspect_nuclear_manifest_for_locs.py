from pathlib import Path
import csv
import json


DATASET_ROOT = Path(
    r"E:\Eye Project\data sets\Eye_Datasets_Organized"
    r"\01_multimodal_collections\catatriage_ai"
    r"\01_Slit_Lamp_Images\01_Cataract"
    r"\Mendeley_Nuclear_Cataract_Database"
)

OUTPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\labels"
    r"\nuclear_manifest_locs_search.txt"
)


SEARCH_TERMS = [
    "locs",
    "base de datos",
    "pacientes",
    "lleno",
    ".xlsx",
    ".xls"
]


def search_text_file(path):

    matches = []

    try:

        text = path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        for line_number, line in enumerate(
            text.splitlines(),
            start=1
        ):

            line_lower = line.lower()

            if any(
                term in line_lower
                for term in SEARCH_TERMS
            ):

                matches.append(
                    f"{path.name} | line {line_number} | {line}"
                )

    except Exception as error:

        matches.append(
            f"ERROR reading {path}: {error}"
        )

    return matches


def main():

    print()
    print("Searching Nuclear Cataract manifests...")
    print()

    results = []

    for path in DATASET_ROOT.rglob("*"):

        if not path.is_file():
            continue

        if path.suffix.lower() in {
            ".csv",
            ".json",
            ".txt"
        }:

            results.extend(
                search_text_file(path)
            )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "\n".join(results)
        )

    print(
        f"Matches found: {len(results)}"
    )

    print()
    print("Output:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()