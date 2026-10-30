from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

import matplotlib.pyplot as plt

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from torchvision import transforms
from torchvision.models import efficientnet_b0

from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
    auc
)

from sklearn.preprocessing import label_binarize


# ==========================================================
# PATHS
# ==========================================================

TEST_CSV = Path(
    r"E:\Eye Project\CataTriage_AI\data_splits"
    r"\retina_four_class\test.csv"
)

MODEL_FILE = Path(
    r"E:\Eye Project\CataTriage_AI\models"
    r"\retina_four_class\efficientnet_b0_v3"
    r"\best_macro_f1_model.pth"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation"
    r"\retina_four_class\v3_final_test"
)


# ==========================================================
# SETTINGS
# ==========================================================

IMAGE_SIZE = 224

BATCH_SIZE = 8

NUM_WORKERS = 0


CLASS_NAMES = [
    "cataract",
    "glaucoma",
    "normal",
    "retinal_disease"
]


CLASS_TO_INDEX = {
    class_name: index
    for index, class_name in enumerate(
        CLASS_NAMES
    )
}


# ==========================================================
# DEVICE
# ==========================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)


# ==========================================================
# TEST TRANSFORM
#
# IMPORTANT:
# NO random augmentation is allowed here.
# ==========================================================

test_transform = transforms.Compose([

    transforms.Resize(
        (IMAGE_SIZE, IMAGE_SIZE)
    ),

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[
            0.485,
            0.456,
            0.406
        ],
        std=[
            0.229,
            0.224,
            0.225
        ]
    )
])


# ==========================================================
# DATASET
# ==========================================================

class RetinaDataset(Dataset):

    def __init__(
        self,
        csv_file,
        transform=None
    ):

        self.df = pd.read_csv(
            csv_file
        )

        self.transform = transform


    def __len__(self):

        return len(
            self.df
        )


    def __getitem__(
        self,
        index
    ):

        row = self.df.iloc[
            index
        ]

        image_path = Path(
            row["full_path"]
        )

        label_name = str(
            row["label"]
        )

        label = CLASS_TO_INDEX[
            label_name
        ]


        with Image.open(
            image_path
        ) as image:

            image = image.convert(
                "RGB"
            )

            if self.transform:

                image = self.transform(
                    image
                )


        return (
            image,
            label,
            str(image_path)
        )


# ==========================================================
# LOAD CHECKPOINT ROBUSTLY
# ==========================================================

def load_checkpoint_state(
    checkpoint
):

    # Common checkpoint style:
    #
    # {
    #   "model_state_dict": ...
    # }

    if isinstance(
        checkpoint,
        dict
    ):

        if "model_state_dict" in checkpoint:

            return checkpoint[
                "model_state_dict"
            ]

        if "state_dict" in checkpoint:

            return checkpoint[
                "state_dict"
            ]


        # Check if the dictionary itself
        # looks like a PyTorch state_dict.

        tensor_values = [

            isinstance(
                value,
                torch.Tensor
            )

            for value in checkpoint.values()
        ]


        if (
            len(tensor_values) > 0
            and all(tensor_values)
        ):

            return checkpoint


    raise RuntimeError(
        "Could not identify model weights "
        "inside the checkpoint."
    )


# ==========================================================
# LOAD MODEL
# ==========================================================

def load_model():

    print(
        "Loading best V3 Macro-F1 checkpoint..."
    )


    checkpoint = torch.load(
        MODEL_FILE,
        map_location=device,
        weights_only=True
    )


    model = efficientnet_b0(
        weights=None
    )


    in_features = (
        model.classifier[1]
        .in_features
    )


    model.classifier[1] = nn.Linear(
        in_features,
        len(CLASS_NAMES)
    )


    state_dict = load_checkpoint_state(
        checkpoint
    )


    model.load_state_dict(
        state_dict
    )


    model = model.to(
        device
    )

    model.eval()


    return (
        model,
        checkpoint
    )


