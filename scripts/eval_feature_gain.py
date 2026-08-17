"""보강 피처의 순수 기여분을 측정한다.

같은 split · 같은 모델(RandomForest)로 기존 피처 vs 보강 피처를 비교한다.
모델 교체(LightGBM) 효과와 섞이지 않게 이 단계를 따로 둔다.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import ID_COLS, RANDOM_STATE, TARGET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025

# prev_pitch_outcome은 문자열 원본이다. 모델은 인코딩된 prev_pitch_outcome_enc를 쓴다.
EXCLUDE = set(ID_COLS) | {TARGET_COL, "prev_pitch_outcome"}
NEW_PREFIXES = ("pitcher_prior_", "count_prior_", "batter_")
NEW_TEMPORAL = {
    "pitch_of_atbat",
    "pitcher_pitch_count_game",
    "times_through_order",
    "same_pitch_streak",
    "prev_pitch_outcome_enc",
    "is_first_pitch_of_ab",
}


def _is_new(col: str) -> bool:
    return col.startswith(NEW_PREFIXES) or col in NEW_TEMPORAL


def _evaluate(train, test, feature_cols):
    """models.next_pitch_model.build_model()과 동일한 하이퍼파라미터로 학습한다.
    피처 외의 조건이 하나라도 다르면 델타가 피처 기여분이 아니게 된다."""
    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=16,
        min_samples_leaf=30,
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )
    model.fit(train[feature_cols], train[TARGET_COL])
    proba = model.predict_proba(test[feature_cols])
    y = test[TARGET_COL]
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=model.classes_)),
        float(top_k_accuracy_score(y, proba, k=3, labels=model.classes_)),
    )


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    train = pd.read_parquet(os.path.join(processed, f"enriched_train_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    all_cols = [c for c in train.columns if c not in EXCLUDE]
    baseline_cols = [c for c in all_cols if not _is_new(c)]

    print(f"[기존] {len(baseline_cols)}피처로 학습 중...", flush=True)
    t0 = time.time()
    b1, b3 = _evaluate(train, test, baseline_cols)
    baseline_sec = time.time() - t0
    print(f"[기존] top1={b1:.4f} top3={b3:.4f} ({baseline_sec:.0f}s)", flush=True)

    print(f"[보강] {len(all_cols)}피처로 학습 중...", flush=True)
    t0 = time.time()
    e1, e3 = _evaluate(train, test, all_cols)
    enriched_sec = time.time() - t0
    print(f"[보강] top1={e1:.4f} top3={e3:.4f} ({enriched_sec:.0f}s)", flush=True)

    result = {
        "n_features_baseline": len(baseline_cols),
        "n_features_enriched": len(all_cols),
        "baseline_top1": b1,
        "baseline_top3": b3,
        "enriched_top1": e1,
        "enriched_top3": e3,
        "delta_top1": e1 - b1,
        "delta_top3": e3 - b3,
        "n_test": int(len(test)),
        "n_train": int(len(train)),
        "fit_seconds": {"baseline": round(baseline_sec, 1), "enriched": round(enriched_sec, 1)},
    }
    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"feature_gain_{YEAR}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[델타] top1 {result['delta_top1']:+.4f} / top3 {result['delta_top3']:+.4f}")
    print(f"[저장] {out_path}")


if __name__ == "__main__":
    main()
