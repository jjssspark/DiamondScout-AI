"""서빙 확률에 온도 스케일링을 적합한다.

val에서 T를 찾고 test에서 ECE가 실제로 줄었는지 확인한다. 줄지 않으면 적용하지
않고 T=1.0으로 기록한다. 온도 스케일링은 순위를 안 바꾸므로 top-k 정확도는
전후가 같아야 한다 - 같지 않으면 구현이 잘못된 것이다.

캘리브레이션 대상은 서빙이 실제로 내보내는 확률, 즉 LightGBM + GRU 앙상블이다.
LightGBM 단독에 맞춰 놓고 앙상블을 내보내면 맞춰 놓은 의미가 없다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# app.py와 같은 이유. 기본 폰트에 한글 글리프가 없어 축·범례가 빈 네모로 나온다.
plt.rcParams["font.family"] = ["AppleGothic", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd
from sklearn.metrics import top_k_accuracy_score

from models.calibration import apply_temperature, expected_calibration_error, fit_temperature
from models.next_pitch_model import TARGET_COL
from models.seq_infer import SeqPredictor
from models.seq_next_pitch import SEQ_LEN
from services.prediction_service import LAG_FIELDS, SEQ_ENSEMBLE_WEIGHT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025
N_BINS = 15


def to_sequences(df: pd.DataFrame) -> np.ndarray:
    steps = [
        df[[f"{field}_lag{lag}" for field in LAG_FIELDS]].to_numpy(dtype="float32")
        for lag in range(SEQ_LEN, 0, -1)
    ]
    return np.stack(steps, axis=1)


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def reliability_curve(proba: np.ndarray, y: np.ndarray, n_bins: int = N_BINS):
    """구간별 (평균 확신도, 실제 정확도, 표본 수)."""
    conf = proba.max(axis=1)
    correct = (proba.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf > lo) & (conf <= hi)
        if lo == 0.0:
            mask |= conf == 0.0
        if mask.any():
            rows.append((conf[mask].mean(), correct[mask].mean(), int(mask.sum())))
    return np.array(rows)


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    models_dir = os.path.join(ROOT, "models")
    val = pd.read_parquet(os.path.join(processed, f"enriched_val_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    booster = lgb.Booster(model_file=os.path.join(models_dir, "next_pitch_lgbm.txt"))
    with open(os.path.join(models_dir, "next_pitch_lgbm_features.json"), encoding="utf-8") as f:
        feature_cols = json.load(f)["feature_cols"]
    predictor = SeqPredictor(os.path.join(models_dir, "seq_model_weights.npz"))

    labels = sorted(val[TARGET_COL].unique())
    w = SEQ_ENSEMBLE_WEIGHT

    proba, y = {}, {}
    for name, df in (("val", val), ("test", test)):
        gru = predictor.predict_proba(predictor.standardize(to_sequences(df)))
        proba[name] = (1 - w) * booster.predict(df[feature_cols]) + w * gru
        y[name] = df[TARGET_COL].to_numpy()

    T_nll = fit_temperature(proba["val"], y["val"])

    # NLL이 아니라 ECE를 직접 최소화한 T도 같이 본다. 둘이 갈리면 "캘리브레이션이
    # 안 먹는 것"인지 "목적함수를 잘못 고른 것"인지 구분이 안 되기 때문이다.
    grid = np.linspace(0.5, 2.5, 81)
    ece_val = [expected_calibration_error(apply_temperature(proba["val"], t), y["val"], N_BINS)
               for t in grid]
    T_ece = float(grid[int(np.argmin(ece_val))])

    base_val = expected_calibration_error(proba["val"], y["val"], N_BINS)
    print(f"[적합] NLL 최소 T = {T_nll:.4f} / ECE 최소 T = {T_ece:.4f}")
    print(f"[val ] ECE T=1.0 {base_val:.4f} / "
          f"T={T_nll:.2f} {expected_calibration_error(apply_temperature(proba['val'], T_nll), y['val'], N_BINS):.4f} / "
          f"T={T_ece:.2f} {expected_calibration_error(apply_temperature(proba['val'], T_ece), y['val'], N_BINS):.4f}")

    ece_before = expected_calibration_error(proba["test"], y["test"], N_BINS)
    for name, t in (("NLL", T_nll), ("ECE", T_ece)):
        e = expected_calibration_error(apply_temperature(proba["test"], t), y["test"], N_BINS)
        print(f"[test] {name} 기준 T={t:.4f} -> ECE {ece_before:.4f} -> {e:.4f}")

    # 채택 후보는 val ECE를 가장 낮춘 T다. test로 고르면 그 수치는 더 이상 일반화 성능이 아니다.
    T = T_ece if min(ece_val) < base_val else 1.0
    scaled = apply_temperature(proba["test"], T)
    ece_after = expected_calibration_error(scaled, y["test"], N_BINS)
    print(f"[선택] T = {T:.4f} / test ECE {ece_before:.4f} -> {ece_after:.4f}")

    b1, b3 = _topk(y["test"], proba["test"], labels)
    a1, a3 = _topk(y["test"], scaled, labels)
    print(f"[test] top1 {b1:.4f} -> {a1:.4f} / top3 {b3:.4f} -> {a3:.4f}")
    assert (b1, b3) == (a1, a3), "온도 스케일링이 순위를 바꿨다. 구현이 잘못됐다"

    applied = ece_after < ece_before
    if not applied:
        print("[판정] ECE가 줄지 않았다. 적용하지 않고 T=1.0으로 기록한다.")
        T = 1.0

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=140)
    ax.plot([0, 1], [0, 1], "--", color="#888", lw=1, label="완벽한 캘리브레이션")
    for curve, label, color in (
        (reliability_curve(proba["test"], y["test"]), f"보정 전 (ECE {ece_before:.3f})", "#d1495b"),
        (reliability_curve(scaled, y["test"]), f"보정 후 T={T:.2f} (ECE {ece_after:.3f})", "#2a9d8f"),
    ):
        ax.plot(curve[:, 0], curve[:, 1], "o-", color=color, lw=1.6, ms=4, label=label)
    ax.set_xlabel("예측 확신도")
    ax.set_ylabel("실제 정확도")
    ax.set_title(f"신뢰도 다이어그램 (test {len(test):,}건)")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    png = os.path.join(out_dir, f"reliability_{YEAR}.png")
    fig.savefig(png)
    print(f"[저장] {png}")

    artifact = os.path.join(models_dir, "calibration.json")
    with open(artifact, "w", encoding="utf-8") as f:
        json.dump({
            "method": "temperature_scaling",
            "temperature": T,
            "ece_before": ece_before,
            "ece_after": ece_after,
            "applied": applied,
            "n_bins": N_BINS,
            "fitted_on": "val 앙상블 확률",
            "ensemble_weight": w,
        }, f, ensure_ascii=False, indent=2)
    print(f"[저장] {artifact}")


if __name__ == "__main__":
    main()