# ==========================================================
# RUN TEST INFERENCE
# ==========================================================

@torch.no_grad()
def run_inference(
    model,
    loader
):

    all_true = []

    all_pred = []

    all_probabilities = []

    all_paths = []


    for images, labels, paths in loader:

        images = images.to(
            device,
            non_blocking=True
        )

        labels = labels.to(
            device,
            non_blocking=True
        )


        with torch.autocast(
            device_type="cuda",
            dtype=torch.float16,
            enabled=(
                device.type == "cuda"
            )
        ):

            outputs = model(
                images
            )


        probabilities = torch.softmax(
            outputs,
            dim=1
        )


        predictions = torch.argmax(
            probabilities,
            dim=1
        )


        all_true.extend(
            labels.cpu().numpy()
        )

        all_pred.extend(
            predictions.cpu().numpy()
        )

        all_probabilities.extend(
            probabilities.cpu().numpy()
        )

        all_paths.extend(
            paths
        )


    return (
        np.array(all_true),
        np.array(all_pred),
        np.array(all_probabilities),
        all_paths
    )


# ==========================================================
# CONFUSION MATRIX GRAPH
# ==========================================================

def plot_confusion_matrix(
    matrix,
    filename,
    title,
    normalized=False
):

    plt.figure(
        figsize=(8, 7)
    )


    plt.imshow(
        matrix
    )


    plt.colorbar()


    plt.xticks(
        range(
            len(CLASS_NAMES)
        ),
        CLASS_NAMES,
        rotation=30,
        ha="right"
    )


    plt.yticks(
        range(
            len(CLASS_NAMES)
        ),
        CLASS_NAMES
    )


    plt.xlabel(
        "Predicted Class"
    )

    plt.ylabel(
        "True Class"
    )

    plt.title(
        title
    )


    for row in range(
        len(CLASS_NAMES)
    ):

        for column in range(
            len(CLASS_NAMES)
        ):

            value = matrix[
                row,
                column
            ]


            if normalized:

                text = (
                    f"{value:.2f}"
                )

            else:

                text = (
                    str(
                        int(value)
                    )
                )


            plt.text(
                column,
                row,
                text,
                ha="center",
                va="center"
            )


    plt.tight_layout()


    plt.savefig(
        OUTPUT_DIR / filename,
        dpi=300,
        bbox_inches="tight"
    )


    plt.close()


# ==========================================================
# PER-CLASS METRICS GRAPH
# ==========================================================

def plot_per_class_metrics(
    precision,
    recall,
    f1
):

    x = np.arange(
        len(CLASS_NAMES)
    )

    width = 0.25


    plt.figure(
        figsize=(10, 6)
    )


    plt.bar(
        x - width,
        precision,
        width,
        label="Precision"
    )


    plt.bar(
        x,
        recall,
        width,
        label="Recall"
    )


    plt.bar(
        x + width,
        f1,
        width,
        label="F1-score"
    )


    plt.xticks(
        x,
        CLASS_NAMES,
        rotation=25,
        ha="right"
    )


    plt.ylim(
        0,
        1
    )


    plt.ylabel(
        "Score"
    )

    plt.xlabel(
        "Class"
    )


    plt.title(
        "Final Test Performance by Class"
    )


    plt.legend()


    plt.grid(
        axis="y",
        alpha=0.25
    )


    plt.tight_layout()


    plt.savefig(
        OUTPUT_DIR
        / "per_class_metrics.png",
        dpi=300,
        bbox_inches="tight"
    )


    plt.close()


# ==========================================================
# ROC CURVES
# ==========================================================

