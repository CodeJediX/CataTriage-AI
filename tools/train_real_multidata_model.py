from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
)
from sklearn.model_selection import train_test_split
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    r"E:\Eye Project\data sets\Eye_Datasets_Organized\01_multimodal_collections"
    r"\catatriage_ai\02_Clinical_Tabular\01_Cataract_Risk_and_Grading"
    r"\10.5061_dryad.gt410__new PONE-D-15-08786 original data set.xls"
)
OUTPUT = ROOT / "models" / "cataract_grade_multidata_real"
SEED = 20261026
LABELS = ["grade 0", "grade 1", "grade 2", "grade 3+"]


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def clean(name: str) -> str:
    return " ".join(str(name).strip().split())


def build_dataset() -> tuple[pd.DataFrame, pd.Series, pd.Series, list[str]]:
    raw = pd.read_excel(SOURCE, sheet_name="Sheet1")
    raw.columns = [clean(c) for c in raw.columns]
    grade_cols = [
        "Right NO grading", "Right NC grading", "Right C grading", "Right P grading",
        "left NO grading", "left NC grading", "left C grading", "left P grading",
    ]
    max_grade = raw[grade_cols].apply(pd.to_numeric, errors="coerce").max(axis=1)
    target = pd.cut(max_grade, [-1, 0.5, 1.5, 2.5, math.inf], labels=False)

    # These inputs are available before a cataract grade is assigned. Direct cataract
    # diagnoses, lens status, cataract history/surgery and all grading fields are
    # intentionally excluded to prevent label leakage.
    features = [
        "gender", "age", "UCVA Right eye", "BCVA Right", "UCVA Left", "BCVA Left",
        "R optic disc：C/D", "R glaucoma(1 No 2 Yes)", "R AMD (1 No 2 Yes)",
        "R DR (1 No 2 Yes)", "R optic neuritis(1 No 2 Yes)",
        "R retinal pigment degeneration(1 No 2 Yes)", "R RAO/RVO(1 No 2 Yes)",
        "R uveitis(1 No 2 Yes)", "high myopia(1 No 2 Yes)",
        "other fundus diseases(1 No 2 Yes)", "left optic disc：C/D",
        "L glaucoma(1 No 2 Yes)", "L AMD (1 No 2 Yes)", "L DR(1 No 2 Yes)",
        "L optic neuritis(1 No 2 Yes)", "L retinal pigment degeneration(1 No 2 Yes)",
        "L RAO/RVO(1 No 2 Yes)", "L uveitis(1 No 2 Yes)",
        "L high myopia(1 No 2 Yes)", "L other fundus diseases(1 No 2 Yes)",
        "glaucoma history(1 No 2 Yes)", "fundus diseases history(1 No 2 Yes)",
        "uveitis history(1 No 2 Yes)", "other eye diseases(1 No 2 Yes)",
        "eye surgery history(1 No 2 Yes)", "Glaucoma surgery history(1 No 2 Yes)",
        "retinal surgery history(1 No 2 Yes)", "corneal surgery history(1 No 2 Yes)",
        "Steroid taken history(1 No 2 Yes)",
        "Glaucoma drug taken history (1 Yes 0 No)", "Use years .1",
        "outdoor activity hours per day", "sunlight protection or not",
        "Eye diseases history in family", "Glaucoma", "Retinal diseases", "Myopia",
        "Other diseases",
    ]
    missing = [c for c in features + grade_cols if c not in raw.columns]
    if missing:
        raise RuntimeError(f"Expected columns are missing: {missing}")
    valid = target.notna()
    x = raw.loc[valid, features].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
    y = target.loc[valid].astype(int).reset_index(drop=True)
    ids = raw.loc[valid, "ID"].astype(str).reset_index(drop=True)
    return x, y, ids, features


