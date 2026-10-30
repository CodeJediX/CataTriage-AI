from pathlib import Path
import random

import numpy as np
import pandas as pd
from PIL import Image

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

from torchvision import transforms
from torchvision.models import (
    efficientnet_b0,
    EfficientNet_B0_Weights
)


# ==========================================================
# PATHS
# ==========================================================

TRAIN_CSV = Path(
    r"E:\Eye Project\CataTriage_AI\data_splits"
    r"\retina_four_class\train.csv"
)

VAL_CSV = Path(
    r"E:\Eye Project\CataTriage_AI\data_splits"
    r"\retina_four_class\validation.csv"
)

OUTPUT_DIR = Path(
    r"E:\Eye Project\CataTriage_AI\evaluation"
    r"\retina_four_class\smoke_test"
)


# ==========================================================
# SETTINGS
# ==========================================================

SEED = 42

IMAGE_SIZE = 224

BATCH_SIZE = 8

NUM_WORKERS = 0

LEARNING_RATE = 1e-4

EPOCHS = 1


CLASS_NAMES = [
    "cataract",
    "glaucoma",
    "normal",
    "retinal_disease"
]

CLASS_TO_INDEX = {
    name: index
    for index, name in enumerate(CLASS_NAMES)
}


# ==========================================================
# REPRODUCIBILITY
# ==========================================================

def set_seed(seed):

    random.seed(seed)

    np.random.seed(seed)

    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


set_seed(SEED)


# ==========================================================
# DEVICE
# ==========================================================

device = torch.device(
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)


# ==========================================================
# TRANSFORMS
# ==========================================================

