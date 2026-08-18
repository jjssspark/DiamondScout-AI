"""타자 x 구종 피처의 순수 기여분을 측정한다.

같은 parquet · 같은 하이퍼파라미터로 새 33개 컬럼만 넣고 뺀다. 데이터를 다시 만든
전후를 비교하면 전처리 재실행 효과가 섞여서 피처 기여분을 못 가른다.

이 스크립트는 33개 컬럼이 들어 있는 parquet을 전제한다. 기본 파이프라인은 측정
결과에 따라 이 피처를 끄고 만들므로, 재현하려면 먼저 켜서 다시 만들어야 한다:

    ./venv/bin/python data/build_enriched_dataset.py --year 2025 --with-batter-pitch
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import top_k_accuracy_score

from data.feature_builders import batter_pitch_feature_cols
from models.lgbm_next_pitch import get_feature_columns, predict_proba, train_lgbm
from models.next_pitch_model import TARGET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def _mcnemar(y, proba_a, proba_b):
    ok_a = proba_a.argmax(axis=1) == y
    ok_b = proba_b.argmax(axis=1) == y
    b = int((ok_a & ~ok_b).sum())
    c = int((~ok_a & ok_b).sum())
    if b + c == 0:
        return {"only_base": b, "only_new": c, "p_value": 1.0}
    stat = (abs(b - c) - 1) ** 2 / (b + c)
    return {"only_base": b, "only_new": c, "chi2": float(stat),
            "p_value": float(stats.chi2.sf(stat, 1))}


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    train = pd.read_parquet(os.path.join(processed, f"enriched_train_{YEAR}.parquet"))
    val = pd.read_parquet(os.path.join(processed, f"enriched_val_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    labels = sorted(train[TARGET_COL].unique())
    all_cols = get_feature_columns(train)
    new_cols = [c for c in batter_pitch_feature_cols(labels) if c in all_cols]
    base_cols = [c for c in all_cols if c not in set(new_cols)]

    print(f"[구성] 전체 {len(all_cols)}피처 / 새 타자x구종 {len(new_cols)}개 / 기준 {len(base_cols)}개")

    # whiff만 11열로 줄인 변형도 같이 잰다. 33열이 나쁘면 "신호가 없는 것"과
    # "컬럼이 많아 희석된 것"을 구분해야 하는데, 이 둘은 처방이 완전히 다르다.
    whiff_only = [c for c in new_cols if c.startswith("batter_whiff_")]
    variants = (
        ("base", base_cols),
        ("whiff_only_11", base_cols + whiff_only),
        ("with_batter_pitch", all_cols),
    )

    results, proba = {}, {}
    for name, cols in variants:
        t = time.perf_counter()
        booster = train_lgbm(train, val, cols, num_class=len(labels))
        elapsed = time.perf_counter() - t

        proba[name] = {
            "val": predict_proba(booster, val[cols]),
            "test": predict_proba(booster, test[cols]),
        }
        v1, v3 = _topk(val[TARGET_COL], proba[name]["val"], labels)
        t1, t3 = _topk(test[TARGET_COL], proba[name]["test"], labels)
        results[name] = {
            "n_features": len(cols), "best_iteration": booster.best_iteration,
            "train_seconds": elapsed,
            "val": {"top1": v1, "top3": v3}, "test": {"top1": t1, "top3": t3},
        }
        print(f"[{name}] {len(cols)}피처 best_iter={booster.best_iteration} "
              f"val top1={v1:.4f} top3={v3:.4f} / test top1={t1:.4f} top3={t3:.4f} ({elapsed:.0f}s)")

        if name == "with_batter_pitch":
            gain = booster.feature_importance(importance_type="gain")
            total = float(gain.sum())
            share = float(sum(g for c, g in zip(cols, gain) if c in set(new_cols))) / total
            results[name]["batter_pitch_gain_share"] = share
            top = sorted(zip(cols, gain), key=lambda kv: -kv[1])[:5]
            results[name]["top5_gain"] = [{"feature": c, "gain": float(g)} for c, g in top]
            print(f"[중요도] 타자x구종 33개의 gain 비중 = {share * 100:.2f}%")

    y_test = test[TARGET_COL].to_numpy()
    comparisons = {}
    for name, _ in variants:
        if name == "base":
            continue
        mc = _mcnemar(y_test, proba["base"]["test"], proba[name]["test"])
        d1 = results[name]["test"]["top1"] - results["base"]["test"]["top1"]
        comparisons[name] = {"delta_test_top1": d1, "mcnemar_test": mc}
        print(f"[{name} vs base] test top1 {d1:+.4f} / 기준만 맞힘 {mc['only_base']:,} "
              f"신규만 맞힘 {mc['only_new']:,} p={mc['p_value']:.4g}")

    best = max(comparisons.items(), key=lambda kv: kv[1]["delta_test_top1"])
    results["comparisons"] = comparisons
    results["verdict"] = (
        "채택" if best[1]["delta_test_top1"] > 0 and best[1]["mcnemar_test"]["p_value"] < 0.05
        else "미채택"
    )
    print(f"[판정] {results['verdict']} (최선 변형: {best[0]} {best[1]['delta_test_top1']:+.4f})")

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"batter_pitch_gain_{YEAR}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[저장] {out}")


if __name__ == "__main__":
    main()
