"""확률 캘리브레이션 — 온도 스케일링.

앱이 예측 확률을 화면에 그대로 표시하므로 "포심 31.7%"가 실제 빈도와 맞아야 한다.
온도 스케일링은 순위를 바꾸지 않아 top-k 정확도를 그대로 두면서 확신도만 조정한다.
정확도를 올리는 작업이 아니라 표시하는 숫자를 정직하게 만드는 작업이다.

서빙은 apply_temperature만 쓴다. numpy만 있으면 되고 scipy는 T를 찾을 때만 필요하다.
"""

import numpy as np

EPS = 1e-12


def expected_calibration_error(proba: np.ndarray, y: np.ndarray, n_bins: int = 15) -> float:
    """예측 확신도와 실제 정확도의 가중 절대차.

    확신도를 구간으로 나눠, 각 구간에서 "평균 확신도"와 "실제 맞힌 비율"이 얼마나
    벌어지는지 재고 표본 수로 가중 평균한다. 0에 가까울수록 표시 확률이 정직하다.
    """
    proba = np.asarray(proba)
    confidence = proba.max(axis=1)
    correct = (proba.argmax(axis=1) == np.asarray(y)).astype(float)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (confidence > lo) & (confidence <= hi)
        if lo == 0.0:
            mask |= confidence == 0.0
        if not mask.any():
            continue
        ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(ece)


def apply_temperature(proba: np.ndarray, T: float) -> np.ndarray:
    """확률을 로짓으로 되돌려 T로 나눈 뒤 다시 softmax 한다.

    T > 1이면 분포가 평평해져 확신도가 내려가고, T < 1이면 뾰족해진다.
    모든 로짓을 같은 수로 나누므로 순위는 그대로다.
    """
    logits = np.log(np.clip(np.asarray(proba, dtype=float), EPS, None)) / T
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_temperature(proba: np.ndarray, y: np.ndarray) -> float:
    """val에서 negative log-likelihood를 최소화하는 T를 찾는다.

    ECE가 아니라 NLL을 최소화한다. ECE는 구간을 나눠 계산해서 구간 경계에 따라
    값이 튀고 미분도 안 되지만, NLL은 매끄러워서 1차원 최적화가 안정적이다.

    scipy는 여기서만 필요하다. 서빙은 apply_temperature만 쓰므로 함수 안에서
    import 해서 추론 경로가 scipy를 안 건드리게 한다.
    """
    from scipy.optimize import minimize_scalar

    y = np.asarray(y)
    rows = np.arange(len(y))

    def nll(T: float) -> float:
        scaled = apply_temperature(proba, T)
        return float(-np.log(np.clip(scaled[rows, y], EPS, None)).mean())

    return float(minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded").x)
