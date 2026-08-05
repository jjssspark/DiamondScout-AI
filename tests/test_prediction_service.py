"""PredictionService의 핵심 플로우(피처 조립 -> Top-k 예측) 테스트.

models/*.joblib, data/processed/pitch_label_mapping.json은 용량 문제로 git에 커밋되지
않으므로(.gitignore), 이 파일에 실제로 의존하지 않도록 joblib.load와 라벨 매핑 로드를
mock으로 격리한다.
"""

import os
import sys
from unittest.mock import MagicMock, mock_open, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.prediction_service import LOOKBACK, PredictionService, build_feature_row

CONTEXT = {
    "balls": 1, "strikes": 2, "outs_when_up": 1, "inning": 3, "inning_topbot_enc": 0,
    "on_1b": 1, "on_2b": 0, "on_3b": 0, "score_diff": -1, "stand_enc": 1, "p_throws_enc": 0,
}


def _make_pitch(i: int) -> dict:
    return {
        "pitch_label_id": i, "release_speed": 90.0 + i, "pfx_x": 0.1 * i, "pfx_z": 0.2 * i,
        "plate_x": 0.0, "plate_z": 2.0, "zone_cell": 5, "balls": 0, "strikes": i % 3,
    }


class TestBuildFeatureRow:
    def test_raises_when_recent_pitches_count_is_not_lookback(self):
        with pytest.raises(ValueError, match=f"정확히 {LOOKBACK}개"):
            build_feature_row(CONTEXT, [_make_pitch(i) for i in range(3)])

    def test_lag1_comes_from_the_last_pitch_in_the_list(self):
        recent_pitches = [_make_pitch(i) for i in range(LOOKBACK)]

        row = build_feature_row(CONTEXT, recent_pitches)

        last_pitch = recent_pitches[-1]
        assert row["pitch_label_id_lag1"] == last_pitch["pitch_label_id"]
        assert row["release_speed_lag1"] == last_pitch["release_speed"]

    def test_lag5_comes_from_the_first_pitch_in_the_list(self):
        recent_pitches = [_make_pitch(i) for i in range(LOOKBACK)]

        row = build_feature_row(CONTEXT, recent_pitches)

        first_pitch = recent_pitches[0]
        assert row["pitch_label_id_lag5"] == first_pitch["pitch_label_id"]

    def test_includes_all_context_columns(self):
        row = build_feature_row(CONTEXT, [_make_pitch(i) for i in range(LOOKBACK)])

        for col, value in CONTEXT.items():
            assert row[col] == value


class TestPredictTopK:
    def _build_service_with_mocked_model(self, proba_by_class: dict[int, float]) -> PredictionService:
        classes = np.array(sorted(proba_by_class))
        proba = np.array([proba_by_class[c] for c in classes])
        mock_rf_model = MagicMock()
        mock_rf_model.classes_ = classes
        mock_rf_model.predict_proba.return_value = np.array([proba])

        id_to_label = {0: "FF", 1: "SL", 2: "CU"}
        label_json = (
            '{"id_to_label": {"0": "FF", "1": "SL", "2": "CU"}}'
        )

        with patch("services.prediction_service.joblib.load") as mock_joblib_load, \
             patch("builtins.open", mock_open(read_data=label_json)):
            mock_joblib_load.return_value = {
                "model": mock_rf_model,
                "feature_cols": list(CONTEXT.keys()),
            }
            service = PredictionService(root_dir="/fake/root")
        assert service.id_to_label == id_to_label
        return service

    def test_returns_top_k_sorted_by_probability_descending(self):
        service = self._build_service_with_mocked_model({0: 0.2, 1: 0.5, 2: 0.3})

        result = service.predict_top_k(CONTEXT, [_make_pitch(i) for i in range(LOOKBACK)], k=2)

        assert result == [("SL", 0.5), ("CU", 0.3)]

    def test_k_limits_result_length(self):
        service = self._build_service_with_mocked_model({0: 0.2, 1: 0.5, 2: 0.3})

        result = service.predict_top_k(CONTEXT, [_make_pitch(i) for i in range(LOOKBACK)], k=1)

        assert len(result) == 1
        assert result[0][0] == "SL"
