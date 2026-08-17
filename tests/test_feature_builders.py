import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.feature_builders import (
    PRIOR_SHRINKAGE_K,
    build_batter_matchup_features,
    build_count_prior,
    build_pitcher_prior,
    league_prior,
)

LABEL_IDS = [0, 1, 2]


def _train_df():
    # 투수 100: FF(0) 3개, SL(1) 1개 -> 0.75 / 0.25 / 0.0
    # 투수 200: SL(1) 2개, CU(2) 2개 -> 0.0 / 0.5 / 0.5
    return pd.DataFrame({
        "pitcher": [100, 100, 100, 100, 200, 200, 200, 200],
        "batter":  [10, 10, 11, 11, 12, 12, 13, 13],
        "balls":   [0, 0, 1, 1, 0, 0, 1, 1],
        "strikes": [0, 0, 0, 0, 0, 0, 0, 0],
        "target_pitch_label_id": [0, 0, 0, 1, 1, 1, 2, 2],
    })


def test_pitcher_prior_ratios_sum_to_one():
    result = build_pitcher_prior(_train_df(), LABEL_IDS)
    cols = [f"pitcher_prior_{i}" for i in LABEL_IDS]

    assert np.allclose(result[cols].sum(axis=1), 1.0)


def test_pitcher_prior_reflects_actual_mix():
    result = build_pitcher_prior(_train_df(), LABEL_IDS).set_index("pitcher")

    assert result.loc[100, "pitcher_prior_0"] == pytest.approx(0.75)
    assert result.loc[100, "pitcher_prior_1"] == pytest.approx(0.25)
    assert result.loc[100, "pitcher_prior_2"] == pytest.approx(0.0)


def test_pitcher_prior_keeps_columns_for_unseen_labels():
    """train split에 한 번도 안 나온 구종도 컬럼은 있어야 한다.
    없으면 split마다 피처 개수가 달라져 모델 입력이 어긋난다."""
    result = build_pitcher_prior(_train_df(), [0, 1, 2, 9])

    assert "pitcher_prior_9" in result.columns
    assert (result["pitcher_prior_9"] == 0.0).all()


def test_league_prior_is_overall_distribution():
    result = league_prior(_train_df(), LABEL_IDS)

    assert result[0] == pytest.approx(3 / 8)
    assert sum(result.values()) == pytest.approx(1.0)


def test_count_prior_shrinks_toward_pitcher_prior_when_sparse():
    """표본 1개짜리 카운트는 투수 전체 아스널 쪽으로 당겨져야 한다."""
    result = build_count_prior(_train_df(), LABEL_IDS, k=PRIOR_SHRINKAGE_K)
    row = result[(result["pitcher"] == 100) & (result["balls"] == 1) & (result["strikes"] == 0)]

    # 이 카운트의 raw 비율은 FF 0.5인데, 투수 전체 0.75 쪽으로 당겨져야 한다
    assert row["count_prior_0"].iloc[0] > 0.5


def test_count_prior_ratios_sum_to_one():
    result = build_count_prior(_train_df(), LABEL_IDS, k=PRIOR_SHRINKAGE_K)
    cols = [f"count_prior_{i}" for i in LABEL_IDS]

    assert np.allclose(result[cols].sum(axis=1), 1.0)


def test_count_prior_covers_every_observed_count():
    """조인 키가 빠지면 그 카운트의 투구는 prior 없이 학습된다."""
    train = _train_df()
    result = build_count_prior(train, LABEL_IDS, k=PRIOR_SHRINKAGE_K)

    observed = set(map(tuple, train[["pitcher", "balls", "strikes"]].drop_duplicates().to_numpy()))
    produced = set(map(tuple, result[["pitcher", "balls", "strikes"]].to_numpy()))

    assert observed == produced


def _raw_batter_profile():
    return pd.DataFrame({
        "batter": [10, 10, 11, 99],
        "pitch_label": ["FF", "SL", "FF", "FF"],
        "whiff_rate": [0.1, 0.3, 0.2, 0.9],
        "hard_hit_rate": [0.4, 0.2, 0.3, 0.1],
        "extra_base_hit_rate": [0.05, 0.01, 0.02, 0.5],
    })


def test_batter_features_use_only_train_batters():
    """train에 없는 타자 99는 집계에서 빠져야 한다."""
    result = build_batter_matchup_features(_train_df(), _raw_batter_profile())

    assert 99 not in set(result["batter"])


def test_batter_whiff_max_takes_worst_pitch():
    result = build_batter_matchup_features(_train_df(), _raw_batter_profile()).set_index("batter")

    assert result.loc[10, "batter_whiff_max"] == pytest.approx(0.3)
    assert result.loc[10, "batter_whiff_avg"] == pytest.approx(0.2)


def test_builders_do_not_mutate_inputs():
    train, profile = _train_df(), _raw_batter_profile()
    train_before, profile_before = train.copy(), profile.copy()

    build_pitcher_prior(train, LABEL_IDS)
    build_count_prior(train, LABEL_IDS)
    build_batter_matchup_features(train, profile)

    pd.testing.assert_frame_equal(train, train_before)
    pd.testing.assert_frame_equal(profile, profile_before)
