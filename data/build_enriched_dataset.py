"""보강 피처가 붙은 train/val/test split을 만든다.

prior는 반드시 train split에서만 집계한다. 전체로 집계하면 누수다.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.feature_builders import (
    add_temporal_features,
    build_batter_matchup_features,
    build_count_prior,
    build_pitcher_prior,
    league_prior,
)
from models.next_pitch_model import load_dataset, time_based_split

BATTER_FEATURE_COLS = [
    "batter_whiff_avg",
    "batter_hardhit_avg",
    "batter_xbh_avg",
    "batter_whiff_max",
]


def attach_priors(
    target_df: pd.DataFrame,
    train_df: pd.DataFrame,
    label_ids: list[int],
    batter_profile: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """train에서 집계한 prior를 target_df에 조인한다.

    처음 보는 투수/카운트/타자는 리그 평균(또는 train 평균)으로 채운다.
    행은 절대 드롭하지 않는다.
    """
    pitcher_prior = build_pitcher_prior(train_df, label_ids)
    count_prior = build_count_prior(train_df, label_ids)
    lg = league_prior(train_df, label_ids)

    out = target_df.merge(pitcher_prior, on="pitcher", how="left")
    out = out.merge(count_prior, on=["pitcher", "balls", "strikes"], how="left")

    for i in label_ids:
        out[f"pitcher_prior_{i}"] = out[f"pitcher_prior_{i}"].fillna(lg[i])
        # 카운트 prior가 없으면 그 투수의 아스널로 (그것도 없었으면 이미 리그 평균)
        out[f"count_prior_{i}"] = out[f"count_prior_{i}"].fillna(out[f"pitcher_prior_{i}"])

    if batter_profile is not None:
        batter_feats = build_batter_matchup_features(train_df, batter_profile)
        out = out.merge(batter_feats, on="batter", how="left")
        for col in BATTER_FEATURE_COLS:
            # 폴백은 train 타자만의 평균이다. batter_profile 전체 평균을 쓰면
            # test 타자의 성적이 train 피처로 새어 들어간다.
            out[col] = out[col].fillna(batter_feats[col].mean())
    return out


def build_enriched_splits(root: str, year: int):
    df = load_dataset(root, year)

    mapping_path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        label_ids = sorted(int(k) for k in json.load(f)["id_to_label"])

    profile_path = os.path.join(root, "data", "processed", f"batter_matchup_profile_{year}.csv")
    batter_profile = pd.read_csv(profile_path) if os.path.exists(profile_path) else None

    df = add_temporal_features(df)
    train_df, val_df, test_df = time_based_split(df)

    return tuple(
        attach_priors(split, train_df, label_ids, batter_profile)
        for split in (train_df, val_df, test_df)
    )


if __name__ == "__main__":
    import argparse

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    train, val, test = build_enriched_splits(root, args.year)
    out_dir = os.path.join(root, "data", "processed")
    for name, split in (("train", train), ("val", val), ("test", test)):
        path = os.path.join(out_dir, f"enriched_{name}_{args.year}.parquet")
        split.to_parquet(path, index=False)
        print(f"[저장] {path} ({len(split):,}행 x {len(split.columns)}열)")
