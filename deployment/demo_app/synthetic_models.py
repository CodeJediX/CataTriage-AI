from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parents[1]
GRADE_CHECKPOINT = ROOT / "models" / "cataract_grade_synthetic" / "best_model.pth"
FUSION_CHECKPOINT = ROOT / "models" / "clinical_fusion_synthetic" / "best_model.pth"
GRADE_NAMES = ["Grade 0 - clear", "Grade 1 - mild", "Grade 2 - moderate", "Grade 3 - advanced"]
CLINICAL_NAMES = ["age", "visual_acuity_loss", "glare", "contrast_loss", "diabetes", "symptom_duration"]


def generate_synthetic_case(seed: int, grade: int, image_size: int = 64) -> tuple[torch.Tensor, torch.Tensor, Image.Image]:
    """Generate a fictional lens-like pattern and correlated fictional clinical features."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[-1:1:complex(image_size), -1:1:complex(image_size)]
    radius = np.sqrt(x*x + y*y)
    lens = radius < 0.83
    base = 0.07 + 0.035 * rng.normal(size=(image_size, image_size))
    radial = np.clip(1 - radius / .83, 0, 1)
    opacity = np.clip(0.10 + grade * 0.20 + rng.normal(0, .045), .03, .90)
    nucleus = np.exp(-((radius / (.22 + .035 * grade)) ** 2))
    spoke_phase = rng.uniform(0, np.pi)
    spokes = (np.cos(np.arctan2(y, x) * (5 + grade) + spoke_phase) ** 10) * radial
    texture = rng.normal(0, .035 + grade * .012, (image_size, image_size))
    image = base + lens * (0.10 + opacity * (.52 * radial + .32 * nucleus + .12 * spokes) + texture)
    image += np.exp(-(((x + .25) / .13) ** 2 + ((y + .28) / .09) ** 2)) * .20
    image = np.clip(image, 0, 1)
    rgb = np.stack([image * .95, image, image * .90], axis=0).astype("float32")
    age = np.clip((48 + grade * 9 + rng.normal(0, 8) - 30) / 60, 0, 1)
    acuity = np.clip(.08 + grade * .25 + rng.normal(0, .10), 0, 1)
    glare = np.clip(.10 + grade * .24 + rng.normal(0, .12), 0, 1)
    contrast = np.clip(.07 + grade * .26 + rng.normal(0, .10), 0, 1)
    diabetes = float(rng.random() < (.12 + grade * .06))
    duration = np.clip((3 + grade * 8 + rng.normal(0, 5)) / 36, 0, 1)
    clinical = np.array([age, acuity, glare, contrast, diabetes, duration], dtype="float32")
    pil = Image.fromarray((np.moveaxis(rgb, 0, 2) * 255).astype("uint8"), "RGB")
    return torch.from_numpy(rgb), torch.from_numpy(clinical), pil


class GradeCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, 5, stride=2, padding=2), nn.BatchNorm2d(16), nn.SiLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.BatchNorm2d(32), nn.SiLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.SiLU(),
            nn.Conv2d(64, 96, 3, stride=2, padding=1), nn.SiLU(), nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(.15), nn.Linear(96, 4))

    def encode(self, x):
        return self.features(x).flatten(1)

    def forward(self, x):
        return self.classifier(self.features(x))


class FusionCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.image_encoder = GradeCNN().features
        self.clinical_encoder = nn.Sequential(nn.Linear(6, 24), nn.SiLU(), nn.Dropout(.10), nn.Linear(24, 24), nn.SiLU())
        self.classifier = nn.Sequential(nn.Linear(96 + 24, 64), nn.SiLU(), nn.Dropout(.15), nn.Linear(64, 4))

    def forward(self, image, clinical):
        image_features = self.image_encoder(image).flatten(1)
        return self.classifier(torch.cat([image_features, self.clinical_encoder(clinical)], dim=1))


class SyntheticModelProvider:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.grade_model = None
        self.fusion_model = None

    def load(self):
        if self.grade_model is None:
            grade_saved = torch.load(GRADE_CHECKPOINT, map_location=self.device, weights_only=False)
            self.grade_model = GradeCNN().to(self.device)
            self.grade_model.load_state_dict(grade_saved["state_dict"]); self.grade_model.eval()
        if self.fusion_model is None:
            fusion_saved = torch.load(FUSION_CHECKPOINT, map_location=self.device, weights_only=False)
            self.fusion_model = FusionCNN().to(self.device)
            self.fusion_model.load_state_dict(fusion_saved["state_dict"]); self.fusion_model.eval()

    @torch.inference_mode()
    def predict(self, seed: int, synthetic_grade: int) -> dict:
        self.load()
        image, clinical, _ = generate_synthetic_case(seed, synthetic_grade)
        image = image.unsqueeze(0).to(self.device); clinical_gpu = clinical.unsqueeze(0).to(self.device)
        grade_prob = torch.softmax(self.grade_model(image), 1)[0].cpu().numpy()
        fusion_prob = torch.softmax(self.fusion_model(image, clinical_gpu), 1)[0].cpu().numpy()
        return {
            "grade_prediction": int(grade_prob.argmax()), "grade_probabilities": grade_prob.tolist(),
            "fusion_prediction": int(fusion_prob.argmax()), "fusion_probabilities": fusion_prob.tolist(),
            "clinical": dict(zip(CLINICAL_NAMES, [round(float(x), 3) for x in clinical])),
            "device": str(self.device), "synthetic_ground_truth": synthetic_grade,
        }

    def image_png(self, seed: int, synthetic_grade: int) -> bytes:
        _, _, pil = generate_synthetic_case(seed, synthetic_grade)
        buf = io.BytesIO(); pil.resize((512,512), Image.Resampling.NEAREST).save(buf, "PNG")
        return buf.getvalue()


synthetic_provider = SyntheticModelProvider()
