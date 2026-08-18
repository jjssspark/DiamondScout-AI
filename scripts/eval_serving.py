"""서빙 구성에서의 실제 정확도를 잰다. LightGBM 단독 vs GRU 앙상블.

전 피처를 실측한 값(test top1 43.71%)은 앱이 낼 수 있는 수치가 아니다. 앱이 받는 건
볼카운트와 합성한 최근 5구뿐이라 세 피처를 관측할 수 없고 train 대표값으로 고정한다.
그 상태에서도 앙상블 이득이 남는지 확인해야 서빙에 넣은 의미가 있다.

services/prediction_service.py와 같은 규칙으로 입력을 만든다:
- pitcher_pitch_count_game / times_through_order / prev_pitch_outcome_enc -> 고정값
- pitch_of_atbat -> balls + strikes + 1 로 근사
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import TARGET_COL
from models.seq_infer import SeqPredictor
from models.seq_next_pitch import SEQ_LEN
from services.prediction_service import LAG_FIELDS, SEQ_ENSEMBLE_WEIGHT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def _mcnemar(y, proba_a, proba_b):
    ok_a, ok_b = proba_a.argmax(axis=1) == y, proba_b.argmax(axis=1) == y
    b, c = int((ok_a & ~ok_b).sum()), int((~ok_a & ok_b).sum())
    if b + c == 0:
        return {"only_solo": b, "only_ensemble": c, "p_value": 1.0}
    stat = (abs(b - c) - 1) ** 2 / (b + c)
    return {"only_solo": b, "only_ensemble": c, "chi2": float(stat),
            "p_value": float(stats.chi2.sf(stat, 1))}


def to_serving_frame(df: pd.DataFrame, defaults: dict) -> pd.DataFrame:
    """앱이 실제로 넣을 수 있는 값만 남긴 입력을 만든다."""
    out = df.copy()
    for col, value in defaults.items():
        out[col] = value
    out["pitch_of_atbat"] = out["balls"] + out["strikes"] + 1
    return out


def to_sequences(df: pd.DataFrame) -> np.ndarray:
    steps = [
        df[[f"{field}_lag{lag}" for field in LAG_FIELDS]].to_numpy(dtype="float32")
        for lag in range(SEQ_LEN, 0, -1)
    ]
    return np.stack(steps, axis=1)


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    models_dir = os.path.join(ROOT, "models")
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    booster = lgb.Booster(model_file=os.path.join(models_dir, "next_pitch_lgbm.txt"))
    with open(os.path.join(models_dir, "next_pitch_lgbm_features.json"), encoding="utf-8") as f:
        feature_cols = json.load(f)["feature_cols"]
    with open(os.path.join(models_dir, "serving_priors", "temporal_defaults.json"), encoding="utf-8") as f:
        defaults = json.load(f)
    predictor = SeqPredictor(os.path.join(models_dir, "seq_model_weights.npz"))

    labels = sorted(test[TARGET_COL].unique())
    y = test[TARGET_COL].to_numpy()
    served = to_serving_frame(test, defaults)

    full = booster.predict(test[feature_cols])
    solo = booster.predict(served[feature_cols])
    gru = predictor.predict_proba(predictor.standardize(to_sequences(served)))
    w = SEQ_ENSEMBLE_WEIGHT
    mixed = (1 - w) * solo + w * gru

    rows = {
        "전 피처 실측 (단독)": _topk(y, full, labels),
        "서빙 구성 (단독)": _topk(y, solo, labels),
        f"서빙 구성 (앙상블 w={w})": _topk(y, mixed, labels),
    }
    for name, (t1, t3) in rows.items():
        print(f"{name:28s} top1={t1:.4f} top3={t3:.4f}")

    mc = _mcnemar(y, solo, mixed)
    d1 = rows[f"서빙 구성 (앙상블 w={w})"][0] - rows["서빙 구성 (단독)"][0]
    print(f"[차이] top1 {d1:+.4f} / 단독만 맞힘 {mc['only_solo']:,} "
          f"앙상블만 맞힘 {mc['only_ensemble']:,} p={mc['p_value']:.4g}")

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"serving_accuracy_{YEAR}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "ensemble_weight": w,
            "n_samples": len(test),
            "results": {k: {"top1": v[0], "top3": v[1]} for k, v in rows.items()},
            "delta_top1": d1,
            "mcnemar": mc,
        }, f, ensure_ascii=False, indent=2)
    print(f"[저장] {out}")


if __name__ == "__main__":
    main()
