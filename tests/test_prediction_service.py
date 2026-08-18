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
            service = PredictionService(root_dir="/fake/root", backend="rf")
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


# --- LightGBM 백엔드 -----------------------------------------------------------
#
# 여기서는 mock을 쓰지 않는다. 학습에 쓴 prior 테이블과 서빙이 읽는 테이블이 같은지가
# 이 백엔드의 핵심인데, mock 하면 바로 그 부분을 검증하지 못한다.

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LGBM_MODEL = os.path.join(ROOT, "models", "next_pitch_lgbm.txt")

pytestmark_lgbm = pytest.mark.skipif(
    not os.path.exists(_LGBM_MODEL), reason="LightGBM 아티팩트 없음 (scripts/train_lgbm.py 필요)"
)


def _lgbm_context(**overrides) -> dict:
    """CONTEXT + prior 조회용 식별자. pitcher/batter는 모델 피처가 아니라 조회 키다."""
    return {**CONTEXT, "pitcher": 607074, "batter": 621566, **overrides}


@pytestmark_lgbm
class TestLgbmBackend:
    def test_returns_same_shape_as_before(self):
        service = PredictionService(backend="lgbm")

        top3 = service.predict_top_k(_lgbm_context(), [_make_pitch(i) for i in range(LOOKBACK)], k=3)

        assert len(top3) == 3
        assert all(isinstance(label, str) and isinstance(p, float) for label, p in top3)
        assert top3 == sorted(top3, key=lambda t: -t[1])

    def test_full_proba_sums_to_one(self):
        service = PredictionService(backend="lgbm")

        proba = service.predict_full_proba(_lgbm_context(), [_make_pitch(i) for i in range(LOOKBACK)])

        assert abs(sum(proba.values()) - 1.0) < 1e-6

    def test_unknown_pitcher_does_not_raise(self):
        """prior를 못 찾는 투수도 예측이 실패하면 안 된다."""
        service = PredictionService(backend="lgbm")
        context = _lgbm_context(pitcher=999999, batter=999999)

        assert len(service.predict_top_k(context, [_make_pitch(i) for i in range(LOOKBACK)], k=3)) == 3

    def test_feature_row_covers_every_column_the_model_wants(self):
        """빠진 컬럼은 예외가 아니라 NaN이 된다. 모델은 그대로 돌고 정확도만 떨어져
        아무도 눈치채지 못한다 - TS-007/TS-009와 같은 계열의 사고다."""
        service = PredictionService(backend="lgbm")

        row = service._feature_row(_lgbm_context(), [_make_pitch(i) for i in range(LOOKBACK)])

        assert set(service.feature_cols) <= set(row)
        assert not [c for c in service.feature_cols if row[c] is None]

    def test_prior_values_match_the_training_table(self):
        """서빙 prior가 학습에 쓴 표와 다른 값이면 모델이 학습 때와 다른 분포를 받는다.
        prior는 모델 gain의 81%다."""
        import pandas as pd

        table = pd.read_csv(os.path.join(ROOT, "models", "serving_priors", "pitcher_prior.csv"))
        known = int(table["pitcher"].iloc[0])
        expected = float(table["pitcher_prior_0"].iloc[0])

        service = PredictionService(backend="lgbm")
        row = service._feature_row(
            _lgbm_context(pitcher=known), [_make_pitch(i) for i in range(LOOKBACK)]
        )

        assert row["pitcher_prior_0"] == pytest.approx(expected)

    def test_unknown_pitcher_falls_back_to_league_prior(self):
        import json

        with open(os.path.join(ROOT, "models", "serving_priors", "league_prior.json")) as f:
            league = json.load(f)

        service = PredictionService(backend="lgbm")
        row = service._feature_row(
            _lgbm_context(pitcher=999999), [_make_pitch(i) for i in range(LOOKBACK)]
        )

        assert row["pitcher_prior_0"] == pytest.approx(league["0"])

    def test_same_pitch_streak_counts_the_trailing_run(self):
        service = PredictionService(backend="lgbm")
        pitches = [_make_pitch(0), _make_pitch(1), _make_pitch(2), _make_pitch(2), _make_pitch(2)]

        row = service._feature_row(_lgbm_context(), pitches)

        assert row["same_pitch_streak"] == 3

    def test_first_pitch_flag_follows_the_count(self):
        service = PredictionService(backend="lgbm")
        pitches = [_make_pitch(i) for i in range(LOOKBACK)]

        fresh = service._feature_row(_lgbm_context(balls=0, strikes=0), pitches)
        deep = service._feature_row(_lgbm_context(balls=1, strikes=2), pitches)

        assert fresh["is_first_pitch_of_ab"] == 1
        assert deep["is_first_pitch_of_ab"] == 0
        assert deep["pitch_of_atbat"] == 4


