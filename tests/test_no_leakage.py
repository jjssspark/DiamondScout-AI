"""prior 피처가 미래 데이터를 참조하지 않는지 검증한다.

이 테스트가 깨지면 이 계획의 정확도 개선 수치를 전부 믿을 수 없다.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.build_enriched_dataset import attach_priors
from data.feature_builders import league_prior

LABEL_IDS = [0, 1, 2]


def _train():
    return pd.DataFrame({
        "pitcher": [100, 100, 100, 100],
        "batter": [10, 10, 11, 11],
        "game_pk": [1, 1, 1, 1],
        "balls": [0, 0, 0, 0], "strikes": [0, 0, 0, 0],
        "target_pitch_label_id": [0, 0, 0, 1],
    })


def test_prior_computed_from_train_only_ignores_test_rows():
    """test에만 존재하는 구종은 prior에 반영되면 안 된다."""
    train = pd.DataFrame({
        "pitcher": [100, 100], "batter": [10, 10],
        "balls": [0, 0], "strikes": [0, 0],
        "target_pitch_label_id": [0, 0],
    })
    test = pd.DataFrame({
        "pitcher": [100, 100], "batter": [10, 10],
        "balls": [0, 0], "strikes": [0, 0],
        "target_pitch_label_id": [2, 2],
    })

    result = attach_priors(test, train, LABEL_IDS)

    assert result["pitcher_prior_0"].iloc[0] == pytest.approx(1.0)
    assert result["pitcher_prior_2"].iloc[0] == pytest.approx(0.0)


def test_unseen_pitcher_falls_back_to_league_prior():
    train = _train()
    test = pd.DataFrame({
        "pitcher": [999], "batter": [10], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, train, LABEL_IDS)
    lg = league_prior(train, LABEL_IDS)

    assert result["pitcher_prior_0"].iloc[0] == pytest.approx(lg[0])


def test_attach_priors_never_drops_rows():
    test = pd.DataFrame({
        "pitcher": [100, 999, 888], "batter": [10, 11, 12],
        "balls": [0, 1, 2], "strikes": [0, 0, 0],
        "target_pitch_label_id": [0, 1, 2],
    })

    result = attach_priors(test, _train(), LABEL_IDS)

    assert len(result) == 3


def test_attach_priors_never_multiplies_rows():
    """조인 키가 유일하지 않으면 행이 불어난다. 늘어난 행은 학습에서
    같은 상황을 여러 번 세게 만들어 지표를 조용히 왜곡한다."""
    test = pd.DataFrame({
        "pitcher": [100] * 4, "batter": [10, 10, 11, 11],
        "balls": [0, 0, 0, 0], "strikes": [0, 0, 0, 0],
        "target_pitch_label_id": [0, 1, 0, 1],
    })

    result = attach_priors(test, _train(), LABEL_IDS)

    assert len(result) == len(test)


def test_prior_columns_have_no_nan():
    test = pd.DataFrame({
        "pitcher": [100, 999], "batter": [10, 77],
        "balls": [0, 3], "strikes": [0, 2],
        "target_pitch_label_id": [0, 1],
    })

    result = attach_priors(test, _train(), LABEL_IDS)
    prior_cols = [c for c in result.columns if c.startswith(("pitcher_prior_", "count_prior_"))]

    assert not result[prior_cols].isna().any().any()


def test_unseen_count_falls_back_to_that_pitchers_arsenal():
    """카운트는 처음 봐도 투수는 아는 경우. 리그 평균이 아니라
    그 투수의 아스널로 채워야 정보가 덜 버려진다."""
    test = pd.DataFrame({
        "pitcher": [100], "batter": [10], "balls": [3], "strikes": [2],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, _train(), LABEL_IDS)

    assert result["count_prior_0"].iloc[0] == pytest.approx(result["pitcher_prior_0"].iloc[0])


def test_priors_keep_a_column_per_label():
    """라벨 하나당 컬럼 하나. split마다 개수가 다르면 모델 입력이 어긋난다."""
    result = attach_priors(_train(), _train(), LABEL_IDS)

    for i in LABEL_IDS:
        assert f"pitcher_prior_{i}" in result.columns
        assert f"count_prior_{i}" in result.columns


def _events():
    """(타자, 경기, 구종) 카운트. 게임 1이 train, 게임 9는 밖이다."""
    return pd.DataFrame({
        "batter":         [10,  11],
        "game_pk":        [1,   1],
        "pitch_label_id": [0,   0],
        "n":              [100, 100],
        "whiff_n":        [10,  30],
        "hardhit_n":      [40,  20],
        "xbh_n":          [5,   1],
    })


def test_batter_features_fall_back_to_train_mean_for_unseen_batter():
    test = pd.DataFrame({
        "pitcher": [100], "batter": [777], "game_pk": [1], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, _train(), LABEL_IDS, batter_events=_events())

    assert not result["batter_whiff_avg"].isna().any()
    # train 타자 평균 (0.1 + 0.3) / 2
    assert result["batter_whiff_avg"].iloc[0] == pytest.approx(0.2)


def test_batter_events_outside_train_do_not_shift_the_fallback():
    """이벤트 표에는 val/test 경기도 들어 있다. 폴백 평균이 그 값까지 쓰면
    미래 경기 정보가 train 피처로 새어 들어간다."""
    events = pd.concat([
        _events(),
        # 게임 9(train 밖)에서 타자 10이 라벨0을 100구 중 90번 헛스윙
        pd.DataFrame({"batter": [10], "game_pk": [9], "pitch_label_id": [0],
                      "n": [100], "whiff_n": [90], "hardhit_n": [0], "xbh_n": [0]}),
    ], ignore_index=True)
    test = pd.DataFrame({
        "pitcher": [100], "batter": [777], "game_pk": [1], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, _train(), LABEL_IDS, batter_events=events)

    assert result["batter_whiff_avg"].iloc[0] == pytest.approx(0.2)


def test_batter_events_from_batters_outside_train_do_not_shift_the_fallback():
    """train 경기에 나왔지만 학습 행에는 없는 타자도 폴백에 섞이면 안 된다."""
    events = pd.concat([
        _events(),
        pd.DataFrame({"batter": [999], "game_pk": [1], "pitch_label_id": [0],
                      "n": [100], "whiff_n": [90], "hardhit_n": [0], "xbh_n": [0]}),
    ], ignore_index=True)
    test = pd.DataFrame({
        "pitcher": [100], "batter": [777], "game_pk": [1], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, _train(), LABEL_IDS, batter_events=events)

    assert result["batter_whiff_avg"].iloc[0] == pytest.approx(0.2)


def test_attach_priors_does_not_mutate_inputs():
    train, events = _train(), _events()
    train_before, events_before = train.copy(), events.copy()
    test = pd.DataFrame({
        "pitcher": [100], "batter": [10], "game_pk": [1], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    attach_priors(test, train, LABEL_IDS, batter_events=events)

    pd.testing.assert_frame_equal(train, train_before)
    pd.testing.assert_frame_equal(events, events_before)
