"""
DiamondScout AI - 멀티시즌(2021~2025) 가중 프로필 생성
data/preprocess_statcast.py의 기존 전처리 함수(로드/인코딩/구종라벨/존셀/결과플래그)를 그대로
재사용해 연도별 원본(raw, 읽기 전용)을 처리한 뒤, 시즌 가중치를 적용해 하나로 합친 프로필을
data/processed/*_multi_year.csv로 저장한다.

next_pitch_dataset(모델 학습용, lag-5 feature)은 이 스크립트의 목적(표본 보강용 집계 프로필)에
불필요하고 연산 비용이 가장 커서 의도적으로 생성하지 않는다 - 기존 2025 next_pitch_dataset과
next_pitch_model은 그대로 유지된다.

구종 라벨(pitch_label)은 연도마다 따로 계산하면 "그 해 희귀 구종 기준"이 달라져 연도 간 비교가
어긋나므로, 이미 서비스가 쓰고 있는 2025 기준 pitch_label_mapping.json(canonical)을 모든 연도에
동일하게 적용한다.

실행:
    ./venv/bin/python data/build_multi_year_profiles.py
"""

import json
import os

import pandas as pd

from data.preprocess_statcast import (
    add_outcome_flags,
    add_pitch_label,
    add_score_diff,
    add_zone_cell,
    add_pitch_result_group,
    encode_categoricals,
    encode_runners,
    load_raw,
)

SEASON_WEIGHTS = {2025: 1.0, 2024: 0.85, 2023: 0.65, 2022: 0.45, 2021: 0.30}


def _load_canonical_label_mapping(root: str) -> dict:
    path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    return mapping["label_to_id"]


def _prepare_year(root: str, year: int, label_to_id: dict) -> pd.DataFrame:
    print(f"[{year}] raw 로드 중...")
    df = load_raw(root, year)
    df = encode_categoricals(df)
    df = encode_runners(df)
    df = add_score_diff(df)
    df = add_pitch_result_group(df)
    df = add_pitch_label(df, label_to_id)
    # 일부 연도(주로 2021~2022)에는 트래킹이 안 된 극소수 투구(고의4구 등)에 plate_x/plate_z/
    # sz_bot/sz_top이 결측으로 남아 있어, add_zone_cell의 float->int 변환이 그대로 깨진다.
    # 2025 파이프라인은 이런 행이 없어 지금까지 드러나지 않았던 문제라, 원본 add_zone_cell은
    # 그대로 두고 이 스크립트에서만 존 계산에 필요한 4개 컬럼이 결측인 행을 제외한다.
    before = len(df)
    df = df.dropna(subset=["plate_x", "plate_z", "sz_bot", "sz_top"]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"[{year}] plate_x/plate_z/sz_bot/sz_top 결측 {dropped:,}행 제외")
    df = add_zone_cell(df)
    df = add_outcome_flags(df)
    df["season"] = year
    df["season_weight"] = SEASON_WEIGHTS[year]
    print(f"[{year}] 전처리 완료: {len(df):,}행")
    return df