# --- GRU 앙상블 ----------------------------------------------------------------

_SEQ_MODEL = os.path.join(ROOT, "models", "seq_model_weights.npz")

pytestmark_seq = pytest.mark.skipif(
    not (os.path.exists(_LGBM_MODEL) and os.path.exists(_SEQ_MODEL)),
    reason="LightGBM 또는 GRU 아티팩트 없음 (scripts/train_lgbm.py, train_seq.py 필요)",
)


@pytestmark_seq
class TestSeqEnsemble:
    def test_ensemble_is_on_by_default(self):
        assert PredictionService(backend="lgbm").seq is not None

    def test_ensemble_changes_the_probabilities(self):
        """섞이지 않으면 앙상블을 켠 의미가 없다. 값이 실제로 달라져야 한다."""
        pitches = [_make_pitch(i) for i in range(LOOKBACK)]

        solo = PredictionService(backend="lgbm", ensemble=False)
        mixed = PredictionService(backend="lgbm", ensemble=True)

        a = solo.predict_full_proba(_lgbm_context(), pitches)
        b = mixed.predict_full_proba(_lgbm_context(), pitches)

        assert set(a) == set(b)
        assert any(abs(a[k] - b[k]) > 1e-6 for k in a)

    def test_ensemble_proba_still_sums_to_one(self):
        """두 확률분포의 가중 평균이므로 합은 1이어야 한다. 어긋나면 정렬이 깨진 것이다."""
        service = PredictionService(backend="lgbm")

        proba = service.predict_full_proba(_lgbm_context(), [_make_pitch(i) for i in range(LOOKBACK)])

        assert abs(sum(proba.values()) - 1.0) < 1e-6

    def test_sequence_is_ordered_oldest_first(self):
        """recent_pitches[0]이 lag5, [-1]이 lag1이다. 뒤집으면 예외 없이 정확도만 깎인다.

        서비스가 만든 시퀀스 확률이, 같은 순서로 직접 쌓아 numpy 추론기에 넣은 것과
        일치하는지 본다.
        """
        from services.prediction_service import LAG_FIELDS

        service = PredictionService(backend="lgbm")
        pitches = [_make_pitch(i) for i in range(LOOKBACK)]

        expected_seq = np.array(
            [[[p[f] for f in LAG_FIELDS] for p in pitches]], dtype="float32"
        )
        expected = service.seq.predict_proba(service.seq.standardize(expected_seq))[0]

        assert np.allclose(service._seq_proba(pitches), expected)
        # 뒤집힌 순서와는 달라야 한다 - 아니면 이 테스트가 순서를 못 잡는다
        reversed_seq = expected_seq[:, ::-1, :]
        reversed_proba = service.seq.predict_proba(service.seq.standardize(reversed_seq))[0]
        assert not np.allclose(expected, reversed_proba)

    def test_falls_back_to_solo_when_weights_are_missing(self, tmp_path):
        """배포판에 npz가 빠져도 예측은 나와야 한다. 없으면 LightGBM 단독이다."""
        service = PredictionService(backend="lgbm", ensemble=False)

        assert service.seq is None
        assert service._load_seq(str(tmp_path / "없는파일.npz")) is None
