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
    batter_pitch_feature_cols,
    build_batter_matchup_features,
    build_batter_pitch_matchup,
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
    batter_events: pd.DataFrame | None = None,
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

    if batter_events is not None:
        bp = build_batter_pitch_matchup(train_df, batter_events, label_ids)
        out = out.merge(bp, on="batter", how="left")
        # 처음 보는 타자는 train 타자 평균. 여기도 폴백 통계를 train에서만 뽑는다.
        for col in batter_pitch_feature_cols(label_ids):
            out[col] = out[col].fillna(bp[col].mean())
    return out


def save_serving_priors(
    train_df: pd.DataFrame,
    label_ids: list[int],
    batter_profile: pd.DataFrame | None,
    out_dir: str,
    batter_events: pd.DataFrame | None = None,
) -> None:
    """서빙이 쓸 prior 테이블을 그대로 내보낸다.

    학습에 쓴 것과 **같은 함수·같은 k**로 만든 표를 저장한다. 서빙에서
    count_pitch_profile 같은 다른 집계를 대신 쓰면 스무딩 여부와 집계 구간이 달라져
    모델이 학습 때와 다른 분포를 받는다. prior가 gain 중요도의 81%를 지고 있어서
    이 불일치는 에러 없이 정확도만 깎는다.

    parquet이 아니라 CSV인 이유: requirements-deploy.txt에 pyarrow가 없다.
    """
    os.makedirs(out_dir, exist_ok=True)
    build_pitcher_prior(train_df, label_ids).to_csv(
        os.path.join(out_dir, "pitcher_prior.csv"), index=False
    )
    build_count_prior(train_df, label_ids).to_csv(
        os.path.join(out_dir, "count_prior.csv"), index=False
    )
    # 타자 피처는 한 파일에 모은다. 서빙은 batter 하나로 조회하므로 표를 나누면
    # 룩업만 늘고 두 표가 어긋날 여지가 생긴다.
    batter_table = None
    if batter_profile is not None:
        batter_table = build_batter_matchup_features(train_df, batter_profile)
    if batter_events is not None:
        bp = build_batter_pitch_matchup(train_df, batter_events, label_ids)
        batter_table = bp if batter_table is None else batter_table.merge(bp, on="batter", how="outer")
    if batter_table is not None:
        batter_table.to_csv(os.path.join(out_dir, "batter_features.csv"), index=False)
    with open(os.path.join(out_dir, "league_prior.json"), "w", encoding="utf-8") as f:
        json.dump(league_prior(train_df, label_ids), f, ensure_ascii=False, indent=2)

    # 서빙은 경기 상태를 모른다 - 앱이 받는 건 볼카운트와 합성한 최근 5구뿐이라
    # 아래 3개는 관측할 수 없다. train 대표값으로 고정한다. 세 피처의 gain 중요도 합이
    # 0.89%라 고정해도 test top1이 0.4371 -> 0.4325로 0.46%p만 떨어진다(실측).
    defaults = {
        "pitcher_pitch_count_game": float(train_df["pitcher_pitch_count_game"].median()),
        "times_through_order": float(train_df["times_through_order"].median()),
        "prev_pitch_outcome_enc": int(train_df["prev_pitch_outcome_enc"].mode().iloc[0]),
    }
    with open(os.path.join(out_dir, "temporal_defaults.json"), "w", encoding="utf-8") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2)


def build_enriched_splits(root: str, year: int, with_batter_pitch: bool = False):
    df = load_dataset(root, year)

    mapping_path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        label_ids = sorted(int(k) for k in json.load(f)["id_to_label"])

    processed = os.path.join(root, "data", "processed")
    profile_path = os.path.join(processed, f"batter_matchup_profile_{year}.csv")
    batter_profile = pd.read_csv(profile_path) if os.path.exists(profile_path) else None

    # 타자 x 구종 피처는 기본으로 끈다. 측정 결과 이득이 없었다 - test top1이
    # 33열에서 -0.21%p(McNemar p=0.023), whiff 11열로 줄여도 -0.11%p였다.
    # 재현하려면 --with-batter-pitch로 켠다. output/metrics/batter_pitch_gain_2025.json 참고.
    batter_events = None
    if with_batter_pitch:
        events_path = os.path.join(processed, f"batter_matchup_events_{year}.csv")
        batter_events = pd.read_csv(events_path) if os.path.exists(events_path) else None

    df = add_temporal_features(df)
    train_df, val_df, test_df = time_based_split(df)

    # 서빙 prior를 여기서 같이 내보낸다. 따로 만들 수 있게 두면 언젠가 학습 데이터와
    # 어긋나는데, prior가 모델 gain의 81%라 그 순간 정확도가 조용히 무너진다.
    save_serving_priors(
        train_df, label_ids, batter_profile,
        os.path.join(root, "models", "serving_priors"), batter_events,
    )

    return tuple(
        attach_priors(split, train_df, label_ids, batter_profile, batter_events)
        for split in (train_df, val_df, test_df)
    )


if __name__ == "__main__":
    import argparse

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument(
        "--with-batter-pitch", action="store_true",
        help="타자 x 구종 피처 33개를 넣는다. 측정에서 이득이 없어 기본은 끔",
    )
    args = parser.parse_args()

    train, val, test = build_enriched_splits(root, args.year, args.with_batter_pitch)
    out_dir = os.path.join(root, "data", "processed")
    for name, split in (("train", train), ("val", val), ("test", test)):
        path = os.path.join(out_dir, f"enriched_{name}_{args.year}.parquet")
        split.to_parquet(path, index=False)
        print(f"[저장] {path} ({len(split):,}행 x {len(split.columns)}열)")
