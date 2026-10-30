from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageOps


# ==========================================================
# PATHS
# ==========================================================

REPORT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality\image_quality_report.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality\review_sheets"
)


# ==========================================================
# SETTINGS
# ==========================================================

THUMB_W = 220
THUMB_H = 165

LABEL_H = 85

COLS = 4
ROWS = 5

IMAGES_PER_SHEET = COLS * ROWS


# ==========================================================
# IDENTIFY SUB-DATASET
# ==========================================================

def identify_dataset(path):

    path_lower = str(path).lower()

    if "nuclear cataract dataset" in path_lower:
        return "Nuclear_Cataract"

    if "ophthalmic_slit_lamp_60" in path_lower:
        return "Temporal_Slit_Lamp"

    if "binary_cataract_unknown_source" in path_lower:
        return "Binary_Cataract"

    if "retina_four_class" in path_lower:
        return "Retina_Four_Class"

    if "sustech_sysu" in path_lower:
        return "SUSTech_Mask"

    return "Other"


# ==========================================================
# LOAD IMAGE SAFELY
# ==========================================================

def load_thumbnail(file_path):

    try:

        with Image.open(file_path) as img:

            img = img.convert("RGB")

            img.thumbnail(
                (THUMB_W, THUMB_H)
            )

            canvas = Image.new(
                "RGB",
                (THUMB_W, THUMB_H),
                "white"
            )

            x = (
                THUMB_W - img.width
            ) // 2

            y = (
                THUMB_H - img.height
            ) // 2

            canvas.paste(
                img,
                (x, y)
            )

            return canvas

    except Exception:

        canvas = Image.new(
            "RGB",
            (THUMB_W, THUMB_H),
            "white"
        )

        draw = ImageDraw.Draw(canvas)

        draw.text(
            (10, 70),
            "IMAGE LOAD ERROR",
            fill="black"
        )

        return canvas


# ==========================================================
# CREATE ONE CONTACT SHEET
# ==========================================================

def make_sheet(rows, title, output_file):

    if len(rows) == 0:
        return

    cell_w = THUMB_W
    cell_h = THUMB_H + LABEL_H

    title_h = 70

    sheet_w = COLS * cell_w

    sheet_h = (
        title_h
        + ROWS * cell_h
    )

    sheet = Image.new(
        "RGB",
        (sheet_w, sheet_h),
        "white"
    )

    draw = ImageDraw.Draw(sheet)

    draw.text(
        (15, 15),
        title,
        fill="black"
    )

    for index, (_, row) in enumerate(
        rows.head(IMAGES_PER_SHEET).iterrows()
    ):

        col = index % COLS

        row_pos = index // COLS

        x = col * cell_w

        y = title_h + row_pos * cell_h

        thumb = load_thumbnail(
            row["full_path"]
        )

        sheet.paste(
            thumb,
            (x, y)
        )

        label_y = y + THUMB_H + 4

        filename = str(
            row["filename"]
        )[:28]

        dataset = str(
            row["subdataset"]
        )[:22]

        brightness = row.get(
            "mean_brightness",
            ""
        )

        blur = row.get(
            "blur_variance",
            ""
        )

        width = row.get(
            "width",
            ""
        )

        height = row.get(
            "height",
            ""
        )

        text = (
            f"{filename}\n"
            f"{dataset}\n"
            f"B={brightness}  Blur={blur}\n"
            f"{width}x{height}"
        )

        draw.multiline_text(
            (x + 5, label_y),
            text,
            fill="black",
            spacing=2
        )

    sheet.save(
        output_file,
        quality=92
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Quality Review Sheet Builder")
    print("============================================")
    print()

    if not REPORT_FILE.exists():

        print("ERROR:")
        print("Quality report not found:")
        print(REPORT_FILE)

        return

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    df = pd.read_csv(
        REPORT_FILE
    )

    df["subdataset"] = df[
        "full_path"
    ].apply(
        identify_dataset
    )

    # Clinical / candidate images only
    clinical = df[
        df["data_role"] != "SUPPORTING_MASK"
    ].copy()

    review = clinical[
        clinical["quality_flag"] == "REVIEW"
    ].copy()

    print(
        f"Review images found: {len(review)}"
    )

    # ------------------------------------------------------
    # 1. DARKEST IMAGES
    # ------------------------------------------------------

    darkest = review.sort_values(
        "mean_brightness",
        ascending=True
    )

    make_sheet(
        darkest,
        "20 Darkest Flagged Images",
        OUTPUT_DIR / "01_darkest_images.jpg"
    )

    # ------------------------------------------------------
    # 2. LOWEST BLUR VARIANCE
    # ------------------------------------------------------

    blur = review.sort_values(
        "blur_variance",
        ascending=True
    )

    make_sheet(
        blur,
        "20 Lowest Blur-Variance Images",
        OUTPUT_DIR / "02_lowest_blur_variance.jpg"
    )

    # ------------------------------------------------------
    # 3. SMALLEST IMAGES
    # ------------------------------------------------------

    review["smallest_dimension"] = review[
        ["width", "height"]
    ].min(axis=1)

    smallest = review.sort_values(
        "smallest_dimension",
        ascending=True
    )

    make_sheet(
        smallest,
        "20 Smallest Flagged Images",
        OUTPUT_DIR / "03_smallest_images.jpg"
    )

    # ------------------------------------------------------
    # 4. NUCLEAR CATARACT REVIEW SAMPLE
    # ------------------------------------------------------

    nuclear = review[
        review["subdataset"]
        == "Nuclear_Cataract"
    ]

    make_sheet(
        nuclear,
        "Nuclear Cataract - Flagged Sample",
        OUTPUT_DIR / "04_nuclear_flagged_sample.jpg"
    )

    # ------------------------------------------------------
    # 5. RETINA REVIEW SAMPLE
    # ------------------------------------------------------

    retina = review[
        review["subdataset"]
        == "Retina_Four_Class"
    ]

    make_sheet(
        retina,
        "Retina Four-Class - Flagged Sample",
        OUTPUT_DIR / "05_retina_flagged_sample.jpg"
    )

    # ------------------------------------------------------
    # 6. BINARY CATARACT REVIEW SAMPLE
    # ------------------------------------------------------

    binary = review[
        review["subdataset"]
        == "Binary_Cataract"
    ]

    make_sheet(
        binary,
        "Binary Cataract - Flagged Sample",
        OUTPUT_DIR / "06_binary_flagged_sample.jpg"
    )

    # ------------------------------------------------------
    # 7. TEMPORAL SLIT-LAMP REVIEW SAMPLE
    # ------------------------------------------------------

    temporal = review[
        review["subdataset"]
        == "Temporal_Slit_Lamp"
    ]

    make_sheet(
        temporal,
        "Temporal Slit-Lamp - Flagged Sample",
        OUTPUT_DIR / "07_temporal_flagged_sample.jpg"
    )

    print()
    print("DONE")
    print()
    print("Review sheets created in:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()