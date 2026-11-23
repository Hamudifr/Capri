"""Experimental multi-horizon XAUUSD temporal classifier.

UNTRAINED research architecture only. No data fetching, order placement, or
performance claim. Install optional PyTorch before importing this module.
"""
from __future__ import annotations

import torch
from torch import nn


class GoldTemporalNet(nn.Module):
    """Transformer encoder with attention pooling and multi-horizon heads.

    Input:  float tensor [batch, sequence_length, feature_count]
    Output: logits [batch, horizon_count, 3] for DOWN / FLAT / UP.

    Inputs must be point-in-time features. The caller must prevent publication
    timestamp leakage and construct sequences in strict chronological order.
    """

    def __init__(
        self,
        feature_count: int,
        horizon_count: int = 4,
        d_model: int = 64,
        n_heads: int = 4,
        layers: int = 2,
        max_sequence_length: int = 256,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        if feature_count < 1 or horizon_count < 1:
            raise ValueError("feature_count and horizon_count must be positive")
        if d_model % n_heads:
            raise ValueError("d_model must be divisible by n_heads")
        if max_sequence_length < 2 or layers < 1:
            raise ValueError("sequence length must be >= 2 and layers >= 1")
        self.feature_count = feature_count
        self.horizon_count = horizon_count
        self.max_sequence_length = max_sequence_length
        self.input_norm = nn.LayerNorm(feature_count)
        self.input_projection = nn.Linear(feature_count, d_model)
        self.position_embedding = nn.Parameter(torch.zeros(1, max_sequence_length, d_model))
        nn.init.normal_(self.position_embedding, mean=0.0, std=0.02)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 2,
            dropout=dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            layer, num_layers=layers, enable_nested_tensor=False
        )
        self.pool_score = nn.Sequential(
            nn.Linear(d_model, d_model // 2), nn.Tanh(),
            nn.Linear(d_model // 2, 1),
        )
        self.output_norm = nn.LayerNorm(d_model)
        self.heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model // 2), nn.GELU(),
                nn.Dropout(dropout), nn.Linear(d_model // 2, 3),
            )
            for _ in range(horizon_count)
        ])

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if features.ndim != 3:
            raise ValueError("features must have shape [batch, time, features]")
        if features.shape[-1] != self.feature_count:
            raise ValueError("unexpected feature count")
        if not 1 <= features.shape[1] <= self.max_sequence_length:
            raise ValueError("invalid sequence length")
        if not torch.is_floating_point(features):
            raise TypeError("features must be floating-point")
        x = self.input_projection(self.input_norm(features))
        x = x + self.position_embedding[:, :x.shape[1], :]
        x = self.encoder(x)
        weights = torch.softmax(self.pool_score(x).squeeze(-1), dim=1)
        pooled = self.output_norm(torch.sum(x * weights.unsqueeze(-1), dim=1))
        return torch.stack([head(pooled) for head in self.heads], dim=1)


def class_probabilities(logits: torch.Tensor) -> torch.Tensor:
    """Return DOWN / FLAT / UP probabilities for every forecast horizon."""
    if logits.ndim != 3 or logits.shape[-1] != 3:
        raise ValueError("logits must have shape [batch, horizons, 3]")
    return torch.softmax(logits, dim=-1)
