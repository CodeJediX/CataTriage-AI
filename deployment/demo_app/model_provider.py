from __future__ import annotations

import io
import gc
import threading
from pathlib import Path

from PIL import Image, ImageStat, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "models" / "retina_four_class" / "efficientnet_b0_v3" / "best_macro_f1_model.pth"
MODEL_ID = "efficientnet_b0_v3_best_macro_f1_epoch28"
EXPECTED_CLASSES = ["cataract", "glaucoma", "normal", "retinal_disease"]
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageValidationError(ValueError):
    pass


def validate_image_bytes(payload: bytes) -> tuple[Image.Image, dict]:
    if not payload:
        raise ImageValidationError("The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ImageValidationError("Image exceeds the 8 MB demo limit.")
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(payload))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageValidationError("File is not a valid supported image.") from exc
    if image.format not in ALLOWED_FORMATS:
        raise ImageValidationError("Use a JPEG, PNG, or WebP image.")
    if image.width < 64 or image.height < 64:
        raise ImageValidationError("Image must be at least 64 x 64 pixels.")
    if image.width * image.height > 30_000_000:
        raise ImageValidationError("Image dimensions exceed the safety limit.")
    rgb = image.convert("RGB")
    stat = ImageStat.Stat(rgb.convert("L"))
    quality = {
        "width": rgb.width,
        "height": rgb.height,
        "format": image.format,
        "mean_brightness": round(stat.mean[0], 1),
        "contrast_std": round(stat.stddev[0], 1),
        "technical_warning": stat.mean[0] < 18 or stat.mean[0] > 238 or stat.stddev[0] < 8,
    }
    return rgb, quality


class RetinaModelProvider:
    def __init__(self, checkpoint: Path = CHECKPOINT):
        self.checkpoint = checkpoint
        self._model = None
        self._transform = None
        self._device = None
        self._fallback_reason = None
        self._lock = threading.Lock()
        self.class_names = EXPECTED_CLASSES.copy()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        with self._lock:
            if self.loaded:
                return
            import torch
            self._load_on_device(torch.device("cuda" if torch.cuda.is_available() else "cpu"))

    def _load_on_device(self, device) -> None:
        import torch
        from torchvision.models import efficientnet_b0
        from torchvision.transforms import Compose, Normalize, Resize, ToTensor

        if not self.checkpoint.exists():
            raise FileNotFoundError(f"Checkpoint not found: {self.checkpoint}")
        saved = torch.load(self.checkpoint, map_location=device, weights_only=False)
        classes = list(saved.get("class_names", []))
        if classes != EXPECTED_CLASSES:
            raise RuntimeError(f"Unexpected class order: {classes}")
        model = efficientnet_b0(weights=None)
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(classes))
        model.load_state_dict(saved["model_state_dict"], strict=True)
        model.eval().to(device)
        size = int(saved.get("image_size", 224))
        mean = saved.get("normalization_mean", [0.485, 0.456, 0.406])
        std = saved.get("normalization_std", [0.229, 0.224, 0.225])
        self._transform = Compose([Resize((size, size)), ToTensor(), Normalize(mean, std)])
        self._model = model
        self._device = device
        self.class_names = classes

    @property
    def device_label(self) -> str:
        if self._device is None:
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu fallback"
            except Exception:
                return "unavailable"
        return str(self._device) if str(self._device) == "cuda" else "cpu fallback"

    def analyze(self, payload: bytes, modality: str) -> dict:
        image, quality = validate_image_bytes(payload)
        if modality != "fundus":
            return {
                "status": "not_available",
                "reason": "No validated slit-lamp severity or urgency model is available.",
                "technical_quality": quality,
                "urgency": None,
            }
        self.load()
        import torch

        tensor = self._transform(image).unsqueeze(0)
        try:
            with torch.inference_mode():
                logits = self._model(tensor.to(self._device))
                values = torch.softmax(logits, dim=1)[0].detach().cpu().tolist()
        except RuntimeError as exc:
            message = str(exc).lower()
            recoverable = str(self._device) == "cuda" and ("out of memory" in message or "cublas_status_not_initialized" in message)
            if not recoverable:
                raise
            self._model = None
            self._device = None
            self._fallback_reason = "CUDA memory/initialization failure; inference retried on CPU."
            torch.cuda.empty_cache()
            gc.collect()
            self._load_on_device(torch.device("cpu"))
            with torch.inference_mode():
                logits = self._model(tensor)
                values = torch.softmax(logits, dim=1)[0].tolist()
        probabilities = {name: round(float(value), 6) for name, value in zip(self.class_names, values)}
        top = max(probabilities, key=probabilities.get)
        confidence = probabilities[top]
        return {
            "status": "ok",
            "model_id": MODEL_ID,
            "device": self.device_label,
            "device_note": self._fallback_reason,
            "class_order": self.class_names,
            "probabilities": probabilities,
            "top_class": top,
            "confidence": confidence,
            "uncertainty_warning": confidence < 0.60,
            "technical_quality": quality,
            "urgency": None,
        }


provider = RetinaModelProvider()
