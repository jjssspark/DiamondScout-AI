"""
DiamondScout AI - 예측 서비스
저장된 RandomForest(models/next_pitch_model.joblib)를 로드해 다음 구종 Top-k를 예측한다.
딥러닝 모델(models/deep_next_pitch_model.keras)은 TensorFlow가 무거운 의존성이므로
기본적으로는 로드하지 않고, load_deep_model=True일 때만 선택적으로 로드하는 구조만 준비한다.
"""

import json
import os

import joblib
import numpy as np
import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 무료 티어(512MB) 배포판은 축소 학습한 next_pitch_model_deploy.joblib을 쓴다.
# 번들 스키마가 같아 파일명만 바꿔 끼우면 되므로 환경변수로 선택한다(scripts/train_deploy_model.py).
PITCH_MODEL_FILE = os.environ.get("PITCH_MODEL_FILE", "next_pitch_model.joblib")

# next_pitch_dataset_{year}.csv의 현재 상황 feature와 동일한 순서/이름을 따른다.
CONTEXT_COLS = [
    "balls", "strikes", "outs_when_up", "inning", "inning_topbot_enc",
    "on_1b", "on_2b", "on_3b", "score_diff", "stand_enc", "p_throws_enc",
]
# lag1~lag5 컬럼을 만들 때 사용하는 필드 (data/preprocess_statcast.py의 CONTINUOUS_LAG_COLS + pitch_label_id 순서)
LAG_FIELDS = ["pitch_label_id", "release_speed", "pfx_x", "pfx_z", "plate_x", "plate_z", "zone_cell", "balls", "strikes"]
LOOKBACK = 5


def build_feature_row(context: dict, recent_pitches: list[dict]) -> dict:
    """context(현재 상황) + recent_pitches(과거 -> 최근 순으로 정확히 5개)를 모델 입력
    feature dict로 변환한다.

    recent_pitches[-1]이 바로 직전 투구이며 lag1이 된다 (data/preprocess_statcast.py의
    lag1=바로 이전 구 정의와 동일하게 맞춤).
    """
    if len(recent_pitches) != LOOKBACK:
        raise ValueError(f"recent_pitches는 정확히 {LOOKBACK}개(과거->최근 순)여야 합니다. 받은 개수: {len(recent_pitches)}")

    row = {col: context[col] for col in CONTEXT_COLS}
    for lag in range(1, LOOKBACK + 1):
        pitch = recent_pitches[-lag]
        for field in LAG_FIELDS:
            row[f"{field}_lag{lag}"] = pitch[field]
    return row


class PredictionService:
    """RandomForest(필수) + 딥러닝(선택) 모델을 로드해 다음 구종을 예측한다."""

    def __init__(self, root_dir: str = ROOT_DIR, load_deep_model: bool = False):
        self.root_dir = root_dir
        self.id_to_label = self._load_label_mapping()

        rf_bundle = joblib.load(os.path.join(root_dir, "models", PITCH_MODEL_FILE))
        self.rf_model = rf_bundle["model"]
        self.feature_cols = rf_bundle["feature_cols"]

        self.deep_model = None
        if load_deep_model:
            self.deep_model = self._load_deep_model()

    def _load_label_mapping(self) -> dict[int, str]:
        path = os.path.join(self.root_dir, "data", "processed", "pitch_label_mapping.json")
        with open(path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        return {int(k): v for k, v in mapping["id_to_label"].items()}

    def _load_deep_model(self):
        # TensorFlow는 선택적 의존성이라 실제로 필요할 때만 import한다.
        from tensorflow import keras

        model_path = os.path.join(self.root_dir, "models", "deep_next_pitch_model.keras")
        return keras.models.load_model(model_path)

    def _predict_proba(self, context: dict, recent_pitches: list[dict]) -> tuple[np.ndarray, np.ndarray]:
        row = build_feature_row(context, recent_pitches)
        x = pd.DataFrame([row])[self.feature_cols]
        proba = self.rf_model.predict_proba(x)[0]
        return self.rf_model.classes_, proba

    def predict_top_k(self, context: dict, recent_pitches: list[dict], k: int = 3) -> list[tuple[str, float]]:
        """RandomForest 기준 Top-k (구종, 확률) 리스트를 반환한다."""
        classes, proba = self._predict_proba(context, recent_pitches)
        top_idx = np.argsort(proba)[::-1][:k]
        return [(self.id_to_label[classes[i]], float(proba[i])) for i in top_idx]

    def predict_full_proba(self, context: dict, recent_pitches: list[dict]) -> dict[str, float]:
        """모든 구종에 대한 확률 딕셔너리 (위험도 계산 등에서 사용)."""
        classes, proba = self._predict_proba(context, recent_pitches)
        return {self.id_to_label[c]: float(p) for c, p in zip(classes, proba)}
