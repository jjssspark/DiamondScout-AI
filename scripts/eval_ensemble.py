"""Task 8 게이트 — LightGBM 단독 vs LightGBM+GRU 앙상블을 val에서 비교한다.

게이트: **val top-1에서 단일 모델(LightGBM)을 못 이기면 채택하지 않는다.**

두 모델의 확률을 가중 평균한다. 가중치는 val에서만 고르고, test는 고른 뒤 한 번만
본다. test로 가중치를 고르면 그 test 수치는 더 이상 일반화 성능이 아니다.

GRU 확률은 학습이 아니라 **서빙 경로(numpy SeqPredictor)**로 뽑는다. Keras로 재고
numpy로 서빙하면 둘이 갈려도 알 수 없다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import TARGET_COL
from models.seq_infer import SeqPredictor
from models.seq_next_pitch import SEQ_LEN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025

SEQ_FIELDS = [
    "pitch_label_id", "release_speed", "pfx_x", "pfx_z",
    "plate_x", "plate_z", "zone_cell", "balls", "strikes",
]
WEIGHTS = [round(float(w), 2) for w in np.arange(0.0, 0.55, 0.05)]


def to_sequences(df: pd.DataFrame) -> np.ndarray:
    steps = [
        df[[f"{field}_lag{lag}" for field in SEQ_FIELDS]].to_numpy(dtype="float32")
        for lag in range(SEQ_LEN, 0, -1)
    ]
    return np.stack(steps, axis=1)


def _mcnemar(y, proba_a, proba_b):
    """앙상블이 단독보다 나은 게 노이즈인지 본다.

    두 모델이 같은 샘플을 예측하므로 독립 표본 비교가 아니라 짝지은 비교다.
    둘 다 맞히거나 둘 다 틀린 샘플은 정보가 없고, 한쪽만 맞힌 샘플만 신호다.
    """
    from scipy import stats

    ok_a = proba_a.argmax(axis=1) == y
    ok_b = proba_b.argmax(axis=1) == y
    b = int((ok_a & ~ok_b).sum())   # a만 맞힘
    c = int((~ok_a & ok_b).sum())   # b만 맞힘
    if b + c == 0:
        return {"only_a": b, "only_b": c, "p_value": 1.0}
    stat = (abs(b - c) - 1) ** 2 / (b + c)
    return {
        "only_a": b, "only_b": c,
        "chi2": float(stat),
        "p_value": float(stats.chi2.sf(stat, 1)),
    }


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    val = pd.read_parquet(os.path.join(processed, f"enriched_val_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    booster = lgb.Booster(model_file=os.path.join(ROOT, "models", "next_pitch_lgbm.txt"))
    with open(os.path.join(ROOT, "models", "next_pitch_lgbm_features.json"), encoding="utf-8") as f:
        feature_cols = json.load(f)["feature_cols"]
    predictor = SeqPredictor(os.path.join(ROOT, "models", "seq_model_weights.npz"))

    labels = sorted(pd.concat([val[TARGET_COL], test[TARGET_COL]]).unique())

    proba = {}
    for name, df in (("val", val), ("test", test)):
        proba[name] = {
            "lgbm": booster.predict(df[feature_cols]),
            "gru": predictor.predict_proba(predictor.standardize(to_sequences(df))),
        }

    y = {"val": val[TARGET_COL].to_numpy(), "test": test[TARGET_COL].to_numpy()}

    l1, l3 = _topk(y["val"], proba["val"]["lgbm"], labels)
    g1, g3 = _topk(y["val"], proba["val"]["gru"], labels)
    print(f"[val 단독] LightGBM top1={l1:.4f} top3={l3:.4f}")
    print(f"[val 단독] GRU      top1={g1:.4f} top3={g3:.4f}")
    print(f"[val 앙상블] p = (1-w)*LightGBM + w*GRU")

    sweep = []
    for w in WEIGHTS:
        blended = (1 - w) * proba["val"]["lgbm"] + w * proba["val"]["gru"]
        b1, b3 = _topk(y["val"], blended, labels)
        sweep.append({"weight": w, "top1": b1, "top3": b3})
        mark = "  <- 단독 초과" if b1 > l1 else ""
        print(f"  w={w:.2f}  top1={b1:.4f} ({b1 - l1:+.4f})  top3={b3:.4f}{mark}")

    best = max(sweep, key=lambda r: r["top1"])
    passed = bool(best["top1"] > l1 and best["weight"] > 0)

    w_best = best["weight"]
    val_blend = (1 - w_best) * proba["val"]["lgbm"] + w_best * proba["val"]["gru"]
    mc_val = _mcnemar(y["val"], proba["val"]["lgbm"], val_blend)
    print()
    print(f"[val McNemar] LightGBM만 맞힘 {mc_val['only_a']:,} / 앙상블만 맞힘 "
          f"{mc_val['only_b']:,} / p={mc_val['p_value']:.4g}")

    print()
    print(f"[게이트] 최고 val top1={best['top1']:.4f} (w={best['weight']:.2f}) "
          f"vs 단독 {l1:.4f} → {'통과' if passed else '탈락'}")

    result = {
        "gate": "val top-1에서 LightGBM 단독을 초과해야 채택",
        "passed": passed,
        "val": {"lgbm": {"top1": l1, "top3": l3}, "gru": {"top1": g1, "top3": g3}},
        "sweep_val": sweep,
        "best_weight": w_best,
        "mcnemar_val": mc_val,
        "n_samples": {"val": len(val), "test": len(test)},
    }

    if passed:
        w = w_best
        blended = (1 - w) * proba["test"]["lgbm"] + w * proba["test"]["gru"]
        t1, t3 = _topk(y["test"], blended, labels)
        tl1, tl3 = _topk(y["test"], proba["test"]["lgbm"], labels)
        print(f"[test] 앙상블 top1={t1:.4f} top3={t3:.4f} / 단독 top1={tl1:.4f} top3={tl3:.4f}")
        mc_test = _mcnemar(y["test"], proba["test"]["lgbm"], blended)
        print(f"[test McNemar] LightGBM만 맞힘 {mc_test['only_a']:,} / 앙상블만 맞힘 "
              f"{mc_test['only_b']:,} / p={mc_test['p_value']:.4g}")
        result["test"] = {
            "ensemble": {"top1": t1, "top3": t3},
            "lgbm": {"top1": tl1, "top3": tl3},
            "mcnemar": mc_test,
        }
    else:
        print("[test] 게이트 탈락이라 test는 보지 않는다.")

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ensemble_gate_{YEAR}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[저장] {out}")


if __name__ == "__main__":
    main()
