from pathlib import Path
import pandas as pd
from PIL import Image, ImageOps
import hashlib


# ==========================================================
# PATHS
# ==========================================================

MANIFEST_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\final_quality_manifest.csv"
)

OUTPUT_ROOT = Path(
    r"E:\Eye Project\CataTriage_AI\data_processed\model1_slit_lamp_384"
)

OUTPUT_MANIFEST = Path(
    r"E:\Eye Project\CataTriage_AI\data_processed\model1_slit_lamp_384_manifest.csv"
)

SUMMARY_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality\standardization_summary.txt"
)


# ==========================================================
# SETTINGS
# ==========================================================

TARGET_SIZE = 384

BACKGROUND_COLOR = (0, 0, 0)


# ==========================================================
# HASH FUNCTION
# ==========================================================

def sha256_file(file_path):

    hasher = hashlib.sha256()

    with open(file_path, "rb") as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            hasher.update(chunk)

    return hasher.hexdigest()


# ==========================================================
# STANDARDIZE ONE IMAGE
# ==========================================================

def standardize_image(
    source_path,
    destination_path
):

    with Image.open(source_path) as image:

        # Apply EXIF rotation if present
        image = ImageOps.exif_transpose(
            image
        )

        # Convert to RGB
        image = image.convert("RGB")

        original_width = image.width
        original_height = image.height

        # ----------------------------------------------
        # PRESERVE ASPECT RATIO
        # ----------------------------------------------

        scale = min(
            TARGET_SIZE / original_width,
            TARGET_SIZE / original_height
        )

        new_width = max(
            1,
            round(original_width * scale)
        )

        new_height = max(
            1,
            round(original_height * scale)
        )

        resized = image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS
        )

        # ----------------------------------------------
        # CREATE 384 x 384 CANVAS
        # ----------------------------------------------

        canvas = Image.new(
            "RGB",
            (TARGET_SIZE, TARGET_SIZE),
            BACKGROUND_COLOR
        )

        left = (
            TARGET_SIZE - new_width
        ) // 2

        top = (
            TARGET_SIZE - new_height
        ) // 2

        canvas.paste(
            resized,
            (left, top)
        )

        right_padding = (
            TARGET_SIZE
            - new_width
            - left
        )

        bottom_padding = (
            TARGET_SIZE
            - new_height
            - top
        )

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # Lossless output
        canvas.save(
            destination_path,
            format="PNG",
            optimize=True
        )

        return {
            "original_width": original_width,
            "original_height": original_height,

            "resized_width": new_width,
            "resized_height": new_height,

            "pad_left": left,
            "pad_top": top,
            "pad_right": right_padding,
            "pad_bottom": bottom_padding,

            "scale_factor": round(
                scale,
                6
            )
        }


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Model 1 Image Standardization")
    print("=============================================")
    print()

    if not MANIFEST_FILE.exists():

        print("ERROR:")
        print("Final quality manifest not found:")
        print(MANIFEST_FILE)

        return

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    df = pd.read_csv(
        MANIFEST_FILE
    )

    # ------------------------------------------------------
    # ONLY PRIMARY MODEL 1 CANDIDATES
    # ------------------------------------------------------

    model1 = df[
        df["primary_model1_status"]
        == "PRIMARY_CANDIDATE"
    ].copy()

    print(
        f"Primary Model 1 images found: {len(model1)}"
    )

    print()

    output_rows = []

    success = 0
    failure = 0

    for index, (_, row) in enumerate(
        model1.iterrows(),
        start=1
    ):

        source_path = Path(
            row["full_path"]
        )

        group_id = str(
            row["group_id"]
        )

        # ----------------------------------------------
        # SAFE UNIQUE OUTPUT NAME
        # ----------------------------------------------

        output_name = (
            f"{row['registry_id']}.png"
        )

        destination_path = (
            OUTPUT_ROOT
            / group_id
            / output_name
        )

        try:

            metrics = standardize_image(
                source_path,
                destination_path
            )

            processed_hash = sha256_file(
                destination_path
            )

            status = "SUCCESS"

            success += 1

        except Exception as error:

            metrics = {
                "original_width": "",
                "original_height": "",
                "resized_width": "",
                "resized_height": "",
                "pad_left": "",
                "pad_top": "",
                "pad_right": "",
                "pad_bottom": "",
                "scale_factor": "",
            }

            processed_hash = ""

            status = (
                f"ERROR:{type(error).__name__}"
            )

            failure += 1

        output_rows.append({

            "registry_id":
                row["registry_id"],

            "group_id":
                row["group_id"],

            "source_path":
                str(source_path),

            "processed_path":
                str(destination_path),

            "modality":
                row["modality"],

            "standardization_status":
                status,

            "processed_sha256":
                processed_hash,

            **metrics
        })

        if index % 100 == 0:

            print(
                f"Processed {index}/{len(model1)}"
            )

    # ------------------------------------------------------
    # WRITE MANIFEST
    # ------------------------------------------------------

    output_df = pd.DataFrame(
        output_rows
    )

    output_df.to_csv(
        OUTPUT_MANIFEST,
        index=False,
        encoding="utf-8-sig"
    )

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    summary = f"""
CataTriage-AI Model 1 Standardization
=====================================

TARGET SIZE
{TARGET_SIZE} x {TARGET_SIZE}

TOTAL PRIMARY MODEL 1 IMAGES
{len(model1)}

SUCCESSFULLY PROCESSED
{success}

FAILED
{failure}

OUTPUT FORMAT
PNG

COLOR MODE
RGB

RESIZE METHOD
Aspect-ratio preserved + black padding

ORIGINAL FILES MODIFIED
NO

ORIGINAL FILES DELETED
NO

ORIGINAL FILES MOVED
NO


IMPORTANT
=========

Only PRIMARY_CANDIDATE slit-lamp images were processed.

Retina/fundus images were not included.

Binary cataract images on HOLD were not included.

Supporting masks were not included.

No image augmentation was performed.

No brightness enhancement was performed.

No contrast enhancement was performed.

No clinical labels were changed.
""".strip()

    SUMMARY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(summary)

    print()
    print(summary)

    print()
    print("---------------------------------------------")
    print("STANDARDIZATION COMPLETE")
    print("---------------------------------------------")

    print()
    print("Processed images:")
    print(OUTPUT_ROOT)

    print()
    print("Manifest:")
    print(OUTPUT_MANIFEST)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()
