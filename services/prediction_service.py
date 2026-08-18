"""
DiamondScout AI - 예측 서비스
LightGBM(models/next_pitch_lgbm.txt)을 로드해 다음 구종 Top-k를 예측한다.
backend="rf"를 주면 기존 RandomForest(models/next_pitch_model.joblib) 경로로 돌아간다.

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

LGBM_MODEL_FILE = "next_pitch_lgbm.txt"
LGBM_FEATURES_FILE = "next_pitch_lgbm_features.json"
SERVING_PRIOR_DIR = "serving_priors"

# GRU 가중치. numpy 추론기(models/seq_infer.py)가 읽으므로 TensorFlow는 필요 없다.
SEQ_MODEL_FILE = "seq_model_weights.npz"

# 앙상블 가중치: p = (1-w)*LightGBM + w*GRU. val에서 고른 값이다.
# w=0.05~0.35 구간이 전부 단독을 넘었고 0.30이 제일 좋았다. test에서 top-1 43.71 ->
# 44.13%, top-3 85.73 -> 86.44%. 근거는 docs/PERFORMANCE.md와
# output/metrics/ensemble_gate_2025.json.
SEQ_ENSEMBLE_WEIGHT = 0.30

# next_pitch_dataset_{year}.csv의 현재 상황 feature와 동일한 순서/이름을 따른다.
CONTEXT_COLS = [
    "balls", "strikes", "outs_when_up", "inning", "inning_topbot_enc",
    "on_1b", "on_2b", "on_3b", "score_diff", "stand_enc", "p_throws_enc",
]
# lag1~lag5 컬럼을 만들 때 사용하는 필드 (data/preprocess_statcast.py의 CONTINUOUS_LAG_COLS + pitch_label_id 순서)
LAG_FIELDS = ["pitch_label_id", "release_speed", "pfx_x", "pfx_z", "plate_x", "plate_z", "zone_cell", "balls", "strikes"]
LOOKBACK = 5

BATTER_FEATURE_COLS = [
    "batter_whiff_avg", "batter_hardhit_avg", "batter_xbh_avg", "batter_whiff_max",
]


def build_feature_row(context: dict, recent_pitches: list[dict], priors: dict | None = None) -> dict:
    """context(현재 상황) + recent_pitches(과거 -> 최근 순으로 정확히 5개)를 모델 입력
    feature dict로 변환한다.

    recent_pitches[-1]이 바로 직전 투구이며 lag1이 된다 (data/preprocess_statcast.py의
    lag1=바로 이전 구 정의와 동일하게 맞춤).

    priors는 LightGBM 백엔드가 넘기는 prior · 시간 피처다. RandomForest는 이 컬럼들을
    학습하지 않았으므로 넘기지 않는다.
    """
    if len(recent_pitches) != LOOKBACK:
        raise ValueError(f"recent_pitches는 정확히 {LOOKBACK}개(과거->최근 순)여야 합니다. 받은 개수: {len(recent_pitches)}")

    row = {col: context[col] for col in CONTEXT_COLS}
    for lag in range(1, LOOKBACK + 1):
        pitch = recent_pitches[-lag]
        for field in LAG_FIELDS:
            row[f"{field}_lag{lag}"] = pitch[field]
    if priors:
        row.update(priors)
    return row


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


class PriorLookup:
    """학습에 쓴 prior 표를 그대로 읽어 조회한다.

    data/build_enriched_dataset.py::save_serving_priors가 학습 데이터와 **같이** 내보낸
    파일만 읽는다. count_pitch_profile 같은 다른 집계로 대신하면 스무딩 여부와 집계
    구간이 달라져 모델이 학습 때와 다른 분포를 받는다 - prior는 모델 gain의 81%다.
    """

    def __init__(self, prior_dir: str):
        self.label_ids = self._read_league(os.path.join(prior_dir, "league_prior.json"))
        self.pitcher = self._read_table(
            os.path.join(prior_dir, "pitcher_prior.csv"), ["pitcher"], "pitcher_prior"
        )
        self.count = self._read_table(
            os.path.join(prior_dir, "count_prior.csv"),
            ["pitcher", "balls", "strikes"], "count_prior",
        )
        self.batter, self.batter_mean, self.batter_cols = self._read_batter(
            os.path.join(prior_dir, "batter_features.csv")
        )
        with open(os.path.join(prior_dir, "temporal_defaults.json"), "r", encoding="utf-8") as f:
            self.temporal_defaults = json.load(f)

    def _read_league(self, path: str) -> list[int]:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.league = {int(k): float(v) for k, v in raw.items()}
        return sorted(self.league)

    def _read_table(self, path: str, key_cols: list[str], prefix: str) -> dict:
        table = pd.read_csv(path)
        value_cols = [f"{prefix}_{i}" for i in self.label_ids]
        keys = table[key_cols].astype(int).itertuples(index=False, name=None)
        return dict(zip(keys, table[value_cols].to_numpy().tolist()))

    def _read_batter(self, path: str) -> tuple[dict, list[float], list[str]]:
        """컬럼 목록은 파일 헤더에서 읽는다.

        타자 x 구종 피처가 붙으면서 컬럼이 4개에서 수십 개로 늘었다. 여기에 목록을
        하드코딩해 두면 학습 쪽에 컬럼이 추가될 때마다 같이 고쳐야 하고, 안 고치면
        모델이 학습 때와 다른 입력을 받는다 - 예외 없이 정확도만 떨어진다.
        """
        if not os.path.exists(path):
            return {}, [0.0] * len(BATTER_FEATURE_COLS), list(BATTER_FEATURE_COLS)
        table = pd.read_csv(path)
        cols = [c for c in table.columns if c != "batter"]
        values = table[cols].to_numpy()
        lookup = dict(zip(table["batter"].astype(int), values.tolist()))
        return lookup, values.mean(axis=0).tolist(), cols

    def features(self, pitcher_id, batter_id, balls: int, strikes: int) -> dict[str, float]:
        """조회에 실패해도 예외를 내지 않는다. 처음 보는 투수/타자여도 예측은 나와야 한다."""
        league = [self.league[i] for i in self.label_ids]
        pitcher = self.pitcher.get((_as_int(pitcher_id),), league)
        # 카운트를 못 찾으면 그 투수의 아스널로 (학습 때의 폴백 순서와 같다)
        count = self.count.get((_as_int(pitcher_id), int(balls), int(strikes)), pitcher)
        batter = self.batter.get(_as_int(batter_id), self.batter_mean)

        out = {f"pitcher_prior_{i}": v for i, v in zip(self.label_ids, pitcher)}
        out.update({f"count_prior_{i}": v for i, v in zip(self.label_ids, count)})
        out.update(dict(zip(self.batter_cols, batter)))
        return out


def temporal_features(context: dict, recent_pitches: list[dict], defaults: dict) -> dict:
    """서빙 시점에 알 수 있는 시간 피처만 만들고, 나머지는 train 대표값으로 채운다.

    앱은 경기 상태를 모른다 - 받는 건 볼카운트와 합성한 최근 5구뿐이다. 그래서
    pitcher_pitch_count_game / times_through_order / prev_pitch_outcome_enc는 관측할 수
    없다. 세 피처의 gain 중요도 합은 0.89%이고, 고정했을 때 test top1이 0.4371 ->
    0.4325로 0.46%p만 떨어지는 것을 실측으로 확인했다.
    """
    balls, strikes = int(context["balls"]), int(context["strikes"])

    # 파울은 카운트를 올리지 않아 실제 타석 내 투구수보다 작게 나온다(일치율 84.9%).
    pitch_of_atbat = balls + strikes + 1

    last_label = recent_pitches[-1]["pitch_label_id"]
    streak = 0
    for pitch in reversed(recent_pitches):
        if pitch["pitch_label_id"] != last_label:
            break
        streak += 1

    return {
        "pitch_of_atbat": pitch_of_atbat,
        "is_first_pitch_of_ab": int(balls == 0 and strikes == 0),
        "same_pitch_streak": streak,
        **defaults,
    }


class PredictionService:
    """LightGBM(기본) 또는 RandomForest로 다음 구종을 예측한다."""

    def __init__(
        self,
        root_dir: str = ROOT_DIR,
        load_deep_model: bool = False,
        backend: str = "lgbm",
        ensemble: bool = True,
    ):
        self.root_dir = root_dir
        self.backend = backend
        self.ensemble = ensemble
        self.seq = None
        self.id_to_label = self._load_label_mapping()
        self.priors = None

        if backend == "lgbm":
            self._load_lgbm()
        elif backend == "rf":
            rf_bundle = joblib.load(os.path.join(root_dir, "models", PITCH_MODEL_FILE))
            self.model = rf_bundle["model"]
            self.feature_cols = rf_bundle["feature_cols"]
        else:
            raise ValueError(f"알 수 없는 backend: {backend!r} (lgbm 또는 rf)")

        self.deep_model = None
        if load_deep_model:
            self.deep_model = self._load_deep_model()

    def _load_lgbm(self) -> None:
        import lightgbm as lgb

        models_dir = os.path.join(self.root_dir, "models")
        self.model = lgb.Booster(model_file=os.path.join(models_dir, LGBM_MODEL_FILE))
        with open(os.path.join(models_dir, LGBM_FEATURES_FILE), "r", encoding="utf-8") as f:
            self.feature_cols = json.load(f)["feature_cols"]
        self.priors = PriorLookup(os.path.join(models_dir, SERVING_PRIOR_DIR))
        self.classes = np.array(self.priors.label_ids)
        if self.ensemble:
            self.seq = self._load_seq(os.path.join(models_dir, SEQ_MODEL_FILE))

    def _load_seq(self, path: str):
        """GRU 추론기를 로드한다. 없거나 클래스 수가 안 맞으면 단독 예측으로 돌아간다.

        클래스 수를 확인하는 이유: 두 모델의 확률을 자리별로 더하므로 라벨 순서가
        어긋나면 예외 없이 엉뚱한 구종 확률이 섞인다. 조용히 틀리느니 안 섞는 게 낫다.
        """
        if not os.path.exists(path):
            return None

        from models.seq_infer import SeqPredictor

        predictor = SeqPredictor(path)
        if len(predictor.dense_b) != len(self.classes):
            return None
        return predictor

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

    def _feature_row(self, context: dict, recent_pitches: list[dict]) -> dict:
        if self.priors is None:
            return build_feature_row(context, recent_pitches)

        extra = self.priors.features(
            context.get("pitcher"), context.get("batter"),
            context["balls"], context["strikes"],
        )
        extra.update(temporal_features(context, recent_pitches, self.priors.temporal_defaults))
        return build_feature_row(context, recent_pitches, priors=extra)

    def _seq_proba(self, recent_pitches: list[dict]) -> np.ndarray:
        """recent_pitches를 (1, 5, 9) 시퀀스로 만들어 GRU 확률을 뽑는다.

        시간 순서는 오래된 것 -> 최근 순이다. recent_pitches[0]이 lag5,
        recent_pitches[-1]이 lag1이고, 학습(scripts/train_seq.py)의 to_sequences가
        lag5부터 쌓는 것과 같은 방향이다. 뒤집으면 예외 없이 정확도만 떨어진다.
        """
        seq = np.array(
            [[[pitch[field] for field in LAG_FIELDS] for pitch in recent_pitches]],
            dtype="float32",
        )
        return self.seq.predict_proba(self.seq.standardize(seq))[0]

    def _predict_proba(self, context: dict, recent_pitches: list[dict]) -> tuple[np.ndarray, np.ndarray]:
        x = pd.DataFrame([self._feature_row(context, recent_pitches)])[self.feature_cols]
        if self.backend == "lgbm":
            proba = self.model.predict(x, num_iteration=self.model.best_iteration)[0]
            if self.seq is not None:
                w = SEQ_ENSEMBLE_WEIGHT
                proba = (1 - w) * proba + w * self._seq_proba(recent_pitches)
            return self.classes, proba
        return self.model.classes_, self.model.predict_proba(x)[0]

    def predict_top_k(self, context: dict, recent_pitches: list[dict], k: int = 3) -> list[tuple[str, float]]:
        """Top-k (구종, 확률) 리스트를 반환한다."""
        classes, proba = self._predict_proba(context, recent_pitches)
        top_idx = np.argsort(proba)[::-1][:k]
        return [(self.id_to_label[classes[i]], float(proba[i])) for i in top_idx]

    def predict_full_proba(self, context: dict, recent_pitches: list[dict]) -> dict[str, float]:
        """모든 구종에 대한 확률 딕셔너리 (위험도 계산 등에서 사용)."""
        classes, proba = self._predict_proba(context, recent_pitches)
        return {self.id_to_label[c]: float(p) for c, p in zip(classes, proba)}
