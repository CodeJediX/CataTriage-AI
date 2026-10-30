"""EfficientNet-B0 retina training with validated splits and epoch-level recovery.

CSV columns: full_path, label; optionally patient_id (or --group-column).
Relative image paths are resolved against the CSV's directory.
Run --help for options. Defaults retain the original training hyperparameters.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time
import warnings

import numpy as np
import pandas as pd
from PIL import Image
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0
from torchvision.transforms import InterpolationMode
from sklearn.metrics import classification_report, confusion_matrix, f1_score


CLASS_NAMES = ["cataract", "glaucoma", "normal", "retinal_disease"]
CLASS_TO_INDEX = {name: index for index, name in enumerate(CLASS_NAMES)}
PROJECT = Path(r"E:\Eye Project\CataTriage_AI")
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
FORMAT_VERSION = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-csv", type=Path,
                        default=PROJECT / "data_splits/retina_four_class/train.csv")
    parser.add_argument("--val-csv", type=Path,
                        default=PROJECT / "data_splits/retina_four_class/validation.csv")
    parser.add_argument("--output-dir", type=Path,
                        default=PROJECT / "models/retina_four_class/efficientnet_b0_v3")
    parser.add_argument("--resume", type=Path, help="V3 latest_checkpoint.pth in its original run directory")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--warmup-epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup-lr", type=float, default=3e-4)
    parser.add_argument("--backbone-lr", type=float, default=2e-5)
    parser.add_argument("--classifier-lr", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--class-weight-power", type=float, default=0.5)
    parser.add_argument("--grad-clip-norm", type=float, default=1.0)
    parser.add_argument("--plot-every", type=int, default=5)
    parser.add_argument("--group-column", help="Patient/group ID column; patient_id is used automatically if present")
    parser.add_argument("--verify-images", action="store_true", help="Decode all images before training")
    parser.add_argument("--deterministic", action="store_true", help="Require deterministic PyTorch operations")
    parser.add_argument("--no-amp", action="store_true")
    parser.add_argument("--no-pretrained", action="store_true", help="Random initialization, mainly for offline smoke tests")
    args = parser.parse_args(argv)
    for name in ("epochs", "batch_size", "plot_every"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.image_size < 64:
        parser.error("--image-size must be at least 64")
    if not 0 <= args.warmup_epochs <= args.epochs:
        parser.error("--warmup-epochs must be between zero and --epochs")
    if args.num_workers < 0 or not 0 <= args.seed < 2**32:
        parser.error("num-workers must be nonnegative and seed must be in [0, 2**32)")
    if not 0 <= args.label_smoothing <= 1:
        parser.error("--label-smoothing must be in [0, 1]")
    for name in ("warmup_lr", "backbone_lr", "classifier_lr", "grad_clip_norm"):
        if not np.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            parser.error(f"{name} must be finite and positive")
    for name in ("weight_decay", "class_weight_power"):
        if not np.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            parser.error(f"{name} must be finite and nonnegative")
    return args


def seed_everything(seed, deterministic):
    # Must be configured before CUDA context initialization.
    if deterministic:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = not deterministic
    torch.backends.cudnn.deterministic = deterministic
    torch.use_deterministic_algorithms(deterministic)


def seed_worker(_worker_id):
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)


def read_split(csv_file, verify_images=False):
    csv_file = csv_file.expanduser().resolve()
    df = pd.read_csv(csv_file, dtype=str)
    required = {"full_path", "label"}
    if not required.issubset(df.columns):
        raise ValueError(f"{csv_file}: required columns are {sorted(required)}")
    if df.empty or df[list(required)].isna().any().any():
        raise ValueError(f"{csv_file}: empty split or missing path/label")
    df["label"] = df["label"].str.strip()
    unknown = sorted(set(df["label"]) - set(CLASS_NAMES))
    if unknown:
        raise ValueError(f"{csv_file}: unknown labels {unknown}; expected {CLASS_NAMES}")
    paths = []
    for raw_path in df["full_path"]:
        if not raw_path.strip():
            raise ValueError(f"{csv_file}: empty image path")
        path = Path(raw_path).expanduser()
        path = (path if path.is_absolute() else csv_file.parent / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{csv_file}: image not found: {path}")
        if verify_images:
            try:
                with Image.open(path) as image:
                    image.convert("RGB").load()
            except (OSError, ValueError) as exc:
                raise ValueError(f"Cannot decode image: {path}") from exc
        paths.append(str(path))
    df["full_path"] = paths
    keys = df["full_path"].map(os.path.normcase)
    if keys.duplicated().any():
        raise ValueError(f"{csv_file}: duplicate image paths")
    return df


def validate_splits(train_df, val_df, group_column=None):
    missing = set(CLASS_NAMES) - set(train_df["label"])
    if missing:
        raise ValueError(f"Training split is missing classes: {sorted(missing)}")
    train_paths = set(train_df["full_path"].map(os.path.normcase))
    val_paths = set(val_df["full_path"].map(os.path.normcase))
    if train_paths & val_paths:
        raise ValueError("Train/validation leakage: the same image path occurs in both splits")
    missing_val = set(CLASS_NAMES) - set(val_df["label"])
    if missing_val:
        warnings.warn(f"Validation lacks {sorted(missing_val)}; macro-F1 still averages all four classes")
    if group_column is None and ("patient_id" in train_df or "patient_id" in val_df):
        group_column = "patient_id"
    if group_column:
        groups = []
        for df in (train_df, val_df):
            if group_column not in df:
                raise ValueError(f"Both CSVs must contain group column {group_column!r}")
            values = df[group_column].str.strip()
            if values.isna().any() or (values == "").any():
                raise ValueError(f"Missing values in group column {group_column!r}")
            groups.append(set(values))
        if groups[0] & groups[1]:
            raise ValueError(f"Train/validation leakage: overlapping {group_column} values")


class RetinaDataset(Dataset):
    def __init__(self, dataframe, transform):
        self.paths = dataframe["full_path"].tolist()
        self.labels = dataframe["label"].map(CLASS_TO_INDEX).tolist()
        self.transform = transform

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, index):
        path = self.paths[index]
        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                tensor = self.transform(image)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Failed to read image {path}") from exc
        return tensor, self.labels[index]


def make_transforms(image_size):
    resize = transforms.Resize((image_size, image_size),
                               interpolation=InterpolationMode.BILINEAR, antialias=True)
    tail = [transforms.ToTensor(), transforms.Normalize(MEAN, STD)]
    train = transforms.Compose([
        resize, transforms.RandomHorizontalFlip(0.5),
        transforms.RandomRotation(8, interpolation=InterpolationMode.BILINEAR, fill=0),
        transforms.ColorJitter(brightness=0.08, contrast=0.08, saturation=0.05, hue=0.01),
        *tail,
    ])
    return train, transforms.Compose([resize, *tail])


def calculate_class_weights(dataframe, power):
    counts = dataframe["label"].value_counts().reindex(CLASS_NAMES, fill_value=0)
    if (counts == 0).any():
        raise ValueError("Every class must occur in training to calculate class weights")
    weights = (len(dataframe) / (len(CLASS_NAMES) * counts.to_numpy())) ** power
    return torch.tensor(weights, dtype=torch.float32)


def build_model(pretrained=True):
    model = efficientnet_b0(weights=EfficientNet_B0_Weights.DEFAULT if pretrained else None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(CLASS_NAMES))
    return model


def configure_stage(model, args, stage):
    frozen = stage == "classifier_warmup"
    for parameter in model.features.parameters():
        parameter.requires_grad_(not frozen)
    if frozen:
        optimizer = torch.optim.AdamW(model.classifier.parameters(), lr=args.warmup_lr,
                                      weight_decay=args.weight_decay)
        return optimizer, None
    optimizer = torch.optim.AdamW([
        {"params": model.features.parameters(), "lr": args.backbone_lr},
        {"params": model.classifier.parameters(), "lr": args.classifier_lr},
    ], weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3, min_lr=1e-7)
    return optimizer, scheduler


def run_epoch(model, loader, criterion, device, amp, optimizer=None, scaler=None,
              backbone_frozen=False, grad_clip_norm=1.0):
    training = optimizer is not None
    model.train(training)
    if training and backbone_frozen:
        model.features.eval()
    numerator = denominator = 0.0
    labels_all, predictions_all = [], []
    with torch.set_grad_enabled(training):
        for images, labels in loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            if training:
                optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
                outputs = model(images)
                loss = criterion(outputs, labels)
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite loss; previous completed epoch remains recoverable")
            if training:
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                # AMP's scaler skips an overflowing step and adjusts its scale.
                nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm,
                                         error_if_nonfinite=not amp)
                scaler.step(optimizer)
                scaler.update()
            # CrossEntropyLoss(mean) divides by sum of target weights, even
            # with label smoothing. Weight each batch mean by that denominator.
            batch_denominator = (criterion.weight[labels].sum().item()
                                 if criterion.weight is not None else labels.numel())
            numerator += loss.item() * batch_denominator
            denominator += batch_denominator
            labels_all.extend(labels.detach().cpu().tolist())
            predictions_all.extend(outputs.detach().argmax(1).cpu().tolist())
    if not labels_all:
        raise ValueError("Cannot calculate metrics for an empty loader")
    return {
        "loss": numerator / denominator,
        "accuracy": float(np.mean(np.equal(labels_all, predictions_all))),
        "macro_f1": float(f1_score(labels_all, predictions_all, labels=range(len(CLASS_NAMES)),
                                   average="macro", zero_division=0)),
    }, labels_all, predictions_all


def atomic_torch_save(payload, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_text(text, path):
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture_rng(generators):
    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        # Store NumPy state as primitives so weights_only=True can load it.
        "numpy": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "loaders": [generator.get_state() for generator in generators],
    }


def restore_rng(state, generators):
    random.setstate(state["python"])
    numpy_state = state["numpy"]
    np.random.set_state((numpy_state[0], np.array(numpy_state[1], dtype=np.uint32),
                         *numpy_state[2:]))
    torch.set_rng_state(state["torch"])
    if state["cuda"] and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])
    for generator, saved in zip(generators, state["loaders"]):
        generator.set_state(saved)


def run_config(args, train_df, val_df):
    # Epoch count may increase on resume; numerical/data settings must match.
    excluded = {"resume", "output_dir", "epochs", "plot_every", "verify_images", "train_csv", "val_csv"}
    config = {key: value for key, value in vars(args).items() if key not in excluded}
    config["class_names"] = CLASS_NAMES
    config["split_sha256"] = [hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
                               for df in (train_df, val_df)]
    return config


def model_payload(model, args, row):
    return {
        "format_version": FORMAT_VERSION, "model_name": "efficientnet_b0",
        "class_names": CLASS_NAMES, "class_to_index": CLASS_TO_INDEX,
        "image_size": args.image_size, "normalization_mean": MEAN, "normalization_std": STD,
        "resize": "bilinear square resize, antialias=True",
        "model_state_dict": model.state_dict(), "epoch": row["epoch"],
        **{key: row[key] for key in ("val_loss", "val_accuracy", "val_macro_f1")},
    }


def create_graphs(history, graph_dir, warmup_epochs):
    graph_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(history)
    for metric in ("loss", "accuracy", "macro_f1"):
        fig, ax = plt.subplots(figsize=(8, 5))
        for split in ("train", "val"):
            ax.plot(df["epoch"], df[f"{split}_{metric}"], label=split)
        if 0 < warmup_epochs < df["epoch"].max():
            ax.axvline(warmup_epochs + 0.5, linestyle="--", label="Full fine-tuning")
        ax.set(xlabel="Epoch", ylabel=metric.replace("_", " "), title=metric.replace("_", " ").title())
        if metric != "loss":
            ax.set_ylim(0, 1)
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(graph_dir / f"{metric}.png", dpi=160)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    for group in ("backbone", "classifier"):
        values = df[f"{group}_lr"].replace(0, np.nan)
        ax.plot(df["epoch"], values, label=group)
    ax.set(xlabel="Epoch", ylabel="Learning rate used", yscale="log")
    ax.legend()
    fig.tight_layout()
    fig.savefig(graph_dir / "learning_rate.png", dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(df["epoch"], df["train_accuracy"] - df["val_accuracy"])
    ax.axhline(0, linestyle="--")
    ax.set(xlabel="Epoch", ylabel="Train accuracy - validation accuracy",
           title="Accuracy gap (training uses augmentation and dropout)")
    fig.tight_layout()
    fig.savefig(graph_dir / "generalization_gap.png", dpi=160)
    plt.close(fig)


def main(argv=None):
    args = parse_args(argv)
    seed_everything(args.seed, args.deterministic)
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Use --device cpu explicitly for CPU training/testing.")
    amp = device.type == "cuda" and not args.no_amp
    out = args.output_dir.expanduser().resolve()
    checkpoint = None
    if args.resume:
        resume_path = args.resume.expanduser().resolve()
        if resume_path != out / "latest_checkpoint.pth":
            raise ValueError("Resume from the latest checkpoint in --output-dir to preserve the run's best models")
        checkpoint = torch.load(resume_path, map_location="cpu", weights_only=True)
        if checkpoint.get("format_version") != FORMAT_VERSION or "rng" not in checkpoint:
            raise ValueError("Resume requires a V3 recovery checkpoint; V2 files lack recovery state")
    elif out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {out}. Use --resume or a new --output-dir.")

    train_df = read_split(args.train_csv, args.verify_images)
    val_df = read_split(args.val_csv, args.verify_images)
    validate_splits(train_df, val_df, args.group_column)
    config = run_config(args, train_df, val_df)
    if checkpoint:
        changed = [key for key in config if config[key] != checkpoint["config"].get(key)]
        if changed:
            raise ValueError(f"Resume settings/data changed: {changed}")
        if args.epochs < checkpoint["epoch"]:
            raise ValueError("--epochs is less than the number already completed")
        for filename in ("best_macro_f1_model.pth", "best_val_accuracy_model.pth"):
            if not (out / filename).is_file():
                raise FileNotFoundError(f"Missing best checkpoint from this run: {out / filename}")
    out.mkdir(parents=True, exist_ok=True)
    atomic_text(json.dumps(config, indent=2), out / "run_config.json")
    print(f"Device: {device} | Train: {len(train_df)} | Validation: {len(val_df)}", flush=True)
    print(f"Epochs: {args.epochs}; warm-up: {args.warmup_epochs}; early stopping: disabled", flush=True)

    train_transform, val_transform = make_transforms(args.image_size)
    generators = [torch.Generator().manual_seed(args.seed + offset) for offset in (0, 1)]
    common = dict(batch_size=args.batch_size, num_workers=args.num_workers,
                  pin_memory=device.type == "cuda", worker_init_fn=seed_worker)
    # Recreate workers each epoch so generator state also reproduces their RNGs on resume.
    train_loader = DataLoader(RetinaDataset(train_df, train_transform), shuffle=True,
                              generator=generators[0], **common)
    val_loader = DataLoader(RetinaDataset(val_df, val_transform), shuffle=False,
                            generator=generators[1], **common)
    model = build_model(pretrained=not args.no_pretrained and checkpoint is None).to(device)
    criterion = nn.CrossEntropyLoss(weight=calculate_class_weights(train_df, args.class_weight_power).to(device),
                                    label_smoothing=args.label_smoothing)
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    history = checkpoint["history"] if checkpoint else []
    stage = checkpoint["stage"] if checkpoint else ("classifier_warmup" if args.warmup_epochs else "full_finetune")
    optimizer, scheduler = configure_stage(model, args, stage)
    best = checkpoint["best"] if checkpoint else {"macro_f1": -1.0, "accuracy": -1.0}
    if checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        scaler.load_state_dict(checkpoint["scaler_state_dict"])
        if scheduler is not None:
            scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
        restore_rng(checkpoint["rng"], generators)
        print(f"Resuming after epoch {checkpoint['epoch']}", flush=True)
    start_epoch = checkpoint["epoch"] + 1 if checkpoint else 1
    # Release the CPU copy of all checkpoint tensors after restoration.
    del checkpoint
    for epoch in range(start_epoch, args.epochs + 1):
        target_stage = "classifier_warmup" if epoch <= args.warmup_epochs else "full_finetune"
        if stage != target_stage:
            stage = target_stage
            optimizer, scheduler = configure_stage(model, args, stage)
            print("Starting full-network fine-tuning", flush=True)
        frozen = stage == "classifier_warmup"
        # Capture rates before scheduler.step: these are the rates used this epoch.
        backbone_lr = 0.0 if frozen else optimizer.param_groups[0]["lr"]
        classifier_lr = optimizer.param_groups[-1]["lr"]
        start = time.perf_counter()
        train, _, _ = run_epoch(model, train_loader, criterion, device, amp, optimizer, scaler,
                                backbone_frozen=frozen, grad_clip_norm=args.grad_clip_norm)
        val, _, _ = run_epoch(model, val_loader, criterion, device, amp)
        if scheduler is not None:
            scheduler.step(val["macro_f1"])
        row = {"epoch": epoch, "stage": stage,
               **{f"train_{key}": value for key, value in train.items()},
               **{f"val_{key}": value for key, value in val.items()},
               "backbone_lr": backbone_lr, "classifier_lr": classifier_lr,
               "epoch_seconds": time.perf_counter() - start}
        history.append(row)
        payload = model_payload(model, args, row)
        for metric, filename in (("macro_f1", "best_macro_f1_model.pth"),
                                 ("accuracy", "best_val_accuracy_model.pth")):
            if val[metric] > best[metric]:
                best[metric] = val[metric]
                atomic_torch_save(payload, out / filename)
        recovery = {**payload, "stage": stage, "config": config, "history": history, "best": best,
                    "optimizer_state_dict": optimizer.state_dict(), "scaler_state_dict": scaler.state_dict(),
                    "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
                    "rng": capture_rng(generators)}
        # Recovery takes precedence over optional graph generation.
        atomic_torch_save(recovery, out / "latest_checkpoint.pth")
        atomic_text(pd.DataFrame(history).to_csv(index=False), out / "training_history.csv")
        print(f"Epoch {epoch:02d}/{args.epochs} | {stage} | "
              f"train loss {train['loss']:.4f} acc {train['accuracy']:.4f} F1 {train['macro_f1']:.4f} | "
              f"val loss {val['loss']:.4f} acc {val['accuracy']:.4f} F1 {val['macro_f1']:.4f} | "
              f"{row['epoch_seconds']:.1f}s", flush=True)
        if epoch % args.plot_every == 0:
            create_graphs(history, out / "graphs", args.warmup_epochs)

    atomic_torch_save(model_payload(model, args, history[-1]), out / "final_epoch_model.pth")
    atomic_text(pd.DataFrame(history).to_csv(index=False), out / "training_history.csv")
    create_graphs(history, out / "graphs", args.warmup_epochs)
    # Reports explicitly describe the selected checkpoint, not the final epoch.
    selected = torch.load(out / "best_macro_f1_model.pth", map_location="cpu", weights_only=True)
    model.load_state_dict(selected["model_state_dict"])
    _, labels, predictions = run_epoch(model, val_loader, criterion, device, amp)
    report = classification_report(labels, predictions, labels=range(len(CLASS_NAMES)),
                                   target_names=CLASS_NAMES, zero_division=0, output_dict=True)
    atomic_text(pd.DataFrame(report).transpose().to_csv(), out / "best_f1_classification_report.csv")
    matrix = confusion_matrix(labels, predictions, labels=range(len(CLASS_NAMES)))
    atomic_text(pd.DataFrame(matrix, index=CLASS_NAMES, columns=CLASS_NAMES).to_csv(),
                out / "best_f1_confusion_matrix.csv")
    best_acc_row = max(history, key=lambda row: row["val_accuracy"])
    summary = (
        f"EfficientNet-B0 V3 | Completed {len(history)} epochs | No early stopping\n"
        f"Best validation macro-F1: {selected['val_macro_f1']:.6f} at epoch {selected['epoch']}\n"
        f"Best validation accuracy: {best_acc_row['val_accuracy']:.6f} at epoch {best_acc_row['epoch']}\n"
        f"Final validation macro-F1: {history[-1]['val_macro_f1']:.6f}\n"
        f"Training/validation epoch time: {sum(row['epoch_seconds'] for row in history) / 60:.2f} minutes\n"
        "Loss is class-weighted cross-entropy with label smoothing in both splits.\n"
        "Classification report and confusion matrix use the best macro-F1 checkpoint.\n"
        "Confusion matrix rows are true labels; columns are predicted labels.\n"
        "Validation selects checkpoints; reserve a separate test set for final evaluation.\n"
    )
    atomic_text(summary, out / "training_summary.txt")
    print(summary, flush=True)
    print(f"Saved run to {out}")


if __name__ == "__main__":
    main()
