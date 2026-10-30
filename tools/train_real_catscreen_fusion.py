from __future__ import annotations

import json
import random
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageOps
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score, recall_score
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.getenv('CATATRIAGE_CATSCREEN_DIR',r"E:\Eye Project\data sets\CatScreen_Public_Sample"))
OUTPUT = ROOT / "models" / "clinical_fusion_catscreen_real"
CACHE_ROOT = Path(os.getenv('CATATRIAGE_CATSCREEN_CACHE',str(ROOT/'data_processed/catscreen_training_cache_512')))
SEED = 20261026
CLASS_NAMES = ["normal", "cataract", "other"]
LABEL_MAP = {name: index for index, name in enumerate(CLASS_NAMES)}
CONTEXT_FIELDS = ["eye_side", "reflection", "image_quality", "slit_lamp_illumination_type"]
CONTEXT_VALUES = {
    "eye_side": ["Left", "Right"],
    "image_quality": ["Poor", "Good", "Very good"],
    "slit_lamp_illumination_type": ["Diffuse Illumination", "Direct Focal Illumination", "Retro Illumination"],
}


def seed_everything(seed: int) -> None:
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True; torch.backends.cudnn.benchmark = False


def locate_release() -> tuple[Path, dict[str, Path]]:
    trains = list(DATA_ROOT.rglob("train.xlsx"))
    candidates = []
    for train in trains:
        base = train.parent
        image_dir = base / "Clean images"
        if image_dir.is_dir() and (base / "val.xlsx").exists() and (base / "test.xlsx").exists():
            candidates.append((base, image_dir))
    if not candidates:
        raise FileNotFoundError("Extracted CatScreen public sample with Clean/train.xlsx and Clean/Clean images was not found.")
    base, image_dir = max(candidates, key=lambda pair: len(list(pair[1].glob("*.jpg"))))
    return image_dir, {name: base / f"{name}.xlsx" for name in ("train", "val", "test")}


def encode_context(row: pd.Series) -> np.ndarray:
    values: list[float] = []
    for item in CONTEXT_VALUES["eye_side"]:
        values.append(float(str(row["eye_side"]).strip() == item))
    values.append(float(pd.to_numeric(row["reflection"], errors="coerce") if pd.notna(row["reflection"]) else 0.0))
    for item in CONTEXT_VALUES["image_quality"]:
        values.append(float(str(row["image_quality"]).strip() == item))
    for item in CONTEXT_VALUES["slit_lamp_illumination_type"]:
        values.append(float(str(row["slit_lamp_illumination_type"]).strip() == item))
    return np.asarray(values, dtype=np.float32)


def build_training_cache(source: Path, frames: dict[str, pd.DataFrame]) -> Path:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    filenames = sorted({str(name) for frame in frames.values() for name in frame["filename"]})
    for filename in filenames:
        target = CACHE_ROOT / filename
        if target.exists():
            continue
        with Image.open(source / filename) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            image.save(target, format="JPEG", quality=92, optimize=True)
    return CACHE_ROOT


class CatScreenDataset(Dataset):
    def __init__(self, frame: pd.DataFrame, image_dir: Path, transform):
        self.frame = frame.reset_index(drop=True)
        self.image_dir = image_dir
        self.transform = transform

    def __len__(self) -> int:
        return len(self.frame)

    def __getitem__(self, index: int):
        row = self.frame.iloc[index]
        image = Image.open(self.image_dir / str(row["filename"])).convert("RGB")
        label = LABEL_MAP[str(row["diagnosis"]).strip().lower()]
        return self.transform(image), torch.from_numpy(encode_context(row)), label


class FusionNet(nn.Module):
    def __init__(self, dropout: float = 0.25):
        super().__init__()
        backbone = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
        self.features = backbone.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        image_dim = backbone.classifier[0].in_features
        self.context = nn.Sequential(nn.Linear(9, 24), nn.LayerNorm(24), nn.GELU(), nn.Dropout(dropout))
        self.head = nn.Sequential(
            nn.Linear(image_dim + 24, 192), nn.LayerNorm(192), nn.Hardswish(), nn.Dropout(dropout),
            nn.Linear(192, len(CLASS_NAMES)),
        )

    def forward(self, image: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        image_features = self.pool(self.features(image)).flatten(1)
        return self.head(torch.cat([image_features, self.context(context)], dim=1))


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    model.eval(); ys, predictions, probability_rows = [], [], []
    with torch.inference_mode():
        for images, context, labels in loader:
            logits = model(images.to(device), context.to(device))
            probabilities = logits.softmax(dim=1).cpu().numpy()
            ys.extend(labels.numpy().tolist()); predictions.extend(probabilities.argmax(axis=1).tolist()); probability_rows.extend(probabilities.tolist())
    y = np.asarray(ys); pred = np.asarray(predictions); probs = np.asarray(probability_rows)
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "per_class_recall": {CLASS_NAMES[index]: float(value) for index, value in enumerate(recall_score(y, pred, labels=np.arange(3), average=None, zero_division=0))},
    }, y, pred, probs


