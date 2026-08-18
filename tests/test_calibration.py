"""확률 캘리브레이션 테스트.

앱이 예측 확률을 화면에 그대로 띄우므로 "포심 31.7%"가 실제 빈도와 맞아야 한다.
온도 스케일링은 순위를 안 바꾸므로 top-k 정확도는 그대로 두고 확신도만 조정한다.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.calibration import apply_temperature, expected_calibration_error, fit_temperature


def test_ece_is_zero_for_perfectly_calibrated_confident_predictions():
    """항상 100% 확신하고 항상 맞히면 ECE는 0이다."""
    proba = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    y = np.array([0, 0, 1])

    assert expected_calibration_error(proba, y) == pytest.approx(0.0, abs=1e-9)


def test_ece_is_high_for_overconfident_wrong_predictions():
    """항상 100% 확신하는데 항상 틀리면 ECE는 1이다."""
    proba = np.array([[1.0, 0.0], [1.0, 0.0]])
    y = np.array([1, 1])

    assert expected_calibration_error(proba, y) == pytest.approx(1.0, abs=1e-9)


def test_apply_temperature_preserves_argmax():
    """온도 스케일링은 순위를 안 바꾼다. 그래서 top-k 정확도가 유지된다."""
    proba = np.array([[0.6, 0.3, 0.1], [0.1, 0.2, 0.7]])

    scaled = apply_temperature(proba, T=2.5)

    assert np.array_equal(scaled.argmax(axis=1), proba.argmax(axis=1))


def test_apply_temperature_output_sums_to_one():
    proba = np.array([[0.6, 0.3, 0.1], [0.1, 0.2, 0.7]])

    assert np.allclose(apply_temperature(proba, T=2.5).sum(axis=1), 1.0)


def test_apply_temperature_above_one_lowers_confidence():
    """T > 1이면 확신도가 낮아져야 한다. 방향이 반대면 부호를 잘못 쓴 것이다."""
    proba = np.array([[0.8, 0.15, 0.05]])

    assert apply_temperature(proba, T=2.0).max() < proba.max()
    assert apply_temperature(proba, T=0.5).max() > proba.max()


def test_apply_temperature_of_one_is_identity():
    proba = np.array([[0.6, 0.3, 0.1], [0.1, 0.2, 0.7]])

    assert np.allclose(apply_temperature(proba, T=1.0), proba)


def test_fit_temperature_softens_overconfident_model():
    """과확신 모델에는 T > 1이 나와야 한다. 확률을 눌러야 하므로."""
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, size=500)
    proba = np.full((500, 3), 0.01)
    for i, label in enumerate(y):
        proba[i, label if i % 2 == 0 else (label + 1) % 3] = 0.98
    proba = proba / proba.sum(axis=1, keepdims=True)

    assert fit_temperature(proba, y) > 1.0


def test_fit_temperature_leaves_calibrated_model_alone():
    """이미 확신도와 정확도가 맞는 모델이면 T가 1 근처여야 한다."""
    rng = np.random.default_rng(1)
    n = 4000
    proba = rng.dirichlet([2.0, 2.0, 2.0], size=n)
    # 예측 확률 그대로의 분포에서 정답을 뽑으면 정의상 캘리브레이션이 맞는다
    y = np.array([rng.choice(3, p=row) for row in proba])

    assert fit_temperature(proba, y) == pytest.approx(1.0, abs=0.15)
