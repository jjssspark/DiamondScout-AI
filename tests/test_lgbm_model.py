import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.lgbm_next_pitch import get_feature_columns, predict_proba, train_lgbm

RNG = np.random.default_rng(0)


def _toy_split(n=400):
    x1 = RNG.normal(size=n)
    # 라벨이 x1에 의존하게 만들어 학습이 실제로 되는지 확인 가능하게 한다
    y = (x1 > 0.5).astype(int) + (x1 > 1.2).astype(int)
    return pd.DataFrame({"x1": x1, "x2": RNG.normal(size=n), "target_pitch_label_id": y})


def test_predict_proba_shape_matches_class_count():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    assert predict_proba(booster, val[["x1", "x2"]]).shape == (len(val), 3)


def test_probabilities_sum_to_one():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    proba = predict_proba(booster, val[["x1", "x2"]])

    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_learns_signal_better_than_random():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    proba = predict_proba(booster, val[["x1", "x2"]])
    acc = (proba.argmax(axis=1) == val["target_pitch_label_id"]).mean()

    assert acc > 0.5


def test_feature_columns_exclude_ids_and_target():
    """ID나 타깃이 피처로 새면 정확도가 가짜로 뛴다."""
    df = pd.DataFrame(columns=[
        "game_date", "game_pk", "pitcher", "batter", "at_bat_number", "pitch_number",
        "prev_pitch_outcome", "target_pitch_label_id", "balls", "count_prior_0",
    ])

    cols = get_feature_columns(df)

    assert cols == ["balls", "count_prior_0"]


def test_feature_columns_drop_the_raw_outcome_string():
    """prev_pitch_outcome은 문자열이다. 남으면 LightGBM이 학습 시점에 죽는다."""
    df = pd.DataFrame({"prev_pitch_outcome": ["ball"], "prev_pitch_outcome_enc": [1]})

    cols = get_feature_columns(df)

    assert "prev_pitch_outcome" not in cols
    assert "prev_pitch_outcome_enc" in cols


def test_early_stopping_keeps_a_best_iteration():
    """best_iteration이 0이면 predict가 전체 트리를 쓴다 - 과적합 방어가 사라진다."""
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3, num_boost_round=500)

    assert booster.best_iteration > 0
    assert booster.best_iteration <= 500