class GradeMLP(nn.Module):
    def __init__(self, n_features: int, hidden: int, dropout: float):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_features, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2), nn.LayerNorm(hidden // 2), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden // 2, len(LABELS)),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@torch.no_grad()
def predict(model: nn.Module, x: np.ndarray, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits = model(torch.tensor(x, dtype=torch.float32, device=device))
    probs = logits.softmax(dim=1).cpu().numpy()
    return probs.argmax(axis=1), probs


def metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "quadratic_weighted_kappa": float(cohen_kappa_score(y, pred, weights="quadratic")),
        "grade_mae": float(mean_absolute_error(y, pred)),
    }


def main() -> None:
    seed_everything(SEED)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    xdf, yser, ids, features = build_dataset()
    indices = np.arange(len(yser))
    train_idx, test_idx = train_test_split(indices, test_size=0.15, stratify=yser, random_state=SEED)
    train_idx, val_idx = train_test_split(
        train_idx, test_size=0.1764705882, stratify=yser.iloc[train_idx], random_state=SEED
    )

    train_x = xdf.iloc[train_idx].to_numpy(np.float32)
    medians = np.nanmedian(train_x, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)

    def preprocess(arr: np.ndarray) -> np.ndarray:
        arr = arr.astype(np.float32, copy=True)
        positions = np.where(np.isnan(arr))
        arr[positions] = medians[positions[1]]
        return (arr - means) / stds

    filled_train = train_x.copy()
    positions = np.where(np.isnan(filled_train))
    filled_train[positions] = medians[positions[1]]
    means = filled_train.mean(axis=0)
    stds = filled_train.std(axis=0)
    stds[stds < 1e-6] = 1.0
    arrays = {name: preprocess(xdf.iloc[idx].to_numpy(np.float32)) for name, idx in {
        "train": train_idx, "validation": val_idx, "test": test_idx
    }.items()}
    labels = {"train": yser.iloc[train_idx].to_numpy(), "validation": yser.iloc[val_idx].to_numpy(), "test": yser.iloc[test_idx].to_numpy()}

    configs = [
        {"hidden": 128, "dropout": 0.20, "lr": 8e-4, "weight_decay": 2e-4},
        {"hidden": 192, "dropout": 0.30, "lr": 6e-4, "weight_decay": 5e-4},
        {"hidden": 96, "dropout": 0.10, "lr": 1e-3, "weight_decay": 1e-4},
    ]
    class_counts = np.bincount(labels["train"], minlength=len(LABELS))
    class_weights = len(labels["train"]) / (len(LABELS) * class_counts)
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float32, device=device))
    train_loader = DataLoader(
        TensorDataset(torch.tensor(arrays["train"]), torch.tensor(labels["train"], dtype=torch.long)),
        batch_size=128, shuffle=True, generator=torch.Generator().manual_seed(SEED),
    )

    best_run = None
    for run_id, config in enumerate(configs):
        seed_everything(SEED + run_id)
        model = GradeMLP(len(features), config["hidden"], config["dropout"]).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=config["lr"], weight_decay=config["weight_decay"])
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=10)
        best_state = None
        best_val = -1.0
        stale = 0
        history = {"train_loss": [], "validation_macro_f1": [], "validation_accuracy": []}
        for epoch in range(220):
            model.train()
            total_loss = 0.0
            seen = 0
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad(set_to_none=True)
                loss = loss_fn(model(xb), yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item() * len(xb)
                seen += len(xb)
            val_pred, _ = predict(model, arrays["validation"], device)
            val_metrics = metrics(labels["validation"], val_pred)
            history["train_loss"].append(total_loss / seen)
            history["validation_macro_f1"].append(val_metrics["macro_f1"])
            history["validation_accuracy"].append(val_metrics["accuracy"])
            scheduler.step(val_metrics["macro_f1"])
            if val_metrics["macro_f1"] > best_val + 1e-4:
                best_val = val_metrics["macro_f1"]
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                stale = 0
            else:
                stale += 1
            if stale >= 35:
                break
        assert best_state is not None
        model.load_state_dict(best_state)
        val_pred, _ = predict(model, arrays["validation"], device)
        score = metrics(labels["validation"], val_pred)["macro_f1"]
        candidate = {"score": score, "model": model, "config": config, "history": history, "epochs": len(history["train_loss"])}
        if best_run is None or candidate["score"] > best_run["score"]:
            best_run = candidate

    assert best_run is not None
    model = best_run["model"]
    split_metrics = {}
    predictions = {}
    for name in ("train", "validation", "test"):
        pred, probs = predict(model, arrays[name], device)
        split_metrics[name] = metrics(labels[name], pred)
        predictions[name] = (pred, probs)

    checkpoint = {
        "model_type": "GradeMLP",
        "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "n_features": len(features),
        "hidden": best_run["config"]["hidden"],
        "dropout": best_run["config"]["dropout"],
        "labels": LABELS,
        "features": features,
        "medians": medians.tolist(), "means": means.tolist(), "stds": stds.tolist(),
    }
    torch.save(checkpoint, OUTPUT / "best_model.pt")

    split_manifest = []
    for name, idx in (("train", train_idx), ("validation", val_idx), ("test", test_idx)):
        pred, probs = predictions[name]
        for position, source_idx in enumerate(idx):
            row = {"participant_id": ids.iloc[source_idx], "split": name, "target": int(labels[name][position]), "prediction": int(pred[position])}
            row.update({f"p_{i}": float(probs[position, i]) for i in range(len(LABELS))})
            split_manifest.append(row)
    pd.DataFrame(split_manifest).to_csv(OUTPUT / "predictions_and_splits.csv", index=False)

    cm = confusion_matrix(labels["test"], predictions["test"][0], labels=np.arange(len(LABELS)))
    fig, ax = plt.subplots(figsize=(6.8, 5.6))
    image = ax.imshow(cm, cmap="Blues")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "#17324d", fontweight="bold")
    ax.set(xticks=range(4), yticks=range(4), xticklabels=LABELS, yticklabels=LABELS, xlabel="Predicted", ylabel="Actual", title="Real held-out test confusion matrix")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(OUTPUT / "test_confusion_matrix.png", dpi=180); plt.close(fig)

    history = best_run["history"]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    axes[0].plot(history["train_loss"], color="#0b7189", linewidth=2); axes[0].set(title="Training loss", xlabel="Epoch", ylabel="Weighted cross-entropy")
    axes[1].plot(history["validation_macro_f1"], label="Macro-F1", color="#ef8354", linewidth=2)
    axes[1].plot(history["validation_accuracy"], label="Accuracy", color="#5b8e7d", linewidth=2)
    axes[1].set(title="Validation performance", xlabel="Epoch", ylabel="Score", ylim=(0, 1)); axes[1].legend()
    for ax in axes: ax.grid(alpha=0.2)
    fig.tight_layout(); fig.savefig(OUTPUT / "training_curves.png", dpi=180); plt.close(fig)

    report = {
        "model_name": "Real multi-data cataract grade model",
        "status": "research_only_not_clinically_validated",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {"path": str(SOURCE), "doi": "10.5061/dryad.gt410", "license": "CC0 1.0", "population": "Taizhou Eye Study phase 1"},
        "target": "Maximum available grade across bilateral NO, NC, cortical and PSC fields, grouped as 0, 1, 2, or 3+.",
        "inputs": features,
        "leakage_controls": "All direct cataract flags, cataract history/surgery, lens status, cataract type and grading fields excluded from inputs. Preprocessing fit on training split only.",
        "split_strategy": "Single row per participant; stratified 70/15/15 participant-level train/validation/test split with fixed seed. Test set used only after validation-based configuration selection.",
        "sample_counts": {name: int(len(values)) for name, values in labels.items()},
        "class_counts": {name: {LABELS[i]: int(v) for i, v in enumerate(np.bincount(values, minlength=4))} for name, values in labels.items()},
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "seed": SEED,
        "selected_hyperparameters": best_run["config"],
        "epochs": best_run["epochs"],
        "metrics": split_metrics,
        "test_confusion_matrix": cm.tolist(),
        "limitations": [
            "This is a retrospective single-population research benchmark, not a diagnostic device.",
            "The target is a derived patient-level maximum; it is not an independent adjudicated outcome.",
            "No external validation, calibration study, subgroup safety study, or prospective clinical evaluation was performed.",
            "Predictions must never assign treatment or urgency and require clinician review.",
        ],
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "device": str(device), "metrics": split_metrics, "config": best_run["config"]}, indent=2))


if __name__ == "__main__":
    main()
