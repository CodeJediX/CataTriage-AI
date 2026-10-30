from pathlib import Path
import csv
import cv2
import numpy as np
from collections import Counter


# ==========================================================
# PATHS
# ==========================================================

INPUT_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\data_raw\grouped_image_manifest.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation\image_quality"
)

REPORT_FILE = OUTPUT_DIR / "image_quality_report.csv"

SUMMARY_FILE = OUTPUT_DIR / "image_quality_summary.txt"


# ==========================================================
# BASIC IMAGE ANALYSIS
# ==========================================================

def analyze_image(file_path, data_role):

    result = {
        "decode_status": "FAIL",
        "width": "",
        "height": "",
        "channels": "",
        "mean_brightness": "",
        "contrast_std": "",
        "blur_variance": "",
        "dark_fraction": "",
        "bright_fraction": "",
        "quality_flag": "REVIEW",
        "quality_reasons": "",
    }

    reasons = []

    try:

        image = cv2.imread(
            str(file_path),
            cv2.IMREAD_UNCHANGED
        )

        if image is None:

            result["quality_reasons"] = (
                "IMAGE_COULD_NOT_BE_DECODED"
            )

            return result

        result["decode_status"] = "PASS"

        # ----------------------------------------------
        # DIMENSIONS
        # ----------------------------------------------

        height, width = image.shape[:2]

        result["width"] = width
        result["height"] = height

        if len(image.shape) == 2:
            channels = 1

        else:
            channels = image.shape[2]

        result["channels"] = channels

        # ----------------------------------------------
        # MASKS
        # ----------------------------------------------

        if data_role == "SUPPORTING_MASK":

            result["quality_flag"] = "MASK_OK"
            result["quality_reasons"] = (
                "SUPPORTING_MASK_NOT_CLINICAL_INPUT"
            )

            return result

        # ----------------------------------------------
        # CONVERT TO GRAYSCALE FOR METRICS
        # ----------------------------------------------

        if len(image.shape) == 2:

            gray = image

        elif channels == 4:

            gray = cv2.cvtColor(
                image,
                cv2.COLOR_BGRA2GRAY
            )

        else:

            gray = cv2.cvtColor(
                image,
                cv2.COLOR_BGR2GRAY
            )

        # Ensure uint8 for comparable metrics

        if gray.dtype != np.uint8:

            gray_float = gray.astype(
                np.float32
            )

            min_value = gray_float.min()
            max_value = gray_float.max()

            if max_value > min_value:

                gray = (
                    (gray_float - min_value)
                    /
                    (max_value - min_value)
                    * 255
                ).astype(np.uint8)

            else:

                gray = np.zeros_like(
                    gray_float,
                    dtype=np.uint8
                )

        # ----------------------------------------------
        # BRIGHTNESS
        # ----------------------------------------------

        mean_brightness = float(
            np.mean(gray)
        )

        result["mean_brightness"] = round(
            mean_brightness,
            2
        )

        # ----------------------------------------------
        # CONTRAST
        # ----------------------------------------------

        contrast = float(
            np.std(gray)
        )

        result["contrast_std"] = round(
            contrast,
            2
        )

        # ----------------------------------------------
        # BLUR
        # ----------------------------------------------

        blur_variance = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F
            ).var()
        )

        result["blur_variance"] = round(
            blur_variance,
            2
        )

        # ----------------------------------------------
        # DARK / BRIGHT FRACTIONS
        # ----------------------------------------------

        dark_fraction = float(
            np.mean(gray < 15)
        )

        bright_fraction = float(
            np.mean(gray > 240)
        )

        result["dark_fraction"] = round(
            dark_fraction,
            4
        )

        result["bright_fraction"] = round(
            bright_fraction,
            4
        )

        # ----------------------------------------------
        # CONSERVATIVE REVIEW FLAGS
        #
        # IMPORTANT:
        # These do NOT automatically reject medical images.
        # They only tell us which ones deserve inspection.
        # ----------------------------------------------

        if width < 128 or height < 128:

            reasons.append(
                "VERY_SMALL_IMAGE"
            )

        if mean_brightness < 20:

            reasons.append(
                "EXTREMELY_DARK"
            )

        if mean_brightness > 235:

            reasons.append(
                "EXTREMELY_BRIGHT"
            )

        if contrast < 8:

            reasons.append(
                "VERY_LOW_CONTRAST"
            )

        if blur_variance < 10:

            reasons.append(
                "POSSIBLE_EXTREME_BLUR"
            )

        if dark_fraction > 0.90:

            reasons.append(
                "MOSTLY_DARK_PIXELS"
            )

        if bright_fraction > 0.90:

            reasons.append(
                "MOSTLY_BRIGHT_PIXELS"
            )

        # ----------------------------------------------
        # RESULT
        # ----------------------------------------------

        if len(reasons) == 0:

            result["quality_flag"] = "PASS_INITIAL"

            result["quality_reasons"] = ""

        else:

            result["quality_flag"] = "REVIEW"

            result["quality_reasons"] = "|".join(
                reasons
            )

        return result

    except Exception as error:

        result["quality_reasons"] = (
            f"ERROR:{type(error).__name__}"
        )

        return result


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("CataTriage-AI — Image Quality Validation")
    print("========================================")
    print()

    if not INPUT_FILE.exists():

        print("ERROR:")
        print("Grouped manifest not found:")
        print(INPUT_FILE)

        return

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    rows_out = []

    counters = Counter()

    # ------------------------------------------------------
    # LOAD MANIFEST
    # ------------------------------------------------------

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        rows = list(reader)

    total = len(rows)

    print(
        f"Images to validate: {total}"
    )

    print()

    # ------------------------------------------------------
    # ANALYZE
    # ------------------------------------------------------

    for index, row in enumerate(
        rows,
        start=1
    ):

        file_path = Path(
            row["full_path"]
        )

        data_role = row["data_role"]

        metrics = analyze_image(
            file_path,
            data_role
        )

        output_row = dict(row)
        output_row.update(metrics)

        rows_out.append(output_row)

        counters[
            metrics["decode_status"]
        ] += 1

        counters[
            metrics["quality_flag"]
        ] += 1

        if index % 100 == 0:

            print(
                f"Checked {index}/{total}"
            )

    # ------------------------------------------------------
    # WRITE REPORT
    # ------------------------------------------------------

    extra_fields = [
        "decode_status",
        "width",
        "height",
        "channels",
        "mean_brightness",
        "contrast_std",
        "blur_variance",
        "dark_fraction",
        "bright_fraction",
        "quality_flag",
        "quality_reasons",
    ]

    fieldnames = list(
        rows_out[0].keys()
    )

    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(rows_out)

    # ------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------

    summary = f"""
CataTriage-AI Image Quality Validation
======================================

TOTAL IMAGES CHECKED
{total}

DECODE PASS
{counters['PASS']}

DECODE FAIL
{counters['FAIL']}

PASS_INITIAL
{counters['PASS_INITIAL']}

REVIEW
{counters['REVIEW']}

SUPPORTING MASKS
{counters['MASK_OK']}


IMPORTANT
=========

PASS_INITIAL does NOT mean clinically approved.

REVIEW does NOT mean the image is unusable.

The thresholds in this first audit are conservative
engineering flags only.

No images were deleted.

No images were moved.

No images were resized.

No images were normalized.

Supporting masks were not treated as normal
clinical Model-1 inputs.

Images marked REVIEW must be inspected before
any quality-based exclusion decision.
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
    print("----------------------------------------")
    print("IMAGE VALIDATION COMPLETE")
    print("----------------------------------------")

    print()
    print("Detailed report:")
    print(REPORT_FILE)

    print()
    print("Summary:")
    print(SUMMARY_FILE)


if __name__ == "__main__":
    main()