"""다음 구종 예측용 prior 피처 빌더.

모든 prior는 train split에서만 집계한다. 전체 데이터로 집계하면 test 정보가
train으로 새어 들어가 정확도가 비현실적으로 높게 나온다.
"""

import numpy as np
import pandas as pd

TARGET_COL = "target_pitch_label_id"

# 카운트별 비율을 투수 전체 아스널 쪽으로 당기는 강도.
# 표본 k개만큼의 가상 관측을 투수 평균에서 빌려오는 셈이라, 표본이 k보다
# 적은 카운트는 자기 비율보다 투수 평균을 더 믿는다.
PRIOR_SHRINKAGE_K = 20


def league_prior(train_df: pd.DataFrame, label_ids: list[int]) -> dict[int, float]:
    """train 전체의 구종 분포. 처음 보는 투수/타자를 채우는 데 쓴다."""
    counts = train_df[TARGET_COL].value_counts()
    total = float(counts.sum())
    return {i: float(counts.get(i, 0)) / total for i in label_ids}


def _ratio_matrix(
    counts: pd.DataFrame, group_cols: list[str], label_ids: list[int], prefix: str
) -> pd.DataFrame:
    """(group_cols, label) 카운트 테이블을 label별 비율 컬럼으로 편다.

    train에 안 나온 라벨도 0.0 컬럼으로 남긴다 — split마다 피처 개수가 달라지면
    모델 입력이 어긋난다.
    """
    wide = counts.pivot_table(
        index=group_cols, columns=TARGET_COL, values="n", fill_value=0, aggfunc="sum"
    )
    for i in label_ids:
        if i not in wide.columns:
            wide[i] = 0
    wide = wide[label_ids]

    totals = wide.sum(axis=1).replace(0, np.nan)
    ratios = wide.div(totals, axis=0).fillna(0.0)
    ratios.columns = [f"{prefix}_{i}" for i in label_ids]
    return ratios.reset_index()


def build_pitcher_prior(train_df: pd.DataFrame, label_ids: list[int]) -> pd.DataFrame:
    """투수별 구종 구사 비율 (아스널)."""
    counts = train_df.groupby(["pitcher", TARGET_COL]).size().rename("n").reset_index()
    return _ratio_matrix(counts, ["pitcher"], label_ids, "pitcher_prior")


def build_count_prior(
    train_df: pd.DataFrame, label_ids: list[int], k: int = PRIOR_SHRINKAGE_K
) -> pd.DataFrame:
    """투수 x 볼카운트별 구종 비율.

    3-0 같은 희소 카운트는 표본이 적어 비율이 튄다. 투수 전체 아스널 쪽으로
    스무딩한다: (n*r_count + k*r_pitcher) / (n + k)
    """
    counts = (
        train_df.groupby(["pitcher", "balls", "strikes", TARGET_COL])
        .size()
        .rename("n")
        .reset_index()
    )
    count_ratios = _ratio_matrix(counts, ["pitcher", "balls", "strikes"], label_ids, "count_prior")

    n_per_count = (
        train_df.groupby(["pitcher", "balls", "strikes"]).size().rename("n_count").reset_index()
    )
    pitcher_ratios = build_pitcher_prior(train_df, label_ids)

    merged = count_ratios.merge(n_per_count, on=["pitcher", "balls", "strikes"]).merge(
        pitcher_ratios, on="pitcher"
    )

    n = merged["n_count"].to_numpy()[:, None]
    raw = merged[[f"count_prior_{i}" for i in label_ids]].to_numpy()
    base = merged[[f"pitcher_prior_{i}" for i in label_ids]].to_numpy()
    smoothed = (n * raw + k * base) / (n + k)

    out = merged[["pitcher", "balls", "strikes"]].copy()
    for idx, i in enumerate(label_ids):
        out[f"count_prior_{i}"] = smoothed[:, idx]
    return out


def build_batter_matchup_features(
    train_df: pd.DataFrame, raw_profile: pd.DataFrame
) -> pd.DataFrame:
    """타자 x 구종 반응 지표를 타자 단위로 요약한다.

    train split에 등장한 타자만 사용한다 — 그래야 누수가 없다.
    raw_profile은 data/processed/batter_matchup_profile_{year}.csv 형식이다.
    """
    train_batters = set(train_df["batter"].unique())
    prof = raw_profile[raw_profile["batter"].isin(train_batters)]
    return (
        prof.groupby("batter")
        .agg(
            batter_whiff_avg=("whiff_rate", "mean"),
            batter_hardhit_avg=("hard_hit_rate", "mean"),
            batter_xbh_avg=("extra_base_hit_rate", "mean"),
            batter_whiff_max=("whiff_rate", "max"),
        )
        .reset_index()
    )