def _weighted_pitcher_pitch_profile(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["w_count"] = df["season_weight"]
    g = df.groupby(["pitcher", "pitch_label"])["w_count"].sum().rename("pitch_count").reset_index()
    totals = df.groupby("pitcher")["w_count"].sum().rename("pitcher_total_pitches")
    g = g.merge(totals, on="pitcher")
    g["pitch_ratio"] = g["pitch_count"] / g["pitcher_total_pitches"]
    # player_name은 가장 최근 시즌(최대 season) 표기를 대표값으로 사용한다.
    latest_name = df.sort_values("season").groupby("pitcher")["player_name"].last().rename("player_name")
    g = g.merge(latest_name, on="pitcher")
    return g.sort_values(["pitcher", "pitch_count"], ascending=[True, False]).reset_index(drop=True)


def _weighted_count_pitch_profile(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["w_count"] = df["season_weight"]
    g = df.groupby(["pitcher", "balls", "strikes", "pitch_label"])["w_count"].sum().rename("pitch_count").reset_index()
    totals = df.groupby(["pitcher", "balls", "strikes"])["w_count"].sum().rename("count_total_pitches")
    g = g.merge(totals, on=["pitcher", "balls", "strikes"])
    g["pitch_ratio"] = g["pitch_count"] / g["count_total_pitches"]
    return g.sort_values(
        ["pitcher", "balls", "strikes", "pitch_count"], ascending=[True, True, True, False]
    ).reset_index(drop=True)


def _weighted_mean_agg(df: pd.DataFrame, group_cols: list[str], rate_cols: list[str]) -> pd.DataFrame:
    """rate_cols(0/1 플래그 또는 delta_run_exp)의 시즌 가중 평균을, 각 행의 season_weight를
    가중치로 삼아 계산한다. pitch_count는 가중치 합(=사실상 유효 표본 크기)으로 저장한다."""
    df = df.copy()
    df["w"] = df["season_weight"]
    result_frames = [df.groupby(group_cols)["w"].sum().rename("pitch_count")]
    wsum = df.groupby(group_cols)["w"].sum()
    for col in rate_cols:
        weighted = (df[col] * df["w"]).groupby([df[c] for c in group_cols]).sum()
        result_frames.append((weighted / wsum).rename(col))
    out = pd.concat(result_frames, axis=1).reset_index()
    return out


def _weighted_zone_risk_profile(df: pd.DataFrame) -> pd.DataFrame:
    rate_cols = [
        "is_whiff", "is_ball", "is_in_play", "is_extra_base_hit", "is_home_run",
        "hard_hit", "risky_contact", "delta_run_exp",
    ]
    out = _weighted_mean_agg(df, ["pitcher", "pitch_label", "zone_cell"], rate_cols)
    out = out.rename(columns={
        "is_whiff": "whiff_rate", "is_ball": "ball_rate", "is_in_play": "in_play_rate",
        "is_extra_base_hit": "extra_base_hit_rate", "is_home_run": "home_run_rate",
        "hard_hit": "hard_hit_rate", "risky_contact": "risky_contact_rate",
        "delta_run_exp": "avg_delta_run_exp",
    })
    return out.sort_values(["pitcher", "pitch_label", "zone_cell"]).reset_index(drop=True)


def _weighted_batter_matchup_profile(df: pd.DataFrame) -> pd.DataFrame:
    rate_cols = ["is_whiff", "is_foul", "is_in_play", "hard_hit", "is_extra_base_hit", "delta_run_exp"]
    out = _weighted_mean_agg(df, ["batter", "stand", "p_throws", "pitch_label"], rate_cols)
    out = out.rename(columns={
        "is_whiff": "whiff_rate", "is_foul": "foul_rate", "is_in_play": "in_play_rate",
        "hard_hit": "hard_hit_rate", "is_extra_base_hit": "extra_base_hit_rate",
        "delta_run_exp": "avg_delta_run_exp",
    })
    return out.sort_values(["batter", "stand", "p_throws", "pitch_label"]).reset_index(drop=True)


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(root)
    label_to_id = _load_canonical_label_mapping(root)

    frames = [_prepare_year(root, year, label_to_id) for year in sorted(SEASON_WEIGHTS)]
    combined = pd.concat(frames, ignore_index=True)
    print(f"\n[전체 결합] {len(combined):,}행 (2021~2025)")

    outputs = {
        "pitcher_pitch_profile_multi_year.csv": _weighted_pitcher_pitch_profile(combined),
        "count_pitch_profile_multi_year.csv": _weighted_count_pitch_profile(combined),
        "zone_risk_profile_multi_year.csv": _weighted_zone_risk_profile(combined),
        "batter_matchup_profile_multi_year.csv": _weighted_batter_matchup_profile(combined),
    }
    processed_dir = os.path.join(root, "data", "processed")
    for filename, out_df in outputs.items():
        path = os.path.join(processed_dir, filename)
        out_df.to_csv(path, index=False)
        print(f"[저장] {path} ({len(out_df):,}행 x {len(out_df.columns)}열)")

    print("\n[멀티시즌 프로필 생성 완료]")


if __name__ == "__main__":
    main()
