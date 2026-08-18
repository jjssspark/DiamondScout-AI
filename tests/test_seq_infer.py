"""numpy GRU 순전파가 Keras 출력과 일치하는지 검증한다.

이 테스트가 없으면 서빙 경로가 조용히 틀린 확률을 낼 수 있다.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.seq_infer import SeqPredictor

pytest.importorskip("keras", reason="학습 전용 의존성 — 배포 환경에는 없음")

SEQ_LEN, N_FEAT, N_CLASS = 5, 6, 11


@pytest.fixture
def trained_pair(tmp_path):
    """작은 Keras GRU를 만들고 npz로 내보낸 뒤 (keras_model, SeqPredictor)를 돌려준다."""
    from models.seq_next_pitch import build_model, export_weights

    model = build_model(seq_len=SEQ_LEN, n_features=N_FEAT, n_classes=N_CLASS, units=16)
    npz_path = tmp_path / "w.npz"
    export_weights(model, str(npz_path))
    return model, SeqPredictor(str(npz_path))


def test_numpy_matches_keras_output(trained_pair):
    model, predictor = trained_pair
    x = np.random.default_rng(0).normal(size=(4, SEQ_LEN, N_FEAT)).astype("float32")

    keras_out = model.predict(x, verbose=0)
    numpy_out = predictor.predict_proba(x)

    assert np.allclose(keras_out, numpy_out, atol=1e-5)


def test_output_shape(trained_pair):
    _, predictor = trained_pair
    x = np.zeros((3, SEQ_LEN, N_FEAT), dtype="float32")

    assert predictor.predict_proba(x).shape == (3, N_CLASS)


def test_probabilities_sum_to_one(trained_pair):
    _, predictor = trained_pair
    x = np.random.default_rng(1).normal(size=(5, SEQ_LEN, N_FEAT)).astype("float32")

    assert np.allclose(predictor.predict_proba(x).sum(axis=1), 1.0, atol=1e-6)


def test_matches_keras_after_weights_change(trained_pair, tmp_path):
    """초기 가중치는 대칭이라 게이트 순서가 틀려도 우연히 맞을 수 있다.
    학습된 것처럼 흔든 뒤에도 일치해야 순전파가 실제로 맞는 것이다."""
    from models.seq_next_pitch import export_weights

    model, _ = trained_pair
    rng = np.random.default_rng(7)
    model.set_weights([rng.normal(scale=0.5, size=w.shape) for w in model.get_weights()])

    npz_path = tmp_path / "shaken.npz"
    export_weights(model, str(npz_path))
    x = rng.normal(size=(6, SEQ_LEN, N_FEAT)).astype("float32")

    assert np.allclose(
        model.predict(x, verbose=0), SeqPredictor(str(npz_path)).predict_proba(x), atol=1e-5
    )


def test_single_row_batch_works(trained_pair):
    """서빙은 한 번에 1건을 예측한다. batch=1에서 shape이 뭉개지면 안 된다."""
    _, predictor = trained_pair
    x = np.zeros((1, SEQ_LEN, N_FEAT), dtype="float32")

    assert predictor.predict_proba(x).shape == (1, N_CLASS)
