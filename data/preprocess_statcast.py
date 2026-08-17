"""
DiamondScout AI - Statcast 원본 데이터 전처리
data/raw/statcast_{year}_full.csv를 읽어 data/processed/에 파생 데이터셋과 집계 테이블을 생성한다.
raw 데이터는 읽기만 하며 수정하지 않는다.
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

from data.player_names import attach_player_names

RARE_PITCH_MIN_COUNT = 1000
LOOKBACK = 5
HARD_HIT_THRESHOLD = 95.0
PLATE_HALF_WIDTH = 0.83  # 스트라이크존 좌우 절반 폭(ft) 근사값

STAND_MAP = {"L": 0, "R": 1}
TOPBOT_MAP = {"Top": 1, "Bot": 0}

WHIFF_DESC = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}
FOUL_DESC = {"foul", "foul_tip", "foul_bunt", "bunt_foul_tip"}
BALL_DESC = {"ball", "blocked_ball", "pitchout"}
HIT_EVENTS = {"single", "double", "triple", "home_run"}
XBH_EVENTS = {"double", "triple", "home_run"}
STRIKEOUT_EVENTS = {"strikeout", "strikeout_double_play"}


def load_raw(root: str, year: int) -> pd.DataFrame:
    path = os.path.join(root, "data", "raw", f"statcast_{year}_full.csv")
    df = pd.read_csv(path)
    df = df[df["pitch_type"].notna() & (df["pitch_type"] != "")]
    df = df.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)
    return df


def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    df["stand_enc"] = df["stand"].map(STAND_MAP)
    df["p_throws_enc"] = df["p_throws"].map(STAND_MAP)
    df["inning_topbot_enc"] = df["inning_topbot"].map(TOPBOT_MAP)
    return df


def encode_runners(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("on_1b", "on_2b", "on_3b"):
        df[col] = df[col].notna().astype(int)
    return df


def add_score_diff(df: pd.DataFrame) -> pd.DataFrame:
    df["score_diff"] = df["bat_score"] - df["fld_score"]
    return df


def classify_pitch_result(description: str) -> str:
    if description in WHIFF_DESC:
        return "whiff"
    if description == "called_strike":
        return "called_strike"
    if description in FOUL_DESC:
        return "foul"
    if description in BALL_DESC:
        return "ball"
    if description == "hit_by_pitch":
        return "hit_by_pitch"
    if description == "hit_into_play":
        return "in_play"
    return "other"


def add_pitch_result_group(df: pd.DataFrame) -> pd.DataFrame:
    df["pitch_result_group"] = df["description"].map(classify_pitch_result)
    return df


def build_pitch_label_mapping(df: pd.DataFrame) -> dict:
    counts = df["pitch_type"].value_counts()
    common = counts[counts >= RARE_PITCH_MIN_COUNT].index.tolist()
    common_sorted = sorted(common, key=lambda pt: -counts[pt])
    labels = common_sorted + ["OTHER"]
    return {label: i for i, label in enumerate(labels)}


def add_pitch_label(df: pd.DataFrame, label_to_id: dict) -> pd.DataFrame:
    known = [k for k in label_to_id if k != "OTHER"]
    df["pitch_label"] = df["pitch_type"].where(df["pitch_type"].isin(known), "OTHER")
    df["pitch_label_id"] = df["pitch_label"].map(label_to_id)
    return df


def add_zone_cell(df: pd.DataFrame) -> pd.DataFrame:
    sz_bot, sz_top = df["sz_bot"], df["sz_top"]
    in_zone = df["plate_x"].between(-PLATE_HALF_WIDTH, PLATE_HALF_WIDTH) & df["plate_z"].between(sz_bot, sz_top)

    x_clamped = df["plate_x"].clip(-PLATE_HALF_WIDTH, PLATE_HALF_WIDTH)
    col = ((x_clamped + PLATE_HALF_WIDTH) / (2 * PLATE_HALF_WIDTH) * 3).clip(0, 2.999).astype(int)

    z_clamped = df["plate_z"].clip(lower=sz_bot, upper=sz_top)
    row = ((z_clamped - sz_bot) / (sz_top - sz_bot) * 3).clip(0, 2.999).astype(int)

    # 존 안 3x3 격자를 1~9로, 존 밖은 0으로 표기. zone_cell_clamped는 존 밖 좌표를
    # 가장 가까운 셀(1~9)로 투영한 값으로, 히트맵 등 UI 표시에만 사용한다.
    grid_cell = row * 3 + col + 1
    df["zone_cell"] = np.where(in_zone, grid_cell, 0)
    df["zone_cell_clamped"] = grid_cell
    return df


def add_outcome_flags(df: pd.DataFrame) -> pd.DataFrame:
    df["is_whiff"] = (df["pitch_result_group"] == "whiff").astype(int)
    df["is_ball"] = (df["pitch_result_group"] == "ball").astype(int)
    df["is_foul"] = (df["pitch_result_group"] == "foul").astype(int)
    df["is_in_play"] = (df["type"] == "X").astype(int)

    df["is_hit"] = df["events"].isin(HIT_EVENTS).astype(int)
    df["is_extra_base_hit"] = df["events"].isin(XBH_EVENTS).astype(int)
    df["is_home_run"] = (df["events"] == "home_run").astype(int)
    df["is_walk"] = (df["events"] == "walk").astype(int)
    df["is_strikeout"] = df["events"].isin(STRIKEOUT_EVENTS).astype(int)

    df["hard_hit"] = (df["launch_speed"] >= HARD_HIT_THRESHOLD).astype(int)
    df["risky_contact"] = (
        (df["is_in_play"] == 1)
        & ((df["hard_hit"] == 1) | df["bb_type"].isin({"line_drive", "fly_ball"}))
    ).astype(int)
    return df


def build_next_pitch_dataset(df: pd.DataFrame) -> pd.DataFrame:
    lag_cols = [
        "pitch_label_id", "release_speed", "pfx_x", "pfx_z",
        "plate_x", "plate_z", "zone_cell", "balls", "strikes",
    ]
    # 현재 투구가 던져지기 전에 이미 알 수 있는 상황 정보만 사용한다.
    # release_speed/plate_x/plate_z처럼 투구 결과로만 알 수 있는 값은 포함하지 않는다.
    current_context_cols = [
        "balls", "strikes", "outs_when_up", "inning", "inning_topbot_enc",
        "on_1b", "on_2b", "on_3b", "score_diff", "stand_enc", "p_throws_enc",
    ]
    id_cols = ["game_date", "game_pk", "pitcher", "batter", "at_bat_number", "pitch_number"]

    work = df.sort_values(
        ["game_pk", "pitcher", "at_bat_number", "pitch_number"]
    ).reset_index(drop=True).copy()
    grouped = work.groupby(["game_pk", "pitcher"], sort=False)

    lag_feature_cols = []
    for col in lag_cols:
        for lag in range(1, LOOKBACK + 1):
            lag_col = f"{col}_lag{lag}"
            work[lag_col] = grouped[col].shift(lag)
            lag_feature_cols.append(lag_col)

    work = work.dropna(subset=lag_feature_cols).copy()
    work["target_pitch_label_id"] = work["pitch_label_id"]

    out_cols = id_cols + current_context_cols + lag_feature_cols + ["target_pitch_label_id"]
    return work[out_cols].reset_index(drop=True)


def build_pitcher_pitch_profile(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["pitcher", "player_name", "pitch_label"]).size().rename("pitch_count").reset_index()
    totals = df.groupby("pitcher").size().rename("pitcher_total_pitches")
    g = g.merge(totals, on="pitcher")
    g["pitch_ratio"] = g["pitch_count"] / g["pitcher_total_pitches"]
    return g.sort_values(["pitcher", "pitch_count"], ascending=[True, False]).reset_index(drop=True)


def build_count_pitch_profile(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["pitcher", "balls", "strikes", "pitch_label"]).size().rename("pitch_count").reset_index()
    totals = df.groupby(["pitcher", "balls", "strikes"]).size().rename("count_total_pitches")
    g = g.merge(totals, on=["pitcher", "balls", "strikes"])
    g["pitch_ratio"] = g["pitch_count"] / g["count_total_pitches"]
    return g.sort_values(
        ["pitcher", "balls", "strikes", "pitch_count"], ascending=[True, True, True, False]
    ).reset_index(drop=True)


def build_zone_risk_profile(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["pitcher", "pitch_label", "zone_cell"]).agg(
        pitch_count=("pitch_label", "size"),
        whiff_rate=("is_whiff", "mean"),
        ball_rate=("is_ball", "mean"),
        in_play_rate=("is_in_play", "mean"),
        extra_base_hit_rate=("is_extra_base_hit", "mean"),
        home_run_rate=("is_home_run", "mean"),
        hard_hit_rate=("hard_hit", "mean"),
        risky_contact_rate=("risky_contact", "mean"),
        avg_delta_run_exp=("delta_run_exp", "mean"),
    ).reset_index()
    return g.sort_values(["pitcher", "pitch_label", "zone_cell"]).reset_index(drop=True)


def _load_player_names(processed_dir: str) -> pd.DataFrame | None:
    """이름 표가 아직 없으면 None. 그러면 프로필에 player_name 컬럼이 안 붙고
    화면은 기존대로 'Batter ID {id}' 폴백을 쓴다. 전처리를 막지는 않는다."""
    path = os.path.join(processed_dir, "player_names.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def build_batter_matchup_profile(df: pd.DataFrame, names: pd.DataFrame | None = None) -> pd.DataFrame:
    """names를 주면 player_name 컬럼을 붙인다. raw의 player_name은 투수 이름이라
    타자 이름은 별도 룩업에서 온다(data/player_names.py)."""
    g = df.groupby(["batter", "stand", "p_throws", "pitch_label"]).agg(
        pitch_count=("pitch_label", "size"),
        whiff_rate=("is_whiff", "mean"),
        foul_rate=("is_foul", "mean"),
        in_play_rate=("is_in_play", "mean"),
        hard_hit_rate=("hard_hit", "mean"),
        extra_base_hit_rate=("is_extra_base_hit", "mean"),
        avg_delta_run_exp=("delta_run_exp", "mean"),
    ).reset_index()
    g = g.sort_values(["batter", "stand", "p_throws", "pitch_label"]).reset_index(drop=True)
    if names is not None:
        g = attach_player_names(g, names, id_col="batter")
    return g


def process_year(root: str, year: int) -> None:
    processed_dir = os.path.join(root, "data", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    df = load_raw(root, year)
    df = encode_categoricals(df)
    df = encode_runners(df)
    df = add_score_diff(df)
    df = add_pitch_result_group(df)

    label_to_id = build_pitch_label_mapping(df)
    df = add_pitch_label(df, label_to_id)
    df = add_zone_cell(df)
    df = add_outcome_flags(df)

    outputs = {
        f"next_pitch_dataset_{year}.csv": build_next_pitch_dataset(df),
        f"pitcher_pitch_profile_{year}.csv": build_pitcher_pitch_profile(df),
        f"count_pitch_profile_{year}.csv": build_count_pitch_profile(df),
        f"zone_risk_profile_{year}.csv": build_zone_risk_profile(df),
        f"batter_matchup_profile_{year}.csv": build_batter_matchup_profile(df, _load_player_names(processed_dir)),
    }
    for filename, out_df in outputs.items():
        path = os.path.join(processed_dir, filename)
        out_df.to_csv(path, index=False)
        print(f"[저장] {path} ({len(out_df):,}행 x {len(out_df.columns)}열)")

    mapping_path = os.path.join(processed_dir, "pitch_label_mapping.json")
    mapping = {
        "label_to_id": label_to_id,
        "id_to_label": {v: k for k, v in label_to_id.items()},
        "rare_pitch_min_count": RARE_PITCH_MIN_COUNT,
    }
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"[저장] {mapping_path}")


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    process_year(root, args.year)
    print("\n[전처리 완료]")
