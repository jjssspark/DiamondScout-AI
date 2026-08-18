"""GRU 시퀀스 모델 — 학습 전용 (Keras).

LSTM이 아니라 GRU를 쓰는 이유: 게이트가 3개(LSTM 4개)라 파라미터가 약 25% 적고
numpy 순전파 구현도 짧다. 이 규모에서 두 구조의 성능 차이는 통상 미미하다.
성능이 기존 LSTM보다 떨어지면 LSTM으로 되돌린다.

keras는 함수 안에서 import 한다. 모듈 최상단에 두면 TensorFlow가 없는 배포 환경에서
이 파일을 건드리는 것만으로 죽는다.
"""

import numpy as np

SEQ_LEN = 5


def build_model(seq_len: int, n_features: int, n_classes: int, units: int = 64):
    from keras import layers, models

    return models.Sequential([
        layers.Input(shape=(seq_len, n_features)),
        layers.GRU(units, name="gru"),
        layers.Dense(n_classes, activation="softmax", name="out"),
    ])


def export_weights(
    model, npz_path: str, mean: np.ndarray | None = None, std: np.ndarray | None = None
) -> None:
    """Keras GRU/Dense 가중치를 numpy 추론용 npz로 내보낸다.

    Keras GRU는 reset_after=True가 기본이라 recurrent bias가 따로 존재해
    bias 배열 shape이 (2, 3*units)가 된다. seq_infer.py가 이 규약을 따른다.

    mean/std는 학습에 쓴 표준화 통계다. 같이 저장해야 서빙에서 동일하게 적용할 수
    있다 - 따로 관리하면 언젠가 어긋나고, 그러면 입력 분포가 달라져 조용히 틀린
    확률이 나온다.
    """
    gru = model.get_layer("gru")
    dense = model.get_layer("out")
    w_x, w_h, bias = (np.asarray(w) for w in gru.get_weights())
    dense_w, dense_b = (np.asarray(w) for w in dense.get_weights())

    arrays = {
        "gru_kernel": w_x, "gru_recurrent": w_h, "gru_bias": bias,
        "dense_kernel": dense_w, "dense_bias": dense_b,
    }
    if mean is not None and std is not None:
        arrays["feature_mean"] = np.asarray(mean)
        arrays["feature_std"] = np.asarray(std)
    np.savez(npz_path, **arrays)