def plot_roc_curves(
    y_true,
    probabilities
):

    y_binary = label_binarize(
        y_true,
        classes=list(
            range(
                len(CLASS_NAMES)
            )
        )
    )


    plt.figure(
        figsize=(8, 7)
    )


    for class_index, class_name in enumerate(
        CLASS_NAMES
    ):

        fpr, tpr, _ = roc_curve(

            y_binary[
                :,
                class_index
            ],

            probabilities[
                :,
                class_index
            ]
        )


        class_auc = auc(
            fpr,
            tpr
        )


        plt.plot(
            fpr,
            tpr,
            label=(
                f"{class_name} "
                f"(AUC={class_auc:.3f})"
            )
        )


    plt.plot(
        [0, 1],
        [0, 1],
        linestyle="--",
        label="Chance"
    )


    plt.xlabel(
        "False Positive Rate"
    )

    plt.ylabel(
        "True Positive Rate"
    )


    plt.title(
        "Final Test ROC Curves"
    )


    plt.legend(
        loc="lower right"
    )


    plt.grid(
        alpha=0.25
    )


    plt.tight_layout()


    plt.savefig(
        OUTPUT_DIR
        / "roc_curves.png",
        dpi=300,
        bbox_inches="tight"
    )


    plt.close()


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print(
        "CataTriage-AI — V3 Final Test"
    )

    print(
        "=============================="
    )

    print()


    # ------------------------------------------------------
    # CHECK FILES
    # ------------------------------------------------------

    if not TEST_CSV.exists():

        print(
            "ERROR:"
        )

        print(
            "test.csv not found:"
        )

        print(
            TEST_CSV
        )

        return


    if not MODEL_FILE.exists():

        print(
            "ERROR:"
        )

        print(
            "best_macro_f1_model.pth "
            "not found:"
        )

        print(
            MODEL_FILE
        )

        return


    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    # ------------------------------------------------------
    # DEVICE
    # ------------------------------------------------------

    print(
        f"Device: {device}"
    )


    if device.type == "cuda":

        print(
            "GPU:",
            torch.cuda.get_device_name(
                0
            )
        )


    print()


    # ------------------------------------------------------
    # TEST DATA
    # ------------------------------------------------------

    test_dataframe = pd.read_csv(
        TEST_CSV
    )


    print(
        "Test images:",
        len(test_dataframe)
    )


    print()


    print(
        "Test class counts:"
    )


    print(
        test_dataframe[
            "label"
        ].value_counts()
    )


    print()


    test_dataset = RetinaDataset(
        TEST_CSV,
        transform=test_transform
    )


    test_loader = DataLoader(

        test_dataset,

        batch_size=BATCH_SIZE,

        shuffle=False,

        num_workers=NUM_WORKERS,

        pin_memory=(
            device.type
            == "cuda"
        )
    )


    # ------------------------------------------------------
    # LOAD MODEL
    # ------------------------------------------------------

    model, checkpoint = load_model()


    # ------------------------------------------------------
    # SHOW CHECKPOINT METADATA
    # ------------------------------------------------------

    if isinstance(
        checkpoint,
        dict
    ):

        print()
        print(
            "Checkpoint information:"
        )


        for key in [
            "epoch",
            "val_accuracy",
            "val_macro_f1",
            "best_val_accuracy",
            "best_macro_f1"
        ]:

            if key in checkpoint:

                print(
                    f"{key}: "
                    f"{checkpoint[key]}"
                )


    print()


    # ------------------------------------------------------
    # TEST
    # ------------------------------------------------------

    print(
        "Running inference on the "
        "untouched test set..."
    )


    (
        y_true,
        y_pred,
        probabilities,
        image_paths
    ) = run_inference(
        model,
        test_loader
    )


    # ------------------------------------------------------
    # OVERALL METRICS
    # ------------------------------------------------------

    accuracy = accuracy_score(
        y_true,
        y_pred
    )


    balanced_accuracy = (
        balanced_accuracy_score(
            y_true,
            y_pred
        )
    )


    (
        precision,
        recall,
        f1,
        support
    ) = precision_recall_fscore_support(

        y_true,
        y_pred,

        labels=list(
            range(
                len(CLASS_NAMES)
            )
        ),

        zero_division=0
    )


    macro_precision = np.mean(
        precision
    )

    macro_recall = np.mean(
        recall
    )

    macro_f1 = np.mean(
        f1
    )


    (
        weighted_precision,
        weighted_recall,
        weighted_f1,
        _
    ) = precision_recall_fscore_support(

        y_true,
        y_pred,

        average="weighted",

        zero_division=0
    )


    # ------------------------------------------------------
    # ROC-AUC
    # ------------------------------------------------------

    y_binary = label_binarize(
        y_true,
        classes=list(
            range(
                len(CLASS_NAMES)
            )
        )
    )


    macro_roc_auc = roc_auc_score(

        y_binary,

        probabilities,

        average="macro",

        multi_class="ovr"
    )


    # ------------------------------------------------------
    # RESULTS
    # ------------------------------------------------------

    print()
    print(
        "=============================="
    )

    print(
        "FINAL TEST RESULTS"
    )

    print(
        "=============================="
    )

    print()


    print(
        f"Accuracy: "
        f"{accuracy * 100:.2f}%"
    )


    print(
        f"Balanced Accuracy: "
        f"{balanced_accuracy * 100:.2f}%"
    )


    print(
        f"Macro Precision: "
        f"{macro_precision:.4f}"
    )


    print(
        f"Macro Recall: "
        f"{macro_recall:.4f}"
    )


    print(
        f"Macro F1: "
        f"{macro_f1:.4f}"
    )


    print(
        f"Weighted F1: "
        f"{weighted_f1:.4f}"
    )


    print(
        f"Macro ROC-AUC: "
        f"{macro_roc_auc:.4f}"
    )


    # ------------------------------------------------------
    # CLASSIFICATION REPORT
    # ------------------------------------------------------

    report_text = classification_report(

        y_true,
        y_pred,

        target_names=CLASS_NAMES,

        digits=4,

        zero_division=0
    )


    print()
    print(
        report_text
    )


    with open(
        OUTPUT_DIR
        / "classification_report.txt",
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            report_text
        )


    report_dict = classification_report(

        y_true,
        y_pred,

        target_names=CLASS_NAMES,

        output_dict=True,

        zero_division=0
    )


    pd.DataFrame(
        report_dict
    ).transpose().to_csv(

        OUTPUT_DIR
        / "classification_report.csv"
    )


    # ------------------------------------------------------
    # CONFUSION MATRIX
    # ------------------------------------------------------

    cm = confusion_matrix(

        y_true,
        y_pred,

        labels=list(
            range(
                len(CLASS_NAMES)
            )
        )
    )


    pd.DataFrame(

        cm,

        index=CLASS_NAMES,

        columns=CLASS_NAMES

    ).to_csv(

        OUTPUT_DIR
        / "confusion_matrix.csv"
    )


    plot_confusion_matrix(

        cm,

        "confusion_matrix.png",

        "Final Test Confusion Matrix"
    )


    # ------------------------------------------------------
    # NORMALIZED CONFUSION MATRIX
    # ------------------------------------------------------

    row_totals = cm.sum(
        axis=1,
        keepdims=True
    )


    normalized_cm = np.divide(

        cm,

        row_totals,

        out=np.zeros_like(
            cm,
            dtype=float
        ),

        where=(
            row_totals != 0
        )
    )


    plot_confusion_matrix(

        normalized_cm,

        "normalized_confusion_matrix.png",

        "Normalized Final Test Confusion Matrix",

        normalized=True
    )


    # ------------------------------------------------------
    # PER-CLASS METRICS
    # ------------------------------------------------------

    per_class_df = pd.DataFrame({

        "class":
            CLASS_NAMES,

        "precision":
            precision,

        "recall":
            recall,

        "f1":
            f1,

        "support":
            support
    })


    per_class_df.to_csv(

        OUTPUT_DIR
        / "per_class_metrics.csv",

        index=False
    )


    plot_per_class_metrics(
        precision,
        recall,
        f1
    )


    # ------------------------------------------------------
    # ROC
    # ------------------------------------------------------

    plot_roc_curves(
        y_true,
        probabilities
    )


    # ------------------------------------------------------
    # SAVE INDIVIDUAL PREDICTIONS
    # ------------------------------------------------------

    prediction_rows = []


    for index in range(
        len(y_true)
    ):

        true_index = int(
            y_true[index]
        )

        predicted_index = int(
            y_pred[index]
        )


        row = {

            "image_path":
                image_paths[index],

            "true_label":
                CLASS_NAMES[
                    true_index
                ],

            "predicted_label":
                CLASS_NAMES[
                    predicted_index
                ],

            "correct":
                (
                    true_index
                    == predicted_index
                ),

            "prediction_confidence":
                float(
                    probabilities[
                        index,
                        predicted_index
                    ]
                )
        }


        for class_index, class_name in enumerate(
            CLASS_NAMES
        ):

            row[
                f"prob_{class_name}"
            ] = float(
                probabilities[
                    index,
                    class_index
                ]
            )


        prediction_rows.append(
            row
        )


    predictions_df = pd.DataFrame(
        prediction_rows
    )


    predictions_df.to_csv(

        OUTPUT_DIR
        / "test_predictions.csv",

        index=False
    )


    # ------------------------------------------------------
    # SAVE MISCLASSIFICATIONS
    # ------------------------------------------------------

    mistakes = predictions_df[
        predictions_df[
            "correct"
        ] == False
    ].copy()


    mistakes = mistakes.sort_values(
        "prediction_confidence",
        ascending=False
    )


    mistakes.to_csv(

        OUTPUT_DIR
        / "misclassified_images.csv",

        index=False
    )


    # ------------------------------------------------------
    # FINAL SUMMARY
    # ------------------------------------------------------

    correct_count = int(
        (
            y_true
            == y_pred
        ).sum()
    )


    incorrect_count = int(
        (
            y_true
            != y_pred
        ).sum()
    )


    summary = f"""
CataTriage-AI Retina Four-Class V3 Final Test
==============================================

MODEL
EfficientNet-B0 V3

CHECKPOINT
best_macro_f1_model.pth

TEST IMAGES
{len(y_true)}

CORRECT PREDICTIONS
{correct_count}

INCORRECT PREDICTIONS
{incorrect_count}

TEST ACCURACY
{accuracy:.6f}

BALANCED ACCURACY
{balanced_accuracy:.6f}

MACRO PRECISION
{macro_precision:.6f}

MACRO RECALL
{macro_recall:.6f}

MACRO F1
{macro_f1:.6f}

WEIGHTED PRECISION
{weighted_precision:.6f}

WEIGHTED RECALL
{weighted_recall:.6f}

WEIGHTED F1
{weighted_f1:.6f}

MACRO ROC-AUC
{macro_roc_auc:.6f}


IMPORTANT LIMITATIONS
=====================

This is a development baseline.

The complete retina dataset contains
601 unique images.

The final test set contains
91 images.

Reliable patient IDs were unavailable,
so this evaluation uses an image-level
split rather than a patient-level split.

The images are fundus/retina images.

This is NOT the final slit-lamp cataract
severity model.

These results are not clinical validation
and should not be interpreted as
deployment readiness.
""".strip()


    with open(
        OUTPUT_DIR
        / "final_test_summary.txt",
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            summary
        )


    print()
    print(
        summary
    )


    print()
    print(
        "=============================="
    )

    print(
        "STEP 8E COMPLETE"
    )

    print(
        "=============================="
    )


    print()
    print(
        "Results saved to:"
    )

    print(
        OUTPUT_DIR
    )


if __name__ == "__main__":
    main()