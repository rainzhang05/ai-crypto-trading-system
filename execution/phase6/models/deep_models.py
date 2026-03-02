"""Sequence-model specialist training for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class DeepModelArtifact:
    """Trained deep-model artifact metadata."""

    symbol: str
    family: str
    artifact_path: Path
    train_rows: int
    metric_mse: float



def _load_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Missing required deep-model dependency: torch") from exc
    return torch



def assert_cuda_available() -> None:
    """Fail-hard when CUDA is unavailable for configured deep training."""
    torch = _load_torch()
    if not torch.cuda.is_available():
        raise RuntimeError("Configured deep training requires CUDA, but no CUDA device is available")



def _train_linear_regression(torch, x_np, y_np, seed: int) -> tuple[object, float]:
    torch.manual_seed(seed)
    x = torch.tensor(x_np, dtype=torch.float32, device="cuda")
    y = torch.tensor(y_np, dtype=torch.float32, device="cuda").unsqueeze(1)

    model = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 16), torch.nn.ReLU(), torch.nn.Linear(16, 1)).cuda()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = torch.nn.MSELoss()

    for _ in range(20):
        optimizer.zero_grad()
        pred = model(x)
        loss = loss_fn(pred, y)
        loss.backward()
        optimizer.step()

    mse = float(loss_fn(model(x), y).detach().cpu().item())
    return model, mse



def train_deep_specialists(
    *,
    labeled_frame,
    symbols: Sequence[str],
    output_dir: Path,
    seed: int,
) -> tuple[DeepModelArtifact, ...]:
    """Train deterministic LSTM/Transformer placeholders on CUDA."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for deep specialist training") from exc

    torch = _load_torch()
    assert_cuda_available()

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[DeepModelArtifact] = []

    for symbol in sorted(symbols):
        symbol_frame = labeled_frame[labeled_frame["symbol"] == symbol]
        if symbol_frame.empty:
            continue
        x_np = symbol_frame[["roll_vol_32", "roll_liq_32", "order_flow_32"]].to_numpy(dtype=np.float32)
        y_np = symbol_frame["label_ret_H4"].to_numpy(dtype=np.float32)
        if len(x_np) < 32:
            continue

        model, mse = _train_linear_regression(torch, x_np, y_np, seed)
        artifact_path = output_dir / f"{symbol.lower()}_deep_seq.pt"
        torch.save(model.state_dict(), artifact_path)
        artifacts.append(
            DeepModelArtifact(
                symbol=symbol,
                family="SEQUENCE_DEEP",
                artifact_path=artifact_path,
                train_rows=int(len(symbol_frame)),
                metric_mse=mse,
            )
        )

    if not artifacts:
        raise RuntimeError("No deep specialists trained; insufficient rows per symbol")

    return tuple(artifacts)
