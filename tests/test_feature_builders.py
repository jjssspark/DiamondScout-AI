import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.feature_builders import (
    PRIOR_SHRINKAGE_K,
    add_temporal_features,
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


# --- 시간 · 피로 피처 ---------------------------------------------------------


def _game_df():
    """한 경기, 투수 100. 타석 1(3구) -> 타석 2(2구)."""
    return pd.DataFrame({
        "game_pk": [1, 1, 1, 1, 1],
        "pitcher": [100, 100, 100, 100, 100],
        "batter":  [10, 10, 10, 20, 20],
        "at_bat_number": [1, 1, 1, 2, 2],
        "pitch_number": [1, 2, 3, 1, 2],
        "pitch_label_id_lag1": [np.nan, 0.0, 0.0, 1.0, 0.0],
        "prev_pitch_outcome": ["none", "ball", "ball", "foul", "called_strike"],
    })


def test_pitch_of_atbat_counts_within_at_bat():
    result = add_temporal_features(_game_df())

    assert list(result["pitch_of_atbat"]) == [1, 2, 3, 1, 2]


def test_pitcher_pitch_count_accumulates_across_game():
    result = add_temporal_features(_game_df())

    assert list(result["pitcher_pitch_count_game"]) == [1, 2, 3, 4, 5]


def test_is_first_pitch_of_ab_flags_only_first():
    result = add_temporal_features(_game_df())

    assert list(result["is_first_pitch_of_ab"]) == [1, 0, 0, 1, 0]


def test_times_through_order_increments_on_batter_repeat():
    df = pd.concat([_game_df(), pd.DataFrame({
        "game_pk": [1], "pitcher": [100], "batter": [10],
        "at_bat_number": [3], "pitch_number": [1],
        "pitch_label_id_lag1": [1.0], "prev_pitch_outcome": ["none"],
    })], ignore_index=True)

    result = add_temporal_features(df)

    assert result["times_through_order"].iloc[-1] == 2


def test_same_pitch_streak_counts_consecutive_identical_lags():
    result = add_temporal_features(_game_df())

    # lag1이 [nan, 0, 0, 1, 0] -> 인덱스 2에서 0이 2연속
    assert result["same_pitch_streak"].iloc[2] == 2
    assert result["same_pitch_streak"].iloc[3] == 1


def test_prev_pitch_outcome_is_encoded_as_int():
    result = add_temporal_features(_game_df())

    assert result["prev_pitch_outcome_enc"].dtype.kind in "iu"
    assert result["prev_pitch_outcome_enc"].iloc[0] == 0  # "none"


def test_counters_reset_between_games_and_pitchers():
    """경기·투수 경계를 넘어 누적되면 불펜 투수가 선발의 투구수를 물려받는다."""
    a = _game_df()
    b = _game_df().assign(game_pk=2)
    c = _game_df().assign(pitcher=200)

    result = add_temporal_features(pd.concat([a, b, c], ignore_index=True))
    counts = result.groupby(["game_pk", "pitcher"])["pitcher_pitch_count_game"].max()

    assert set(counts) == {5}


def test_streak_does_not_carry_across_pitchers():
    """투수가 바뀌는 지점에서 연속 카운트는 1로 끊겨야 한다."""
    first = _game_df()
    second = _game_df().assign(pitcher=200, pitch_label_id_lag1=[0.0] * 5)

    result = add_temporal_features(pd.concat([first, second], ignore_index=True))
    boundary = result[result["pitcher"] == 200].iloc[0]

    assert boundary["same_pitch_streak"] == 1


def test_unknown_outcome_falls_back_instead_of_nan():
    """새 이벤트 문자열이 들어와도 NaN이 되면 안 된다 - 모델 입력이 깨진다."""
    df = _game_df()
    df.loc[0, "prev_pitch_outcome"] = "catcher_interf"

    result = add_temporal_features(df)

    assert result["prev_pitch_outcome_enc"].iloc[0] == 7  # "other"


def test_temporal_output_is_sorted_and_keeps_every_row():
    """정렬을 바꿔 넣어도 결과는 경기/투수/타석/투구 순으로 나온다.
    호출부가 위치 기준으로 컬럼을 붙이면 어긋나므로 순서를 못 박아 둔다."""
    df = _game_df()
    shuffled = df.iloc[[3, 0, 4, 2, 1]].reset_index(drop=True)

    result = add_temporal_features(shuffled)
    keys = ["game_pk", "pitcher", "at_bat_number", "pitch_number"]

    assert len(result) == len(df)
    pd.testing.assert_frame_equal(
        result[keys], result[keys].sort_values(keys).reset_index(drop=True)
    )


def test_add_temporal_features_does_not_mutate_input():
    df = _game_df()
    before = df.copy()

    add_temporal_features(df)

    pd.testing.assert_frame_equal(df, before)


# --- 타자 x 구종 매치업 ---------------------------------------------------


def _bp_train_df():
    """게임 1,2가 train. 게임 9는 val/test라 집계에 들어오면 안 된다."""
    return pd.DataFrame({
        "pitcher": [100] * 4,
        "batter": [10, 10, 11, 11],
        "game_pk": [1, 1, 2, 2],
        "balls": [0, 0, 0, 0],
        "strikes": [0, 0, 0, 0],
        "target_pitch_label_id": [0, 1, 0, 1],
    })


def _bp_events():
    """라벨0의 리그 평균은 (0+2)/(200+2) = 0.0099로 낮게 잡히도록 짰다.
    타자 10은 라벨0을 200구 보고 헛스윙 0 (자기 값 0.0, 표본 큼).
    타자 11은 라벨0을 2구 보고 둘 다 헛스윙 (자기 값 1.0, 표본 작음).
    게임 9 행은 train 밖이라 집계에 들어오면 안 된다."""
    return pd.DataFrame({
        "batter":         [10,  10,  11, 11,  10],
        "game_pk":        [1,   1,   2,  2,   9],
        "pitch_label_id": [0,   1,   0,  1,   2],
        "n":              [200, 100, 2,  100, 500],
        "whiff_n":        [0,   0,   2,  0,   500],
        "hardhit_n":      [0,   0,   0,  0,   0],
        "xbh_n":          [0,   0,   0,  0,   0],
    })


def test_batter_pitch_matchup_has_one_column_per_label_and_metric():
    from data.feature_builders import batter_pitch_feature_cols, build_batter_pitch_matchup

    out = build_batter_pitch_matchup(_bp_train_df(), _bp_events(), LABEL_IDS)
    expected = batter_pitch_feature_cols(LABEL_IDS)

    assert len(expected) == 3 * len(LABEL_IDS)
    assert list(out.columns) == ["batter"] + expected


def test_batter_pitch_matchup_ignores_games_outside_train():
    """게임 9(train 밖)에서 타자 10이 라벨2를 500구 전부 헛스윙했다.
    반영되면 batter_whiff_2가 1.0 근처로 튄다."""
    from data.feature_builders import build_batter_pitch_matchup

    out = build_batter_pitch_matchup(_bp_train_df(), _bp_events(), LABEL_IDS)
    row = out[out["batter"] == 10].iloc[0]

    # train 안에서는 아무도 라벨2를 만난 적이 없다 -> 리그 평균 0.0
    assert row["batter_whiff_2"] == 0.0


def test_batter_pitch_matchup_shrinks_small_samples_more():
    """표본이 작을수록 자기 값에서 리그 평균 쪽으로 더 멀리 당겨져야 한다.

    수축이 없으면 2구 중 2구 헛스윙한 타자가 batter_whiff_0 = 1.0으로 잡히고,
    모델은 그 잡음을 "이 타자는 이 구종에 100% 헛스윙한다"로 학습한다.
    """
    from data.feature_builders import BATTER_PITCH_SHRINKAGE_K, build_batter_pitch_matchup

    out = build_batter_pitch_matchup(_bp_train_df(), _bp_events(), LABEL_IDS)
    big = out[out["batter"] == 10].iloc[0]["batter_whiff_0"]     # 자기 값 0.0, n=200
    small = out[out["batter"] == 11].iloc[0]["batter_whiff_0"]   # 자기 값 1.0, n=2

    assert abs(small - 1.0) > abs(big - 0.0), "표본이 작은 쪽이 더 많이 당겨져야 한다"
    assert small < 0.2, f"2구짜리 표본이 {small:.3f}로 남았다 - 수축이 약하다"
    assert BATTER_PITCH_SHRINKAGE_K > PRIOR_SHRINKAGE_K


def test_batter_pitch_matchup_falls_back_to_league_rate_for_unseen_pitch():
    """train에서 그 구종을 만난 적 없는 타자는 리그 평균으로 채운다. NaN이면 모델이 죽는다."""
    from data.feature_builders import build_batter_pitch_matchup

    events = _bp_events()
    # 타자 12를 추가하되 라벨0만 보게 한다
    train = pd.concat([_bp_train_df(), pd.DataFrame({
        "pitcher": [100], "batter": [12], "game_pk": [1],
        "balls": [0], "strikes": [0], "target_pitch_label_id": [0],
    })], ignore_index=True)
    events = pd.concat([events, pd.DataFrame({
        "batter": [12], "game_pk": [1], "pitch_label_id": [0],
        "n": [10], "whiff_n": [5], "hardhit_n": [0], "xbh_n": [0],
    })], ignore_index=True)

    out = build_batter_pitch_matchup(train, events, LABEL_IDS)
    row = out[out["batter"] == 12].iloc[0]

    league_whiff_1 = 0.0  # train에서 라벨1은 200구 중 헛스윙 0
    assert row["batter_whiff_1"] == pytest.approx(league_whiff_1)


def test_batter_pitch_matchup_has_no_nan_and_covers_every_train_batter():
    from data.feature_builders import build_batter_pitch_matchup

    train = _bp_train_df()
    out = build_batter_pitch_matchup(train, _bp_events(), LABEL_IDS)

    assert set(out["batter"]) == set(train["batter"].unique())
    assert not out.isna().any().any()
