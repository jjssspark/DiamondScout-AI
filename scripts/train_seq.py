"""GRU 시퀀스 모델 학습 + numpy 서빙용 가중치 내보내기.

enriched parquet의 lag 컬럼을 (n, SEQ_LEN, n_feat) 시퀀스로 되돌려 학습한다.
t=0이 lag5(가장 오래된 투구), t=SEQ_LEN-1이 lag1(직전 투구)이다.

평가는 Keras가 아니라 numpy 추론기(SeqPredictor)로 한다. 실제 서빙이 쓰는 경로로
재야 의미가 있다 - Keras로 재고 numpy로 서빙하면 둘이 갈려도 알 수 없다.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TS-010: keras(TensorFlow)를 pandas/pyarrow보다 먼저 import 해야 한다. 순서를 바꾸지 말 것.
# 둘 다 absl 심볼을 weak definition으로 내보내는데, dyld는 weak 정의를 이미지 간에
# 하나로 합치고 먼저 로드된 쪽이 이긴다. pyarrow가 먼저 로드되면 TF가 Arrow판 absl
# 뮤텍스를 쓰게 되고, 첫 eager 연산에서 깨어나지 않는 락을 기다린다 - 예외도 없고
# CPU도 0%라 원인을 짐작하기 어렵다.
import keras  # noqa: F401  (부작용을 위한 import: TF를 pyarrow보다 먼저 로드시킨다)

import numpy as np
import pandas as pd
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import TARGET_COL
from models.seq_infer import SeqPredictor
from models.seq_next_pitch import SEQ_LEN, build_model, export_weights

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025

SEQ_FIELDS = [
    "pitch_label_id", "release_speed", "pfx_x", "pfx_z",
    "plate_x", "plate_z", "zone_cell", "balls", "strikes",
]


def to_sequences(df: pd.DataFrame) -> np.ndarray:
    """lag 컬럼을 (n, SEQ_LEN, n_feat)로 되돌린다. 시간 순서대로 lag5 -> lag1."""
    steps = [
        df[[f"{field}_lag{lag}" for field in SEQ_FIELDS]].to_numpy(dtype="float32")
        for lag in range(SEQ_LEN, 0, -1)
    ]
    return np.stack(steps, axis=1)


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def main() -> None:
    from keras import callbacks

    processed = os.path.join(ROOT, "data", "processed")
    splits = {
        name: pd.read_parquet(os.path.join(processed, f"enriched_{name}_{YEAR}.parquet"))
        for name in ("train", "val", "test")
    }
    labels = sorted(splits["train"][TARGET_COL].unique())

    X = {name: to_sequences(df) for name, df in splits.items()}
    y = {name: df[TARGET_COL].to_numpy() for name, df in splits.items()}

    # 표준화 통계는 train에서만 뽑는다. val/test로 계산하면 누수다.
    flat = X["train"].reshape(-1, len(SEQ_FIELDS))
    mean = flat.mean(axis=0)
    std = np.where(flat.std(axis=0) == 0, 1.0, flat.std(axis=0))
    for name in X:
        X[name] = (X[name] - mean) / std

    print(f"[학습] {X['train'].shape} / {len(labels)}클래스", flush=True)

    model = build_model(SEQ_LEN, len(SEQ_FIELDS), len(labels), units=64)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])

    started = time.perf_counter()
    model.fit(
        X["train"], y["train"],
        validation_data=(X["val"], y["val"]),
        epochs=20, batch_size=512, verbose=2,
        callbacks=[callbacks.EarlyStopping(patience=3, restore_best_weights=True, monitor="val_loss")],
    )
    elapsed = time.perf_counter() - started

    npz_path = os.path.join(ROOT, "models", "seq_model_weights.npz")
    export_weights(model, npz_path, mean=mean, std=std)
    size_mb = os.path.getsize(npz_path) / (1024 * 1024)

    # 서빙 경로(numpy)로 평가한다. 입력은 이미 표준화했으므로 predict_proba에 그대로 넣는다.
    predictor = SeqPredictor(npz_path)
    v1, v3 = _topk(y["val"], predictor.predict_proba(X["val"]), labels)
    t1, t3 = _topk(y["test"], predictor.predict_proba(X["test"]), labels)
    print(f"[검증] top1={v1:.4f} top3={v3:.4f}", flush=True)
    print(f"[테스트] top1={t1:.4f} top3={t3:.4f}", flush=True)
    print(f"[저장] {npz_path} ({size_mb:.2f}MB, 학습 {elapsed:.0f}s)", flush=True)

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"seq_metrics_{YEAR}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "seq_len": SEQ_LEN, "n_features": len(SEQ_FIELDS), "units": 64,
            "train_seconds": elapsed, "model_size_mb": size_mb,
            "evaluated_with": "numpy SeqPredictor (서빙 경로)",
            "validation": {"top1_accuracy": v1, "top3_accuracy": v3, "n_samples": len(y["val"])},
            "test": {"top1_accuracy": t1, "top3_accuracy": t3, "n_samples": len(y["test"])},
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
