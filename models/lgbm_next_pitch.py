"""다음 구종 예측 LightGBM 모델.

RandomForest 대비 선택 이유:
- 크기: RF 프로덕션 모델이 188MB인 반면 LightGBM은 수 MB 수준이다.
  Render 무료 티어(512MB) 제약이 풀린다.
- 정확도: 표 형태 다중분류에서 GBDT가 RF보다 일반적으로 우세하다.
  실측 근거 — 보강 피처를 넣은 RF는 깊이 제약을 풀어도 top1 0.4239에서 멈췄고,
  학습 없는 count_prior 룩업(0.4050)보다 겨우 나은 수준이었다. 신호는 있는데
  RF가 못 살린다고 판단해 모델을 바꾼다.
"""

import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

from models.next_pitch_model import ID_COLS, RANDOM_STATE, TARGET_COL

# prev_pitch_outcome은 문자열 원본이다. 모델은 prev_pitch_outcome_enc를 쓴다.
FEATURE_EXCLUDE = set(ID_COLS) | {TARGET_COL, "prev_pitch_outcome"}

DEFAULT_PARAMS = {
    "objective": "multiclass",
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 96,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": RANDOM_STATE,
    "num_threads": -1,
    "verbosity": -1,
}


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in FEATURE_EXCLUDE]


def train_lgbm(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    feature_cols: list[str],
    num_class: int = 11,
    params: dict | None = None,
    num_boost_round: int = 2000,
) -> lgb.Booster:
    merged = {**DEFAULT_PARAMS, "num_class": num_class, **(params or {})}
    train_set = lgb.Dataset(train_df[feature_cols], label=train_df[TARGET_COL])
    val_set = lgb.Dataset(val_df[feature_cols], label=val_df[TARGET_COL], reference=train_set)

    return lgb.train(
        merged,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)],
    )


def predict_proba(booster: lgb.Booster, X: pd.DataFrame) -> np.ndarray:
    return booster.predict(X, num_iteration=booster.best_iteration)


def save_model(booster: lgb.Booster, feature_cols: list[str], root: str, suffix: str = "") -> str:
    model_path = os.path.join(root, "models", f"next_pitch_lgbm{suffix}.txt")
    booster.save_model(model_path, num_iteration=booster.best_iteration)

    features_path = os.path.join(root, "models", f"next_pitch_lgbm{suffix}_features.json")
    with open(features_path, "w", encoding="utf-8") as f:
        json.dump({"feature_cols": feature_cols}, f, ensure_ascii=False, indent=2)
    return model_path
