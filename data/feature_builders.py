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


OUTCOME_ENC = {
    "none": 0,
    "ball": 1,
    "called_strike": 2,
    "whiff": 3,
    "foul": 4,
    "in_play": 5,
    "hit_by_pitch": 6,
    "other": 7,
}


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """같은 경기 안에서의 누적 · 순서 피처를 추가한다.

    모든 값은 '해당 투구를 던지기 직전'까지의 정보만 쓴다.
    반환 프레임은 (game_pk, pitcher, at_bat_number, pitch_number) 순으로 정렬된
    새 객체다 — 입력 순서를 보존하지 않으므로 호출부에서 위치 기준으로 붙이면 안 된다.
    """
    work = (
        df.sort_values(["game_pk", "pitcher", "at_bat_number", "pitch_number"])
        .reset_index(drop=True)
        .copy()
    )

    by_pitcher = work.groupby(["game_pk", "pitcher"], sort=False)
    by_atbat = work.groupby(["game_pk", "pitcher", "at_bat_number"], sort=False)

    work["pitch_of_atbat"] = by_atbat.cumcount() + 1
    work["is_first_pitch_of_ab"] = (work["pitch_of_atbat"] == 1).astype(int)
    work["pitcher_pitch_count_game"] = by_pitcher.cumcount() + 1

    # 타순 순회: 같은 (경기, 투수)에서 그 타자를 몇 번째 상대하는가.
    first = work[work["is_first_pitch_of_ab"] == 1].copy()
    first["tto"] = first.groupby(["game_pk", "pitcher", "batter"]).cumcount() + 1
    work = work.merge(
        first[["game_pk", "pitcher", "at_bat_number", "tto"]],
        on=["game_pk", "pitcher", "at_bat_number"],
        how="left",
    )
    work["times_through_order"] = work["tto"].fillna(1).astype(int)
    work = work.drop(columns=["tto"])

    # 같은 구종 연속 횟수: lag1이 직전 행과 같고 같은 (경기, 투수)면 누적.
    # 투수가 바뀌면 끊는다 — 이어 붙이면 불펜이 선발의 연속 기록을 물려받는다.
    lag1 = work["pitch_label_id_lag1"].to_numpy(dtype=float)
    same_group = (
        work[["game_pk", "pitcher"]].shift() == work[["game_pk", "pitcher"]]
    ).all(axis=1).to_numpy()
    same_value = np.zeros(len(work), dtype=bool)
    same_value[1:] = (lag1[1:] == lag1[:-1]) & ~np.isnan(lag1[1:])
    continues = same_group & same_value

    streak = np.ones(len(work), dtype=int)
    for i in np.flatnonzero(continues):
        streak[i] = streak[i - 1] + 1
    work["same_pitch_streak"] = streak

    work["prev_pitch_outcome_enc"] = (
        work["prev_pitch_outcome"].map(OUTCOME_ENC).fillna(OUTCOME_ENC["other"]).astype(int)
    )
    return work


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
