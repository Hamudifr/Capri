"""Chronological trainer for prepared XAUUSD feature CSVs.

Expected CSV: timestamp, close, and numeric point-in-time feature columns.
This trains a research classifier only; it does not backtest execution or trade.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from labels import make_direction_labels
from model import GoldTemporalNet, class_probabilities


class WindowDataset(Dataset):
    def __init__(self, features, labels, endpoints, sequence_length):
        self.features = features
        self.labels = labels
        self.endpoints = np.asarray(endpoints, dtype=np.int64)
        self.sequence_length = sequence_length

    def __len__(self):
        return len(self.endpoints)

    def __getitem__(self, index):
        end = int(self.endpoints[index])
        start = end - self.sequence_length + 1
        x = torch.from_numpy(self.features[start:end + 1].astype(np.float32))
        y = torch.from_numpy(self.labels[end].astype(np.int64))
        return x, y


def chronological_endpoints(row_count, sequence_length, horizons):
    """Create purged train/validation/test endpoints with targets inside split."""
    max_horizon = max(horizons)
    train_cut = int(row_count * 0.70)
    validation_cut = int(row_count * 0.85)
    first = sequence_length - 1
    train = np.arange(first, train_cut - max_horizon, dtype=np.int64)
    validation = np.arange(
        max(first, train_cut + max_horizon),
        validation_cut - max_horizon,
        dtype=np.int64,
    )
    test = np.arange(
        max(first, validation_cut + max_horizon),
        row_count - max_horizon,
        dtype=np.int64,
    )
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("not enough rows for sequence length, horizons and purged splits")
    return train, validation, test, train_cut


def evaluate(model, loader, device):
    model.eval()
    total_loss = 0.0
    total_rows = 0
    correct = None
    counts = None
    criterion = nn.CrossEntropyLoss()
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits.reshape(-1, 3), y.reshape(-1))
            batch = y.shape[0]
            total_loss += float(loss.item()) * batch
            total_rows += batch
            pred = class_probabilities(logits).argmax(dim=-1)
            batch_correct = (pred == y).sum(dim=0)
            if correct is None:
                correct = batch_correct
                counts = torch.full_like(batch_correct, batch)
            else:
                correct += batch_correct
                counts += batch
    return {
        "loss": total_loss / max(total_rows, 1),
        "accuracy_by_horizon": (correct.float() / counts.float()).cpu().tolist(),
        "rows": total_rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--features", required=True,
                        help="comma-separated numeric feature columns")
    parser.add_argument("--sequence-length", type=int, default=64)
    parser.add_argument("--horizons", default="1,4,16,96")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.0005)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="xauusd_model.pt")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    horizons = tuple(int(value) for value in args.horizons.split(","))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons must be positive integers")
    if args.sequence_length < 2 or args.epochs < 1 or args.batch_size < 1:
        raise ValueError("invalid training configuration")

    feature_names = [name.strip() for name in args.features.split(",") if name.strip()]
    if not feature_names:
        raise ValueError("at least one feature is required")
    frame = pd.read_csv(args.csv)
    required = {"timestamp", "close", *feature_names}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    numeric = frame[["close", *feature_names]].apply(pd.to_numeric, errors="raise")
    values = numeric.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("numeric columns contain missing or non-finite values")
    close = numeric["close"].to_numpy(dtype=np.float64)
    raw_features = numeric[feature_names].to_numpy(dtype=np.float64)

    labels, valid = make_direction_labels(close, horizons=horizons)
    if not valid.any():
        raise ValueError("no valid labels")
    train_idx, validation_idx, test_idx, train_cut = chronological_endpoints(
        len(frame), args.sequence_length, horizons
    )
    # The label builder intentionally marks early rows invalid until its
    # trailing-volatility window exists. Never pass its -1 sentinel to loss.
    train_idx = train_idx[valid[train_idx].all(axis=1)]
    validation_idx = validation_idx[valid[validation_idx].all(axis=1)]
    test_idx = test_idx[valid[test_idx].all(axis=1)]
    if min(len(train_idx), len(validation_idx), len(test_idx)) == 0:
        raise ValueError("not enough fully labelled samples after purging")
    # Fit normalization only on the raw training period and freeze it thereafter.
    fit_end = int(train_idx[-1]) + 1
    mean = raw_features[:fit_end].mean(axis=0)
    scale = raw_features[:fit_end].std(axis=0)
    scale[scale < 1e-12] = 1.0
    features = ((raw_features - mean) / scale).astype(np.float32)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = GoldTemporalNet(
        feature_count=len(feature_names),
        horizon_count=len(horizons),
        max_sequence_length=max(args.sequence_length, 2),
    ).to(device)
    train_data = WindowDataset(features, labels, train_idx, args.sequence_length)
    validation_data = WindowDataset(features, labels, validation_idx, args.sequence_length)
    test_data = WindowDataset(features, labels, test_idx, args.sequence_length)
    train_loader = DataLoader(train_data, batch_size=args.batch_size, shuffle=True)
    validation_loader = DataLoader(validation_data, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_data, batch_size=args.batch_size, shuffle=False)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    best_validation = float("inf")
    best_state = None
    patience, stale_epochs = 5, 0
    for epoch in range(args.epochs):
        model.train()
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = criterion(logits.reshape(-1, 3), y.reshape(-1))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
        validation_metrics = evaluate(model, validation_loader, device)
        print(json.dumps({"epoch": epoch + 1, "validation": validation_metrics}))
        if validation_metrics["loss"] < best_validation:
            best_validation = validation_metrics["loss"]
            best_state = {key: value.detach().cpu().clone()
                          for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= patience:
                break

    if best_state is None:
        raise RuntimeError("training did not produce a valid checkpoint")
    model.load_state_dict(best_state)
    test_metrics = evaluate(model, test_loader, device)
    checkpoint = {
        "state_dict": model.state_dict(),
        "feature_names": feature_names,
        "feature_mean": mean.tolist(),
        "feature_scale": scale.tolist(),
        "horizons_bars": list(horizons),
        "sequence_length": args.sequence_length,
        "class_order": ["DOWN", "FLAT", "UP"],
        "validation_loss": best_validation,
        "test_metrics": test_metrics,
        "train_cut_timestamp": frame["timestamp"].iloc[train_cut].isoformat(),
        "warning": "Research-only model; not a trading system or profitability claim.",
    }
    output = Path(args.output)
    torch.save(checkpoint, output)
    print(json.dumps({"saved": str(output), "test": test_metrics, "device": str(device)}))


if __name__ == "__main__":
    main()
