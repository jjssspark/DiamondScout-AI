"""GRU 순전파 numpy 구현 — 서빙 전용.

TensorFlow는 설치 용량이 수백 MB라 Render 무료 티어에 올릴 수 없다.
학습은 Keras로 하고 가중치만 npz로 받아 여기서 추론한다.
Keras GRU의 reset_after=True 규약을 따른다.

이 파일은 numpy 외에 아무것도 import 하지 않는다. keras/tensorflow를 끌어들이면
배포 의존성을 줄이려던 이유 자체가 사라진다.
"""

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(x: np.ndarray) -> np.ndarray:
    shifted = x - x.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


class SeqPredictor:
    def __init__(self, npz_path: str):
        w = np.load(npz_path)
        self.w_x = w["gru_kernel"]        # (n_feat, 3u)
        self.w_h = w["gru_recurrent"]     # (u, 3u)
        self.bias = w["gru_bias"]         # (2, 3u) — reset_after=True
        self.dense_w = w["dense_kernel"]
        self.dense_b = w["dense_bias"]
        self.units = self.w_h.shape[0]
        # 학습 때 쓴 표준화 통계. 없으면 표준화 없이 학습된 가중치로 본다.
        self.mean = w["feature_mean"] if "feature_mean" in w else None
        self.std = w["feature_std"] if "feature_std" in w else None

    def standardize(self, seq: np.ndarray) -> np.ndarray:
        """학습에 쓴 평균/표준편차를 그대로 적용한다. 서빙에서 다른 통계를 쓰면
        입력 분포가 달라져 조용히 틀린 확률이 나온다."""
        if self.mean is None or self.std is None:
            return seq
        return (seq - self.mean) / np.where(self.std == 0, 1.0, self.std)

    def predict_proba(self, seq: np.ndarray) -> np.ndarray:
        """seq: (batch, seq_len, n_features) -> (batch, n_classes)"""
        x = np.asarray(seq, dtype=np.float64)
        batch = x.shape[0]
        u = self.units
        b_x, b_h = self.bias[0], self.bias[1]

        h = np.zeros((batch, u), dtype=np.float64)
        for t in range(x.shape[1]):
            mat_x = x[:, t, :] @ self.w_x + b_x
            mat_h = h @ self.w_h + b_h

            z = _sigmoid(mat_x[:, :u] + mat_h[:, :u])
            r = _sigmoid(mat_x[:, u:2 * u] + mat_h[:, u:2 * u])
            # reset_after=True: reset gate를 recurrent 행렬곱 '이후'에 곱한다
            n = np.tanh(mat_x[:, 2 * u:] + r * mat_h[:, 2 * u:])
            h = z * h + (1.0 - z) * n

        return _softmax(h @ self.dense_w + self.dense_b)
