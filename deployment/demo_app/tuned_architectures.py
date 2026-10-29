"""Versioned research architectures shared by GPU training and hosted inference."""
import numpy as np


def tabular_features(values, medians):
    values = np.asarray(values, dtype=np.float32).copy()
    if values.ndim == 1:
        values = values[None, :]
    missing = ~np.isfinite(values)
    values[missing] = np.broadcast_to(np.asarray(medians, dtype=np.float32), values.shape)[missing]
    derived = []
    for a, b in ((2, 4), (3, 5), (6, 16)):
        derived.extend([np.minimum(values[:, a], values[:, b]), np.maximum(values[:, a], values[:, b]), np.abs(values[:, a]-values[:, b])])
    return np.concatenate([values, missing.astype(np.float32), np.stack(derived, axis=1)], axis=1)


def tree_probabilities(saved, values):
    x = tabular_features(values, saved['medians'])
    scores = np.tile(np.asarray(saved['tree_bias'], dtype=np.float64), (len(x), 1))
    summed = np.zeros_like(scores)
    for tree in saved['trees']:
        leaves = np.zeros(len(x), dtype=np.int64)
        for bit, (feature, border) in enumerate(zip(tree['features'], tree['borders'])):
            leaves |= (x[:, feature] > border).astype(np.int64) << bit
        summed += np.asarray(tree['values'], dtype=np.float64)[leaves]
    scores += float(saved['tree_scale']) * summed
    scores -= scores.max(axis=1, keepdims=True)
    probs = np.exp(scores)
    return probs / probs.sum(axis=1, keepdims=True)


def create_fusion(backbone_name, hidden=0, dropout=.4, pretrained=False):
    import torch
    from torch import nn
    from torchvision import models

    class Fusion(nn.Module):
        def __init__(self):
            super().__init__()
            constructors = {
                'mobilenet_v3_small': (models.mobilenet_v3_small, models.MobileNet_V3_Small_Weights.DEFAULT, 576),
                'efficientnet_b0': (models.efficientnet_b0, models.EfficientNet_B0_Weights.DEFAULT, 1280),
                'resnet18': (models.resnet18, models.ResNet18_Weights.DEFAULT, 512),
            }
            constructor, weights, dim = constructors[backbone_name]
            self.encoder = constructor(weights=weights if pretrained else None)
            if backbone_name == 'resnet18':
                self.encoder.fc = nn.Identity()
            else:
                self.encoder.classifier = nn.Identity()
            self.context = nn.Sequential(nn.Linear(9, 16), nn.LayerNorm(16), nn.GELU(), nn.Dropout(dropout))
            self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(dim+16, 3)) if not hidden else nn.Sequential(nn.Linear(dim+16, hidden), nn.LayerNorm(hidden), nn.GELU(), nn.Dropout(dropout), nn.Linear(hidden, 3))

        def from_features(self, features, context):
            return self.head(torch.cat([features, self.context(context)], dim=1))

        def forward(self, images, context):
            return self.from_features(self.encoder(images), context)

    return Fusion()
