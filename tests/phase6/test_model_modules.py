from __future__ import annotations

import builtins
from pathlib import Path
import sys
from types import ModuleType

import pandas as pd
import pytest

from execution.phase6.models import deep_models, meta_ensemble, regime_model, tree_models


def _sample_labeled_frame(rows: int = 40, symbol: str = "BTC") -> pd.DataFrame:
    label_h24 = [0.03 if idx % 2 == 0 else -0.03 for idx in range(rows)]
    return pd.DataFrame(
        {
            "symbol": [symbol] * rows,
            "roll_vol_32": [0.1] * rows,
            "roll_liq_32": [1.0] * rows,
            "order_flow_32": [0.2] * rows,
            "label_ret_H1": [0.01] * rows,
            "label_ret_H4": [0.02] * rows,
            "label_ret_H24": label_h24,
        }
    )


def test_tree_dependency_checks_and_training(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _missing_xgboost(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "xgboost":
            raise ImportError("xgboost")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_xgboost)
    with pytest.raises(RuntimeError, match="xgboost"):
        tree_models._assert_tree_dependencies()
    monkeypatch.undo()

    monkeypatch.setitem(sys.modules, "xgboost", ModuleType("xgboost"))
    monkeypatch.setitem(sys.modules, "lightgbm", ModuleType("lightgbm"))
    tree_models._assert_tree_dependencies()

    frame = _sample_labeled_frame(rows=20)
    artifacts = tree_models.train_tree_specialists(
        labeled_frame=frame,
        symbols=("BTC", "ETH"),
        output_dir=tmp_path,
        seed=11,
    )
    assert len(artifacts) == 1
    assert artifacts[0].artifact_path.exists()

    with pytest.raises(RuntimeError, match="No tree specialists trained"):
        tree_models.train_tree_specialists(
            labeled_frame=frame,
            symbols=("ETH",),
            output_dir=tmp_path / "none",
            seed=11,
        )


def test_tree_training_import_error_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tree_models, "_assert_tree_dependencies", lambda: None)
    original_import = builtins.__import__

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "numpy":
            raise ImportError("numpy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)
    with pytest.raises(RuntimeError, match="Missing required dependency for tree specialist training"):
        tree_models.train_tree_specialists(
            labeled_frame=_sample_labeled_frame(rows=10),
            symbols=("BTC",),
            output_dir=tmp_path,
            seed=1,
        )


class _FakeTensor:
    def __init__(self, data, value: float = 0.0) -> None:  # type: ignore[no-untyped-def]
        self._data = data
        self.shape = getattr(data, "shape", (len(data), 1))
        self._value = value

    def unsqueeze(self, _dim: int) -> "_FakeTensor":
        return self

    def detach(self) -> "_FakeTensor":
        return self

    def cpu(self) -> "_FakeTensor":
        return self

    def item(self) -> float:
        return self._value

    def backward(self) -> None:
        return None


class _FakeModel:
    def cuda(self) -> "_FakeModel":
        return self

    def parameters(self):  # type: ignore[no-untyped-def]
        return []

    def __call__(self, _x):  # type: ignore[no-untyped-def]
        return _FakeTensor([[0.0]], value=0.123)

    def state_dict(self):  # type: ignore[no-untyped-def]
        return {"w": 1}


class _FakeTorch:
    float32 = "float32"

    class cuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class nn:
        @staticmethod
        def Linear(_a, _b):  # type: ignore[no-untyped-def]
            return object()

        @staticmethod
        def ReLU():  # type: ignore[no-untyped-def]
            return object()

        @staticmethod
        def Sequential(*_layers):  # type: ignore[no-untyped-def]
            return _FakeModel()

        class MSELoss:
            def __call__(self, _pred, _y):  # type: ignore[no-untyped-def]
                return _FakeTensor([[0.0]], value=0.456)

    class optim:
        class Adam:
            def __init__(self, _params, lr):  # type: ignore[no-untyped-def]
                self.lr = lr

            def zero_grad(self) -> None:
                return None

            def step(self) -> None:
                return None

    @staticmethod
    def manual_seed(_seed: int) -> None:
        return None

    @staticmethod
    def tensor(data, dtype=None, device=None):  # type: ignore[no-untyped-def]
        return _FakeTensor(data, value=0.123)

    @staticmethod
    def save(state, path):  # type: ignore[no-untyped-def]
        Path(path).write_text(str(state), encoding="utf-8")


class _FakeTorchNoCuda(_FakeTorch):
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False


def test_deep_models_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _missing_torch(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "torch":
            raise ImportError("torch")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_torch)
    with pytest.raises(RuntimeError, match="deep-model dependency: torch"):
        deep_models._load_torch()
    monkeypatch.undo()

    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    assert deep_models._load_torch() is sys.modules["torch"]
    monkeypatch.delitem(sys.modules, "torch", raising=False)

    monkeypatch.setattr(deep_models, "_load_torch", lambda: _FakeTorchNoCuda())
    with pytest.raises(RuntimeError, match="requires CUDA"):
        deep_models.assert_cuda_available()

    torch = _FakeTorch()
    model, mse = deep_models._train_linear_regression(torch, [[1.0, 2.0, 3.0]], [0.1], seed=7)
    assert model is not None
    assert mse >= 0

    monkeypatch.setattr(deep_models, "_load_torch", lambda: torch)
    frame_small = _sample_labeled_frame(rows=10)
    with pytest.raises(RuntimeError, match="No deep specialists trained"):
        deep_models.train_deep_specialists(labeled_frame=frame_small, symbols=("BTC",), output_dir=tmp_path, seed=1)

    frame = _sample_labeled_frame(rows=40)
    artifacts = deep_models.train_deep_specialists(labeled_frame=frame, symbols=("BTC", "ETH"), output_dir=tmp_path, seed=1)
    assert len(artifacts) == 1
    assert artifacts[0].artifact_path.exists()


def test_deep_training_numpy_import_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _patched(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "numpy":
            raise ImportError("numpy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)
    with pytest.raises(RuntimeError, match="numpy is required"):
        deep_models.train_deep_specialists(labeled_frame=_sample_labeled_frame(), symbols=("BTC",), output_dir=tmp_path, seed=1)


def test_regime_and_meta_models(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No rows available"):
        regime_model.train_regime_classifier(labeled_frame=_sample_labeled_frame(rows=0), output_dir=tmp_path, seed=1)

    regime = regime_model.train_regime_classifier(labeled_frame=_sample_labeled_frame(rows=20), output_dir=tmp_path, seed=1)
    assert regime.artifact_path.exists()
    assert regime.train_rows == 20

    with pytest.raises(RuntimeError, match="required column"):
        meta_ensemble.train_meta_ensemble(oof_frame=pd.DataFrame({"pred_tree": [0.1]}), output_dir=tmp_path, seed=1)

    with pytest.raises(RuntimeError, match="No OOF rows"):
        meta_ensemble.train_meta_ensemble(
            oof_frame=pd.DataFrame(columns=["pred_tree", "pred_deep", "pred_regime", "target"]),
            output_dir=tmp_path,
            seed=1,
        )

    oof = pd.DataFrame(
        {
            "pred_tree": [0.1, 0.2, 0.3],
            "pred_deep": [0.2, 0.3, 0.4],
            "pred_regime": [0.3, 0.4, 0.5],
            "target": [0.15, 0.25, 0.35],
        }
    )
    meta = meta_ensemble.train_meta_ensemble(oof_frame=oof, output_dir=tmp_path, seed=1)
    assert meta.artifact_path.exists()
    assert meta.train_rows == 3


def test_regime_and_meta_import_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_import = builtins.__import__

    def _patched_meta(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "joblib":
            raise ImportError("joblib")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched_meta)
    with pytest.raises(RuntimeError, match="meta ensemble"):
        meta_ensemble.train_meta_ensemble(
            oof_frame=pd.DataFrame({"pred_tree": [0.1], "pred_deep": [0.2], "pred_regime": [0.3], "target": [0.1]}),
            output_dir=tmp_path,
            seed=1,
        )

    monkeypatch.undo()

    def _patched_regime(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "joblib":
            raise ImportError("joblib")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched_regime)
    with pytest.raises(RuntimeError, match="regime classifier"):
        regime_model.train_regime_classifier(labeled_frame=_sample_labeled_frame(rows=2), output_dir=tmp_path, seed=1)
