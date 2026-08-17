"""보강 피처 데이터로 LightGBM을 학습하고 val/test 성능·모델 크기를 기록한다."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sklearn.metrics import top_k_accuracy_score

from models.lgbm_next_pitch import get_feature_columns, predict_proba, save_model, train_lgbm
from models.next_pitch_model import TARGET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    train = pd.read_parquet(os.path.join(processed, f"enriched_train_{YEAR}.parquet"))
    val = pd.read_parquet(os.path.join(processed, f"enriched_val_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    feature_cols = get_feature_columns(train)
    labels = sorted(train[TARGET_COL].unique())
    print(f"[학습] {len(feature_cols)}피처 / {len(labels)}클래스 / train {len(train):,}행", flush=True)

    started = time.perf_counter()
    booster = train_lgbm(train, val, feature_cols, num_class=len(labels))
    elapsed = time.perf_counter() - started
    print(f"[학습] 완료 {elapsed:.1f}s / best_iteration={booster.best_iteration}", flush=True)

    v1, v3 = _topk(val[TARGET_COL], predict_proba(booster, val[feature_cols]), labels)
    t1, t3 = _topk(test[TARGET_COL], predict_proba(booster, test[feature_cols]), labels)
    print(f"[검증] top1={v1:.4f} top3={v3:.4f}", flush=True)
    print(f"[테스트] top1={t1:.4f} top3={t3:.4f}", flush=True)

    path = save_model(booster, feature_cols, ROOT)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"[저장] {path} ({size_mb:.2f}MB)", flush=True)

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"lgbm_metrics_{YEAR}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "n_features": len(feature_cols), "best_iteration": booster.best_iteration,
            "train_seconds": elapsed, "model_size_mb": size_mb,
            "validation": {"top1_accuracy": v1, "top3_accuracy": v3, "n_samples": len(val)},
            "test": {"top1_accuracy": t1, "top3_accuracy": t3, "n_samples": len(test)},
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
