from __future__ import annotations

import io
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .model_provider import validate_image_bytes


ROOT = Path(__file__).resolve().parents[2]
MULTIDATA_CHECKPOINT = ROOT / "models" / "cataract_grade_multidata_real" / "best_model.pt"
FUSION_CHECKPOINT = ROOT / "models" / "clinical_fusion_catscreen_real" / "best_model.pt"


class GradeMLP:
    @staticmethod
    def create(n_features: int, hidden: int, dropout: float):
        from torch import nn
        class _Grade(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(n_features, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(dropout),
                    nn.Linear(hidden, hidden // 2), nn.LayerNorm(hidden // 2), nn.GELU(), nn.Dropout(dropout),
                    nn.Linear(hidden // 2, 4),
                )

            def forward(self, values):
                return self.net(values)

        return _Grade()


class FusionNet:
    @staticmethod
    def create(dropout: float = 0.30):
        from torch import nn
        from torchvision.models import mobilenet_v3_small

        class _Fusion(nn.Module):
            def __init__(self):
                super().__init__()
                backbone = mobilenet_v3_small(weights=None)
                self.features = backbone.features
                self.pool = nn.AdaptiveAvgPool2d(1)
                image_dim = backbone.classifier[0].in_features
                self.context = nn.Sequential(nn.Linear(9, 24), nn.LayerNorm(24), nn.GELU(), nn.Dropout(dropout))
                self.head = nn.Sequential(
                    nn.Linear(image_dim + 24, 192), nn.LayerNorm(192), nn.Hardswish(), nn.Dropout(dropout),
                    nn.Linear(192, 3),
                )

            def forward(self, image, context):
                image_features = self.pool(self.features(image)).flatten(1)
                return self.head(__import__("torch").cat([image_features, self.context(context)], dim=1))

        return _Fusion()


def build_fusion(saved):
    """Load versioned checkpoints without downloading weights at inference time."""
    if saved['model_type']=='FusionBlendV2':
        import torch
        from torch import nn
        class Blend(nn.Module):
            def __init__(self):
                super().__init__()
                self.primary=build_fusion(saved['primary']);self.secondary=build_fusion(saved['secondary'])
            def forward(self,image,context):
                weight=saved['secondary_weight']
                probabilities=(1-weight)*self.primary(image,context).softmax(1)+weight*self.secondary(image,context).softmax(1)
                return torch.log(probabilities.clamp_min(1e-10))
        return Blend()
    if saved['model_type']=='CNNContextFusionV2':
        from .tuned_architectures import create_fusion
        model=create_fusion(saved['backbone'],saved['hidden'],saved['dropout'])
    else:
        model=FusionNet.create()
    model.load_state_dict(saved['state_dict'],strict=True)
    return model


class RealModelProvider:
    def __init__(self):
        self._lock = threading.Lock()
        self._tabular = None
        self._tabular_saved = None
        self._fusion = None
        self._fusion_saved = None
        self._device = None

    @property
    def device_label(self) -> str:
        if self._device is not None:
            return str(self._device)
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "unavailable"

    def _device_for_inference(self):
        import torch
        if self._device is None:
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return self._device

    def load_tabular(self) -> None:
        if self._tabular is not None:
            return
        with self._lock:
            if self._tabular is not None:
                return
            import torch
            if not MULTIDATA_CHECKPOINT.exists():
                raise FileNotFoundError("Real multi-data checkpoint is not installed.")
            saved = torch.load(MULTIDATA_CHECKPOINT, map_location=self._device_for_inference(), weights_only=False)
            model = GradeMLP.create(saved["n_features"], saved["hidden"], saved["dropout"])
            model.load_state_dict(saved["state_dict"], strict=True)
            self._tabular = model.eval().to(self._device)
            self._tabular_saved = saved

    def analyze_tabular(self, supplied: dict[str, float]) -> dict:
        import torch
        self.load_tabular()
        saved = self._tabular_saved
        values = np.asarray([float(supplied.get(name, float("nan"))) for name in saved["features"]], dtype=np.float32)
        medians = np.asarray(saved["medians"], dtype=np.float32)
        missing=~np.isfinite(values)
        raw_values=values.copy()
        values[missing] = medians[missing]
        values = (values - np.asarray(saved["means"], dtype=np.float32)) / np.asarray(saved["stds"], dtype=np.float32)
        with torch.inference_mode():
            probabilities = self._tabular(torch.tensor(values, dtype=torch.float32, device=self._device).unsqueeze(0)).softmax(dim=1)[0].cpu().tolist()
        if saved.get('model_type')=='GradeBlendV2':
            from .tuned_architectures import tree_probabilities
            tree=tree_probabilities(saved['tree'],raw_values)[0]
            weight=saved['tree_weight']
            probabilities=((1-weight)*np.asarray(probabilities)+weight*tree).tolist()
        rows = {name: round(float(value), 6) for name, value in zip(saved["labels"], probabilities)}
        top = max(rows, key=rows.get)
        return {
            "status": "ok", "model_id": saved.get('model_id',"cataract_grade_multidata_real_v1"), "model_scope": "real retrospective tabular research data",
            "probabilities": rows, "top_class": top, "confidence": rows[top], "device": self.device_label,
            "uncertainty_warning": bool(rows[top] < 0.60 or missing.sum()>len(missing)*.25), "requires_clinician_review": True, "clinical_priority": None,
            "missing_feature_count":int(missing.sum()),"input_completeness_warning":"Many training inputs were not supplied. Full-record benchmark accuracy does not establish accuracy for this incomplete input." if missing.sum()>len(missing)*.25 else None,
        }

    def load_fusion(self) -> None:
        if self._fusion is not None:
            return
        with self._lock:
            if self._fusion is not None:
                return
            import torch
            if not FUSION_CHECKPOINT.exists():
                raise FileNotFoundError("Real CatScreen fusion checkpoint is not installed.")
            saved = torch.load(FUSION_CHECKPOINT, map_location=self._device_for_inference(), weights_only=False)
            model = build_fusion(saved)
            self._fusion = model.eval().to(self._device)
            self._fusion_saved = saved

    @staticmethod
    def _context_vector(context: dict) -> np.ndarray:
        eye = str(context.get("eye_side", "Not recorded")).title()
        quality = str(context.get("image_quality", "Good")).strip().title()
        if quality == "Very Good": quality = "Very good"
        illumination = str(context.get("slit_lamp_illumination_type", "Diffuse Illumination")).strip()
        reflection = float(context.get("reflection", 0))
        return np.asarray([
            float(eye == "Left"), float(eye == "Right"), reflection,
            float(quality == "Poor"), float(quality == "Good"), float(quality == "Very good"),
            float(illumination == "Diffuse Illumination"), float(illumination == "Direct Focal Illumination"),
            float(illumination == "Retro Illumination"),
        ], dtype=np.float32)

    def analyze_fusion(self, payload: bytes, modality: str, context: dict | None = None) -> dict:
        image, quality = validate_image_bytes(payload)
        if modality != "slit_lamp":
            return {"status": "not_available", "reason": "The real CatScreen model accepts slit-lamp photographs only.", "technical_quality": quality, "urgency": None}
        self.load_fusion()
        import torch
        from torchvision.transforms import v2
        saved = self._fusion_saved
        transform = v2.Compose([
            v2.Resize((int(saved["image_size"]), int(saved["image_size"]))), v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=saved["normalization_mean"], std=saved["normalization_std"]),
        ])
        input_context = dict(context or {})
        unknown_eye = input_context.get("eye_side") not in {"Left", "Right"}
        if unknown_eye:
            input_context["eye_side"] = "Not recorded"
        if "image_quality" not in input_context:
            input_context["image_quality"] = "Poor" if quality["technical_warning"] else "Good"
        tensor = transform(image).unsqueeze(0).to(self._device)
        # The trained network uses Left/Right one-hot inputs. For an unknown
        # side, average both valid context hypotheses rather than inventing a
        # label or passing an unseen all-zero laterality vector.
        contexts = [{**input_context, "eye_side": side} for side in ("Left", "Right")] if unknown_eye else [input_context]
        context_tensor = torch.from_numpy(np.stack([self._context_vector(ctx) for ctx in contexts])).to(self._device)
        with torch.inference_mode():
            probabilities = self._fusion(tensor.expand(len(contexts), -1, -1, -1), context_tensor).softmax(dim=1).mean(dim=0).cpu().tolist()
        rows = {name: round(float(value), 6) for name, value in zip(saved["classes"], probabilities)}
        top = max(rows, key=rows.get)
        return {
            "status": "ok", "model_id": saved.get('model_id',"clinical_fusion_catscreen_real_v1"), "model_scope": "CatScreen real public sample",
            "probabilities": rows, "top_class": top, "confidence": rows[top], "device": self.device_label,
            "uncertainty_warning": rows[top] < 0.65, "technical_quality": quality, "context_used": input_context,
            "laterality_unknown": unknown_eye,
            "laterality_note": "Eye side unknown: averaged left/right context predictions; this does not identify the eye. Unknown-side performance has not been separately validated." if unknown_eye else "Eye side supplied by the uploader; not inferred from the photograph.",
            "reason": None, "urgency": None, "clinical_priority": None, "requires_clinician_review": True,
            "sample_limit_warning": "Research-only diagnostic screening model trained on 200 public-snapshot images without the full patient metadata."+(" Historical normal-class recall is only 25% (2 of 8 normal test images). A model score cannot provide clinical reassurance." if saved.get('model_id')=='clinical_fusion_catscreen_real_v2' else ''),
        }


real_provider = RealModelProvider()