def main() -> None:
    seed_everything(SEED)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_dir, files = locate_release()
    frames = {name: pd.read_excel(path) for name, path in files.items()}
    for name, frame in frames.items():
        frame["diagnosis"] = frame["diagnosis"].astype(str).str.strip()
        unknown = set(frame["diagnosis"].str.lower()) - set(LABEL_MAP)
        if unknown:
            raise RuntimeError(f"Unknown grades in {name}: {unknown}")
        missing = [value for value in frame["filename"] if not (image_dir / str(value)).exists()]
        if missing:
            raise FileNotFoundError(f"{len(missing)} {name} images are missing; first: {missing[0]}")
    source_image_dir = image_dir
    image_dir = build_training_cache(source_image_dir, frames)

    overlaps = {}
    for first, second in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = sorted(set(frames[first]["id"].astype(str)) & set(frames[second]["id"].astype(str)))
        overlaps[f"{first}_{second}"] = overlap
        if overlap:
            raise RuntimeError(f"Participant leakage between {first} and {second}: {overlap[:5]}")

    weights = MobileNet_V3_Small_Weights.DEFAULT
    normalize = weights.transforms()
    train_transform = v2.Compose([
        v2.RandomResizedCrop((224, 224), scale=(0.78, 1.0)),
        v2.RandomHorizontalFlip(0.5), v2.RandomRotation(8), v2.ColorJitter(0.12, 0.12, 0.08, 0.03),
        v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=normalize.mean, std=normalize.std),
    ])
    eval_transform = v2.Compose([
        v2.Resize((224, 224)), v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=normalize.mean, std=normalize.std),
    ])
    datasets = {
        "train": CatScreenDataset(frames["train"], image_dir, train_transform),
        "validation": CatScreenDataset(frames["val"], image_dir, eval_transform),
        "test": CatScreenDataset(frames["test"], image_dir, eval_transform),
    }
    loaders = {
        name: DataLoader(ds, batch_size=16 if name == "train" else 24, shuffle=name == "train", num_workers=0, pin_memory=True,
                         generator=torch.Generator().manual_seed(SEED))
        for name, ds in datasets.items()
    }
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = FusionNet(dropout=0.30).to(device)
    for parameter in model.features.parameters(): parameter.requires_grad = False
    train_labels = frames["train"]["diagnosis"].str.lower().map(LABEL_MAP).to_numpy()
    counts = np.bincount(train_labels, minlength=3)
    class_weights = np.sqrt(len(train_labels) / (3 * counts))
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float32, device=device), label_smoothing=0.02)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=8e-4, weight_decay=2e-4)
    history = {"train_loss": [], "validation_macro_f1": [], "validation_accuracy": []}
    best_state = None; best_score = -1.0; best_epoch = 0; stale = 0

    for epoch in range(55):
        if epoch == 10:
            for parameter in model.features[-4:].parameters(): parameter.requires_grad = True
            optimizer = torch.optim.AdamW([
                {"params": model.features[-4:].parameters(), "lr": 7e-5},
                {"params": model.context.parameters(), "lr": 3e-4},
                {"params": model.head.parameters(), "lr": 3e-4},
            ], weight_decay=3e-4)
        model.train(); total_loss = 0.0; seen = 0
        for images, context, labels in loaders["train"]:
            images, context, labels = images.to(device), context.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images, context); loss = loss_fn(logits, labels)
            loss.backward(); optimizer.step()
            total_loss += loss.item() * len(labels); seen += len(labels)
        val_metrics, _, _, _ = evaluate(model, loaders["validation"], device)
        history["train_loss"].append(total_loss / seen)
        history["validation_macro_f1"].append(val_metrics["macro_f1"])
        history["validation_accuracy"].append(val_metrics["accuracy"])
        if val_metrics["macro_f1"] > best_score + 1e-5:
            best_score = val_metrics["macro_f1"]; best_epoch = epoch + 1; stale = 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
        if epoch >= 18 and stale >= 14: break

    assert best_state is not None
    model.load_state_dict(best_state)
    model.eval()
    results = {name: evaluate(model, loader, device) for name, loader in loaders.items()}
    metrics = {name: result[0] for name, result in results.items()}
    checkpoint = {
        "model_type": "MobileNetV3SmallContextFusion", "state_dict": model.state_dict(),
        "classes": CLASS_NAMES, "context_fields": CONTEXT_FIELDS, "context_values": CONTEXT_VALUES,
        "image_size": 224, "normalization_mean": list(normalize.mean), "normalization_std": list(normalize.std),
        "source": "CatScreen official public sample", "best_epoch": best_epoch,
    }
    torch.save(checkpoint, OUTPUT / "best_model.pt")

    prediction_rows = []
    for name, source_name in (("train", "train"), ("validation", "val"), ("test", "test")):
        _, y, pred, probs = results[name]
        for idx, row in frames[source_name].reset_index(drop=True).iterrows():
            item = {"participant_id": str(row["id"]), "filename": str(row["filename"]), "split": name, "target": int(y[idx]), "prediction": int(pred[idx])}
            item.update({f"p_{class_name.replace(' ', '_')}": float(probs[idx, class_idx]) for class_idx, class_name in enumerate(CLASS_NAMES)})
            prediction_rows.append(item)
    pd.DataFrame(prediction_rows).to_csv(OUTPUT / "predictions_and_splits.csv", index=False)

    y_test, pred_test = results["test"][1], results["test"][2]
    matrix = confusion_matrix(y_test, pred_test, labels=np.arange(3))
    fig, ax = plt.subplots(figsize=(6.5, 5.3)); heat = ax.imshow(matrix, cmap="Blues")
    for i in range(3):
        for j in range(3): ax.text(j, i, str(matrix[i, j]), ha="center", va="center", color="white" if matrix[i, j] > matrix.max()/2 else "#17324d", fontweight="bold")
    ax.set(xticks=range(3), yticks=range(3), xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES, xlabel="Predicted", ylabel="Actual", title="CatScreen public-sample held-out test")
    fig.colorbar(heat, ax=ax, fraction=0.046, pad=0.04); fig.tight_layout(); fig.savefig(OUTPUT / "test_confusion_matrix.png", dpi=180); plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    axes[0].plot(history["train_loss"], color="#0b7189", linewidth=2); axes[0].set(title="Training loss", xlabel="Epoch", ylabel="Weighted cross-entropy")
    axes[1].plot(history["validation_macro_f1"], label="Macro-F1", color="#ef8354", linewidth=2); axes[1].plot(history["validation_accuracy"], label="Accuracy", color="#5b8e7d", linewidth=2)
    axes[1].set(title="Validation performance", xlabel="Epoch", ylabel="Score", ylim=(0, 1)); axes[1].legend()
    for ax in axes: ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(OUTPUT / "training_curves.png", dpi=180); plt.close(fig)

    report = {
        "model_name": "Real CatScreen image-context fusion CNN",
        "status": "research_only_not_clinically_validated",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "name": "CatScreen official public sample snapshot", "official_page": "https://www.iab-rubric.org/resources/healthcare-datasets/catscreen",
            "paper": "https://openreview.net/pdf?id=cF7tSNAVQ6", "release_root": str(source_image_dir.parent),
            "training_cache": str(image_dir),
            "license_note": "Public sample obtained from the official dataset page; full release is governed by the CatScreen institutional research license.",
        },
        "target": "Three CatScreen diagnostic screening labels: normal, cataract, or other ocular condition.",
        "architecture": "ImageNet-pretrained MobileNetV3-Small image encoder fused with a 9-value context branch.",
        "context": "Laterality plus acquisition/quality context (reflection, image quality, illumination type). The public snapshot does not include the full patient clinical metadata, so this is not a complete clinical-fusion validation.",
        "split_strategy": "Official train/validation/test files; verified zero participant-ID overlap.",
        "participant_overlap": overlaps,
        "sample_counts": {"train": len(frames["train"]), "validation": len(frames["val"]), "test": len(frames["test"])},
        "participant_counts": {"train": int(frames["train"]["id"].nunique()), "validation": int(frames["val"]["id"].nunique()), "test": int(frames["test"]["id"].nunique())},
        "class_counts": {name: {key: int(value) for key, value in frame["diagnosis"].str.lower().value_counts().items()} for name, frame in frames.items()},
        "device": str(device), "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "seed": SEED, "best_epoch": best_epoch, "epochs_run": len(history["train_loss"]), "metrics": metrics, "test_confusion_matrix": matrix.tolist(),
        "limitations": [
            "The held-out test contains only 40 images from 37 participants; uncertainty is large.",
            "The public snapshot does not include the full patient metadata described for the licensed release, so the structured branch uses laterality and acquisition context only.",
            "Image quality and acquisition settings may encode site/device shortcuts and require external validation.",
            "No calibration, subgroup safety study, prospective evaluation, or clinical validation was performed.",
            "Predictions must not assign diagnosis, treatment, referral urgency, or workflow priority.",
        ],
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "device": str(device), "best_epoch": best_epoch, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