# Training-only augmentation
train_transform = transforms.Compose([

    transforms.Resize(
        (IMAGE_SIZE, IMAGE_SIZE)
    ),

    transforms.RandomHorizontalFlip(
        p=0.5
    ),

    transforms.RandomRotation(
        degrees=10
    ),

    transforms.ColorJitter(
        brightness=0.10,
        contrast=0.10
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


# Validation receives NO random augmentation
val_transform = transforms.Compose([

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
            label
        )


# ==========================================================
# CLASS WEIGHTS
# ==========================================================

def calculate_class_weights(
    train_dataframe
):

    counts = (
        train_dataframe["label"]
        .value_counts()
    )

    total = len(
        train_dataframe
    )

    number_of_classes = len(
        CLASS_NAMES
    )

    weights = []

    for class_name in CLASS_NAMES:

        class_count = counts[
            class_name
        ]

        weight = (
            total
            /
            (
                number_of_classes
                * class_count
            )
        )

        weights.append(
            weight
        )

    return torch.tensor(
        weights,
        dtype=torch.float32
    )


# ==========================================================
# TRAIN ONE EPOCH
# ==========================================================

def train_one_epoch(
    model,
    loader,
    criterion,
    optimizer,
    scaler
):

    model.train()

    running_loss = 0.0

    correct = 0

    total = 0


    for images, labels in loader:

        images = images.to(
            device,
            non_blocking=True
        )

        labels = labels.to(
            device,
            non_blocking=True
        )


        optimizer.zero_grad(
            set_to_none=True
        )


        # Mixed precision on NVIDIA GPU
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

            loss = criterion(
                outputs,
                labels
            )


        if device.type == "cuda":

            scaler.scale(
                loss
            ).backward()

            scaler.step(
                optimizer
            )

            scaler.update()

        else:

            loss.backward()

            optimizer.step()


        running_loss += (
            loss.item()
            * images.size(0)
        )


        predictions = outputs.argmax(
            dim=1
        )


        correct += (
            predictions
            == labels
        ).sum().item()


        total += labels.size(
            0
        )


    epoch_loss = (
        running_loss
        / total
    )

    epoch_accuracy = (
        correct
        / total
    )


    return (
        epoch_loss,
        epoch_accuracy
    )


# ==========================================================
# VALIDATION
# ==========================================================

@torch.no_grad()
def validate(
    model,
    loader,
    criterion
):

    model.eval()

    running_loss = 0.0

    correct = 0

    total = 0


    for images, labels in loader:

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

            loss = criterion(
                outputs,
                labels
            )


        running_loss += (
            loss.item()
            * images.size(0)
        )


        predictions = outputs.argmax(
            dim=1
        )


        correct += (
            predictions
            == labels
        ).sum().item()


        total += labels.size(
            0
        )


    epoch_loss = (
        running_loss
        / total
    )

    epoch_accuracy = (
        correct
        / total
    )


    return (
        epoch_loss,
        epoch_accuracy
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print(
        "CataTriage-AI — Retina GPU Smoke Test"
    )

    print(
        "====================================="
    )

    print()


    # ------------------------------------------------------
    # FILE CHECK
    # ------------------------------------------------------

    if not TRAIN_CSV.exists():

        print(
            "ERROR: train.csv not found"
        )

        return


    if not VAL_CSV.exists():

        print(
            "ERROR: validation.csv not found"
        )

        return


    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    # ------------------------------------------------------
    # GPU INFO
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

        print(
            "CUDA:",
            torch.version.cuda
        )

        gpu_memory = (
            torch.cuda.get_device_properties(
                0
            ).total_memory
            / 1024**3
        )

        print(
            f"GPU VRAM: {gpu_memory:.2f} GB"
        )

    print()


    # ------------------------------------------------------
    # LOAD DATA
    # ------------------------------------------------------

    train_df = pd.read_csv(
        TRAIN_CSV
    )

    val_df = pd.read_csv(
        VAL_CSV
    )


    print(
        f"Training images: {len(train_df)}"
    )

    print(
        f"Validation images: {len(val_df)}"
    )


    # ------------------------------------------------------
    # DATASETS
    # ------------------------------------------------------

    train_dataset = RetinaDataset(
        TRAIN_CSV,
        transform=train_transform
    )

    val_dataset = RetinaDataset(
        VAL_CSV,
        transform=val_transform
    )


    # ------------------------------------------------------
    # DATALOADERS
    # ------------------------------------------------------

    train_loader = DataLoader(

        train_dataset,

        batch_size=BATCH_SIZE,

        shuffle=True,

        num_workers=NUM_WORKERS,

        pin_memory=(
            device.type == "cuda"
        )
    )


    val_loader = DataLoader(

        val_dataset,

        batch_size=BATCH_SIZE,

        shuffle=False,

        num_workers=NUM_WORKERS,

        pin_memory=(
            device.type == "cuda"
        )
    )


    # ------------------------------------------------------
    # CLASS WEIGHTS
    # ------------------------------------------------------

    class_weights = (
        calculate_class_weights(
            train_df
        )
        .to(device)
    )


    print()
    print(
        "Class weights:"
    )


    for name, weight in zip(
        CLASS_NAMES,
        class_weights.tolist()
    ):

        print(
            f"  {name}: {weight:.4f}"
        )


    # ------------------------------------------------------
    # MODEL
    # ------------------------------------------------------

    print()
    print(
        "Loading EfficientNet-B0..."
    )


    weights = (
        EfficientNet_B0_Weights.DEFAULT
    )


    model = efficientnet_b0(
        weights=weights
    )


    # Replace final classifier
    in_features = (
        model.classifier[1]
        .in_features
    )


    model.classifier[1] = nn.Linear(
        in_features,
        len(CLASS_NAMES)
    )


    model = model.to(
        device
    )


    # ------------------------------------------------------
    # LOSS
    # ------------------------------------------------------

    criterion = nn.CrossEntropyLoss(
        weight=class_weights
    )


    # ------------------------------------------------------
    # OPTIMIZER
    # ------------------------------------------------------

    optimizer = torch.optim.AdamW(

        model.parameters(),

        lr=LEARNING_RATE,

        weight_decay=1e-4
    )


    # ------------------------------------------------------
    # AMP SCALER
    # ------------------------------------------------------

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=(
            device.type == "cuda"
        )
    )


    # ------------------------------------------------------
    # ONE-EPOCH TEST
    # ------------------------------------------------------

    print()
    print(
        "Starting 1-epoch GPU smoke test..."
    )

    print()


    train_loss, train_acc = (
        train_one_epoch(
            model,
            train_loader,
            criterion,
            optimizer,
            scaler
        )
    )


    val_loss, val_acc = validate(
        model,
        val_loader,
        criterion
    )


    # ------------------------------------------------------
    # RESULTS
    # ------------------------------------------------------

    print()
    print(
        "====================================="
    )

    print(
        "SMOKE TEST RESULTS"
    )

    print(
        "====================================="
    )


    print(
        f"Train Loss: {train_loss:.4f}"
    )

    print(
        f"Train Accuracy: "
        f"{train_acc * 100:.2f}%"
    )

    print(
        f"Validation Loss: "
        f"{val_loss:.4f}"
    )

    print(
        f"Validation Accuracy: "
        f"{val_acc * 100:.2f}%"
    )


    if device.type == "cuda":

        max_memory = (
            torch.cuda.max_memory_allocated()
            / 1024**3
        )

        print(
            f"Peak GPU memory: "
            f"{max_memory:.2f} GB"
        )


    # ------------------------------------------------------
    # SAVE SUMMARY
    # ------------------------------------------------------

    summary_file = (
        OUTPUT_DIR
        / "smoke_test_summary.txt"
    )


    with open(
        summary_file,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "CataTriage-AI Retina GPU Smoke Test\n"
        )

        file.write(
            "===================================\n\n"
        )

        file.write(
            f"Device: {device}\n"
        )

        if device.type == "cuda":

            file.write(
                "GPU: "
                f"{torch.cuda.get_device_name(0)}\n"
            )

        file.write(
            f"Train images: {len(train_df)}\n"
        )

        file.write(
            f"Validation images: {len(val_df)}\n"
        )

        file.write(
            f"Batch size: {BATCH_SIZE}\n"
        )

        file.write(
            f"Image size: "
            f"{IMAGE_SIZE}x{IMAGE_SIZE}\n\n"
        )

        file.write(
            f"Train loss: "
            f"{train_loss:.6f}\n"
        )

        file.write(
            f"Train accuracy: "
            f"{train_acc:.6f}\n"
        )

        file.write(
            f"Validation loss: "
            f"{val_loss:.6f}\n"
        )

        file.write(
            f"Validation accuracy: "
            f"{val_acc:.6f}\n"
        )


    print()
    print(
        "Smoke-test summary:"
    )

    print(
        summary_file
    )

    print()
    print(
        "STEP 8C COMPLETE"
    )


if __name__ == "__main__":
    main()