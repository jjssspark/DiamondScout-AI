"""
DiamondScout AI - 전력분석(스카우팅) 서비스
PredictionService의 다음 구종 예측 결과에 투수/타자별 위험 프로파일(zone_risk_profile,
batter_matchup_profile, pitcher_pitch_profile)을 결합해 투수 모드/타자 모드 분석 결과를
만든다. LLM은 아직 연결하지 않고 사용자 코멘트는 키워드 기반 rule-based로만 해석한다.
"""

import json
import os
from dataclasses import dataclass, field

import pandas as pd

from services.prediction_service import PredictionService

# zone_cell 1~9는 row*3+col+1 (row0=존 하단, col0=좌측) 규칙을 따른다
# (data/preprocess_statcast.py add_zone_cell 참고). 3x3 히트맵/좌표 추정에 재사용한다.
ZONE_ROW_OF_CELL = {cell: (cell - 1) // 3 for cell in range(1, 10)}
ZONE_COL_OF_CELL = {cell: (cell - 1) % 3 for cell in range(1, 10)}

# 스트라이크존 폭(±0.83ft)을 3등분한 좌우 대표 좌표, 존 높이를 0~1로 정규화한 상하 대표 비율.
_ZONE_HALF_WIDTH = 0.83
ZONE_CELL_X_CENTER = {
    cell: (ZONE_COL_OF_CELL[cell] - 1) * (2 * _ZONE_HALF_WIDTH / 3)
    for cell in range(1, 10)
}
ZONE_CELL_Z_FRACTION = {
    cell: (ZONE_ROW_OF_CELL[cell] + 0.5) / 3
    for cell in range(1, 10)
}

# zone_height_fraction_estimate(0~1)을 실제 plate_z(ft)로 되돌릴 때 쓰는 스트라이크존 상하 경계.
PLATE_Z_ZONE_BOTTOM_FT = 1.5
PLATE_Z_ZONE_TOP_FT = 3.5

LOOKBACK = 5

# 구종 약어 -> 한글 전체 이름. 화면/리포트/Q&A에 FF, SL 같은 약어 대신 이 이름을 노출한다.
PITCH_LABEL_KR = {
    "FF": "포심 패스트볼",
    "SI": "싱커",
    "SL": "슬라이더",
    "CH": "체인지업",
    "ST": "스위퍼",
    "FC": "커터",
    "CU": "커브",
    "FS": "스플리터",
    "KC": "너클커브",
    "SV": "슬러브",
    "OTHER": "기타 구종",
}


def pitch_label_kr(label: str) -> str:
    return PITCH_LABEL_KR.get(label, label)


_PLAYER_NAMES: dict[int, str] | None = None


def _player_name_lookup() -> dict[int, str]:
    """data/processed/player_names.csv를 한 번만 읽어 캐시한다.

    Statcast raw의 player_name은 투수 이름만 담아서 타자 이름을 여기서 따로 만든다
    (data/player_names.py 참고). 파일이 없으면 빈 표를 돌려주고 호출부가 ID 폴백을 쓴다.
    """
    global _PLAYER_NAMES
    if _PLAYER_NAMES is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "processed", "player_names.csv")
        try:
            table = pd.read_csv(path)
            _PLAYER_NAMES = dict(zip(table["player_id"].astype(int), table["player_name"]))
        except (FileNotFoundError, KeyError, ValueError):
            _PLAYER_NAMES = {}
    return _PLAYER_NAMES


def get_batter_display(batter_id: int) -> str:
    """타자 표시 이름. 룩업에 없으면 'Batter ID {id}'로 떨어진다."""
    return _player_name_lookup().get(int(batter_id), f"Batter ID {batter_id}")


# 최근 5구 자동 생성 시 구종별로 사용하는 안전한 구속(mph)/무브먼트(ft) 기본값.
# (data/processed/*.csv에는 구종별 평균 구속/무브먼트가 없어, 일반적인 MLB 구종 특성을 반영한
# 고정값을 사용한다. 실제 값이 아니라 데모/시연용 근사치임을 build_default_recent_pitches 문서에 명시.)
PITCH_TYPE_DEFAULTS = {
    "FF": {"release_speed": 93.5, "pfx_x": 0.6, "pfx_z": 1.4},
    "SI": {"release_speed": 92.5, "pfx_x": 1.2, "pfx_z": 0.6},
    "SL": {"release_speed": 84.5, "pfx_x": -0.4, "pfx_z": 0.2},
    "CH": {"release_speed": 85.0, "pfx_x": 1.0, "pfx_z": 0.6},
    "ST": {"release_speed": 81.0, "pfx_x": -1.0, "pfx_z": 0.1},
    "FC": {"release_speed": 88.0, "pfx_x": -0.2, "pfx_z": 0.6},
    "CU": {"release_speed": 78.0, "pfx_x": -0.6, "pfx_z": -0.8},
    "FS": {"release_speed": 84.0, "pfx_x": 0.5, "pfx_z": 0.1},
    "KC": {"release_speed": 78.5, "pfx_x": -0.4, "pfx_z": -0.6},
    "SV": {"release_speed": 80.0, "pfx_x": -1.2, "pfx_z": -0.2},
    "OTHER": {"release_speed": 85.0, "pfx_x": 0.0, "pfx_z": 0.5},
}


@dataclass
class ScoutingRequest:
    mode: str  # "pitcher" 또는 "batter"
    pitcher_id: int
    context: dict  # balls, strikes, outs_when_up, inning, inning_topbot_enc, on_1b/2b/3b, score_diff, stand_enc, p_throws_enc
    recent_pitches: list[dict] = field(default_factory=list)  # 과거->최근 순 정확히 5개
    user_comment: str = ""
    batter_id: int | None = None
    stand: str | None = None  # "R"/"L", batter_matchup_profile 조회용
    p_throws: str | None = None  # "R"/"L", batter_matchup_profile 조회용


class ScoutingService:
    def __init__(self, root_dir: str | None = None, prediction_service: PredictionService | None = None):
        self.root_dir = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.prediction_service = prediction_service or PredictionService(root_dir=self.root_dir)
        self.zone_risk_df = self._load_csv("zone_risk_profile_2025.csv")
        self.batter_matchup_df = self._load_csv("batter_matchup_profile_2025.csv")
        self.pitcher_profile_df = self._load_csv("pitcher_pitch_profile_2025.csv")
        # pitcher별 p_throws(투구 손) 최빈값 lookup. data/raw/statcast_2025_full.csv(242MB, 59만행)를
        # 매번 로드하기엔 너무 무거워, pitcher,p_throws 두 컬럼만 미리 집계해 저장한 파생 파일.
        self.pitcher_throws_df = self._load_csv("pitcher_throws_2025.csv")
        # 투수+카운트별 구종 비율. 추천구종/예상구종 재랭킹에서 "이 카운트에 실제로 무엇을
        # 던지는가"를 반영하기 위해 사용한다 (기존에는 로드만 안 하고 있던 미사용 파일이었음).
        self.count_pitch_df = self._load_csv("count_pitch_profile_2025.csv")
        # 2021~2025 시즌 가중 평균(2025=1.0 ~ 2021=0.30, data/build_multi_year_profiles.py 생성).
        # 2025 표본이 부족한 선수/조합에서만 보완용으로 쓰고, 2025 표본이 충분하면 항상 2025를
        # 우선한다(아래 _pitcher_rows/_batter_matchup_rows/_zone_risk_rows 참고).
        self.pitcher_profile_multi_df = self._load_csv("pitcher_pitch_profile_multi_year.csv")
        self.batter_matchup_multi_df = self._load_csv("batter_matchup_profile_multi_year.csv")
        self.zone_risk_multi_df = self._load_csv("zone_risk_profile_multi_year.csv")
        self.count_pitch_multi_df = self._load_csv("count_pitch_profile_multi_year.csv")
        self.label_to_id, self.id_to_label = self._load_label_mapping()

    # ---- 멀티시즌 표본 보완 (2025 표본 부족 시에만 사용, 표본 충분하면 2025 우선) ------------

    # 표본 threshold 재검토: 기존 50/15/8은 너무 보수적이어서 2025 표본이 부족한 선수도
    # "표본 부족" 안내 없이 사실상 리그 평균에 가까운 값으로 계속 나오는 경우가 있었다.
    # 값을 낮춰 2021~2025 가중 프로필(선수별로 실제 차이가 있는 데이터)을 더 적극적으로 쓴다.
    _MULTI_YEAR_MIN_PITCHER_PITCHES = 30
    _MULTI_YEAR_MIN_BATTER_PITCHES = 10
    _MULTI_YEAR_MIN_ZONE_PITCHES = 5

    def _pitcher_rows(self, pitcher_id: int) -> tuple[pd.DataFrame, bool]:
        rows = self.pitcher_profile_df[self.pitcher_profile_df["pitcher"] == pitcher_id]
        total = float(rows["pitcher_total_pitches"].iloc[0]) if not rows.empty else 0.0
        if total >= self._MULTI_YEAR_MIN_PITCHER_PITCHES:
            return rows, False
        multi_rows = self.pitcher_profile_multi_df[self.pitcher_profile_multi_df["pitcher"] == pitcher_id]
        if not multi_rows.empty:
            return multi_rows, True
        return rows, False

    def _batter_matchup_rows(self, batter_id: int) -> tuple[pd.DataFrame, bool]:
        rows = self.batter_matchup_df[self.batter_matchup_df["batter"] == batter_id]
        total = float(rows["pitch_count"].sum()) if not rows.empty else 0.0
        if total >= self._MULTI_YEAR_MIN_BATTER_PITCHES:
            return rows, False
        multi_rows = self.batter_matchup_multi_df[self.batter_matchup_multi_df["batter"] == batter_id]
        if not multi_rows.empty:
            return multi_rows, True
        return rows, False

    def _zone_risk_rows(self, pitcher_id: int, pitch_label: str) -> tuple[pd.DataFrame, bool]:
        rows = self.zone_risk_df[
            (self.zone_risk_df["pitcher"] == pitcher_id) & (self.zone_risk_df["pitch_label"] == pitch_label)
        ]
        total = float(rows["pitch_count"].sum()) if not rows.empty else 0.0
        if total >= self._MULTI_YEAR_MIN_ZONE_PITCHES:
            return rows, False
        multi_rows = self.zone_risk_multi_df[
            (self.zone_risk_multi_df["pitcher"] == pitcher_id) & (self.zone_risk_multi_df["pitch_label"] == pitch_label)
        ]
        if not multi_rows.empty:
            return multi_rows, True
        return rows, False

    def _load_csv(self, filename: str) -> pd.DataFrame:
        path = os.path.join(self.root_dir, "data", "processed", filename)
        return pd.read_csv(path)

    def _load_label_mapping(self) -> tuple[dict[str, int], dict[int, str]]:
        path = os.path.join(self.root_dir, "data", "processed", "pitch_label_mapping.json")
        with open(path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        return mapping["label_to_id"], {int(k): v for k, v in mapping["id_to_label"].items()}

    def analyze(self, request: ScoutingRequest) -> dict:
        if request.mode not in ("pitcher", "batter"):
            raise ValueError(f"알 수 없는 mode: {request.mode!r} (pitcher 또는 batter만 지원)")

        full_proba = self.prediction_service.predict_full_proba(request.context, request.recent_pitches)
        interpretation = self._interpret_user_comment(request.user_comment)

        # 모델의 원 예측 확률만으로는 pitcher_id/batter_id/카운트 성향이 충분히 반영되지 않아
        # (모델 feature에 선수 ID가 없고, 카운트도 11개 feature 중 하나일 뿐) 서비스 레벨에서
        # 실제 구종 구사율/카운트 성향/상대 매치업/구종 위험도/코멘트를 결합해 재랭킹한다.
        # 투수 모드="던졌을 때 유리한 공", 타자 모드="실제로 올 가능성이 높은 공"으로 목적이 달라
        # 서로 다른 스코어링 함수를 쓴다.
        if request.mode == "pitcher":
            composite_scores, fallback, score_breakdown = self._score_pitcher_pitch_candidates(
                request.pitcher_id, request.batter_id, request.context, full_proba, interpretation
            )
        else:
            composite_scores, fallback, score_breakdown = self._score_batter_expected_pitch(
                request.pitcher_id, request.context, full_proba, interpretation
            )
        top3 = sorted(composite_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
        model_top3 = self.prediction_service.predict_top_k(request.context, request.recent_pitches, k=3)

        result = {
            "predicted_top3_pitches": [{"pitch_label": label, "probability": prob} for label, prob in top3],
            "model_top3_pitches": [{"pitch_label": label, "probability": prob} for label, prob in model_top3],
            "risk_summary": self._build_risk_summary(request.pitcher_id, top3),
            "user_comment_interpretation": interpretation,
            "pitch_risk_details": self._build_pitch_risk_details(request.pitcher_id, top3),
            # Q&A에서 top3 밖의 구종("슬라이더가 낫지 않아?" 같은 비교 질문)도 조회할 수 있도록
            # 이 투수가 실제로 던지는 모든 구종의 재랭킹 점수를 함께 담아둔다.
            "all_pitch_scores": composite_scores,
            # 구종별 최종 점수의 구성요소(model_score/pitcher_mix_score/count_tendency_score/
            # batter_weakness_score/zone_safety_score/context_adjustment/comment_adjustment/
            # final_score). 리포트·Q&A가 "왜 이 점수인지"를 수치로 설명할 때 사용한다.
            "score_breakdown": score_breakdown,
            "fallback_used": fallback["used"],
            "fallback_reason": fallback["reason"],
        }

        if request.mode == "pitcher":
            result["pitcher_mode_result"] = self._build_pitcher_mode_result(
                request, top3, composite_scores, interpretation
            )
            zone_scores_for_debug = result["pitcher_mode_result"]["zone_danger_scores"]
        else:
            result["batter_mode_result"] = self._build_batter_mode_result(request, top3, interpretation)
            zone_scores_for_debug = result["batter_mode_result"]["zone_probability_scores"]

        result["sensitivity_debug"] = self._build_sensitivity_debug(
            request.mode, top3[0][0], score_breakdown, zone_scores_for_debug
        )

        return result

    def _build_sensitivity_debug(
        self, mode: str, top_pitch: str, score_breakdown: dict, zone_scores: dict,
    ) -> dict:
        """"상황/선수를 바꿔도 결과가 안 바뀐다"는 체감을 검증하기 위한 디버그 정보. Q&A의
        game_situation_sensitivity_question/player_sensitivity_question이 실제 수치로 답할 때
        쓰고, 리포트/개발자 검증에도 그대로 노출한다. per_pitch_before_after에 후보 구종 전체의
        "상황/코멘트 보정 전(score_before_adjustment) vs 보정 후(score_after_adjustment)"를
        담아, top1뿐 아니라 Top-3 전체가 얼마나 움직였는지 확인할 수 있게 한다."""
        factor_keys = [
            "model_score", "pitcher_mix_score", "count_tendency_score",
            "batter_weakness_score", "zone_safety_score",
        ]
        per_pitch_before_after: dict[str, dict] = {}
        for label, b in score_breakdown.items():
            base = sum(b.get(k, 0.0) for k in factor_keys)
            context_adj = b.get("context_adjustment", 1.0)
            comment_adj = b.get("comment_adjustment", 1.0)
            per_pitch_before_after[label] = {
                "score_before_adjustment": round(base, 4),
                "score_after_adjustment": round(base * context_adj * comment_adj, 4),
                "final_score": b.get("final_score", 0.0),
            }

        top_breakdown = score_breakdown.get(top_pitch, {})
        top_factors = sorted(
            ({"factor": k, "value": top_breakdown.get(k, 0.0)} for k in factor_keys),
            key=lambda item: abs(item["value"]), reverse=True,
        )
        zone_values = [v for cell, v in zone_scores.items() if cell != 0] or [0.0]
        return {
            "top_pitch": top_pitch,
            "top_factors": top_factors,
            "score_before_adjustment": per_pitch_before_after.get(top_pitch, {}).get("score_before_adjustment"),
            "score_after_adjustment": per_pitch_before_after.get(top_pitch, {}).get("score_after_adjustment"),
            "per_pitch_before_after": per_pitch_before_after,
            "changed_by_context": round(top_breakdown.get("context_adjustment", 1.0) - 1.0, 4),
            "changed_by_player": (
                round(top_breakdown.get("batter_weakness_score", 0.0), 4) if mode == "pitcher" else None
            ),
            "zone_variation_summary": {
                "min": round(min(zone_values), 4),
                "max": round(max(zone_values), 4),
                "range": round(max(zone_values) - min(zone_values), 4),
            },
        }

    # ---- 선수 이름/최근 5구 자동 생성 --------------------------------------

    def get_pitcher_name(self, pitcher_id: int) -> str:
        rows = self.pitcher_profile_df[self.pitcher_profile_df["pitcher"] == pitcher_id]
        if rows.empty:
            return f"Pitcher ID {pitcher_id}"
        return str(rows.iloc[0]["player_name"])

    def get_batter_stand(self, batter_id: int) -> str:
        """batter_matchup_profile의 stand 컬럼 최빈값으로 타자의 타석 방향을 추정한다.
        데이터가 없으면 기본값 "L"을 사용한다."""
        rows = self.batter_matchup_df[self.batter_matchup_df["batter"] == batter_id]
        if rows.empty:
            return "L"
        return str(rows["stand"].mode().iat[0])

    def get_pitcher_throws(self, pitcher_id: int) -> str:
        """pitcher_throws_2025.csv(투수별 p_throws 최빈값 lookup)로 투구 방향을 추정한다.
        데이터가 없으면 기본값 "L"을 사용한다."""
        rows = self.pitcher_throws_df[self.pitcher_throws_df["pitcher"] == pitcher_id]
        if rows.empty:
            return "L"
        return str(rows.iloc[0]["p_throws"])

    def build_default_recent_pitches(self, pitcher_id: int) -> list[dict]:
        """해당 투수의 pitcher_pitch_profile 기준 실제 구종 구성 비율로 최근 5구를 자동
        생성한다. 구속/무브먼트는 구종별 안전한 기본값(PITCH_TYPE_DEFAULTS)을, 위치는
        zone_risk_profile에서 해당 투수+구종이 가장 많이 던진 zone_cell 추정치를 사용한다.
        해당 투수 데이터가 전혀 없으면 검증된 Rodón, Carlos 샘플로 대체한다."""
        rows = self.pitcher_profile_df[self.pitcher_profile_df["pitcher"] == pitcher_id]
        if rows.empty:
            return self._fallback_recent_pitches()

        rows = rows.sort_values("pitch_count", ascending=False)
        labels = rows["pitch_label"].tolist()
        sequence: list[str] = []
        while len(sequence) < LOOKBACK:
            sequence.extend(labels)
        # 가장 많이 던진 구종이 맨 뒤(=최근/lag1)에 오도록 뒤집어 최근 투구 감각과 맞춘다.
        ordered = list(reversed(sequence[:LOOKBACK]))

        count_progression = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)]
        pitches = []
        for i, label in enumerate(ordered):
            loc = self._estimate_location(pitcher_id, label)
            defaults = PITCH_TYPE_DEFAULTS.get(label, PITCH_TYPE_DEFAULTS["OTHER"])
            balls, strikes = count_progression[i]
            pitches.append({
                "pitch_label_id": self.label_to_id[label],
                "pitch_label": label,
                "release_speed": defaults["release_speed"],
                "pfx_x": defaults["pfx_x"],
                "pfx_z": defaults["pfx_z"],
                "plate_x": loc["plate_x_estimate"],
                "plate_z": self._zone_fraction_to_feet(loc["zone_height_fraction_estimate"]),
                "zone_cell": loc["zone_cell"],
                "balls": balls,
                "strikes": strikes,
            })
        return pitches

    def _zone_fraction_to_feet(self, fraction: float) -> float:
        return round(PLATE_Z_ZONE_BOTTOM_FT + fraction * (PLATE_Z_ZONE_TOP_FT - PLATE_Z_ZONE_BOTTOM_FT), 3)

    def _fallback_recent_pitches(self) -> list[dict]:
        """scripts/test_scouting_service.py에서 검증된 Rodón, Carlos(pitcher=607074) 샘플."""
        raw = [
            (92.8, 0.98, 1.44, 0.014, 2.107, 5, 0, 0),
            (92.4, 0.82, 1.35, 1.181, 2.444, 0, 0, 0),
            (92.3, 1.06, 1.49, 0.495, 2.598, 6, 1, 0),
            (91.5, 0.99, 1.35, -0.634, 3.376, 7, 1, 1),
            (93.1, 0.84, 1.41, -0.941, 1.978, 0, 1, 2),
        ]
        return [
            {
                "pitch_label_id": self.label_to_id["FF"],
                "pitch_label": "FF",
                "release_speed": r[0], "pfx_x": r[1], "pfx_z": r[2],
                "plate_x": r[3], "plate_z": r[4], "zone_cell": r[5], "balls": r[6], "strikes": r[7],
            }
            for r in raw
        ]

    # ---- 공통: 위험 요약 -------------------------------------------------

    def _build_risk_summary(self, pitcher_id: int, top3: list[tuple[str, float]]) -> dict:
        """예측된 top3 구종에 대한 해당 투수의 zone_risk_profile 평균으로 위험 지표를 요약한다."""
        labels = [label for label, _ in top3]
        rows = self.zone_risk_df[
            (self.zone_risk_df["pitcher"] == pitcher_id) & (self.zone_risk_df["pitch_label"].isin(labels))
        ]
        if rows.empty:
            return {
                "pattern_exposure_risk": round(top3[0][1], 4) if top3 else None,
                "extra_base_hit_risk": None,
                "home_run_risk": None,
                "walk_risk": None,
                "note": "해당 투수의 zone_risk_profile 데이터가 부족합니다.",
            }

        return {
            # top1 예측 확률이 높을수록 상대에게 패턴이 쉽게 읽힌다는 의미로 사용
            "pattern_exposure_risk": round(top3[0][1], 4),
            "extra_base_hit_risk": round(float(rows["extra_base_hit_rate"].mean()), 4),
            "home_run_risk": round(float(rows["home_run_rate"].mean()), 4),
            "walk_risk": round(float(rows["ball_rate"].mean()), 4),
        }

    def _build_pitch_risk_details(self, pitcher_id: int, top3: list[tuple[str, float]]) -> dict:
        """Q&A에서 "패스트볼 컨택되면?", "슬라이더가 낫지 않아?" 같이 특정 구종을 콕 집어
        묻는 질문에 top3 밖의 구종으로도 답할 수 있도록, 이 투수가 실제로 던지는 모든 구종의
        개별 위험 지표를 계산해둔다(표시는 top3 위주지만 조회는 전체 레퍼토리 대상)."""
        labels = {label for label, _ in top3}
        pitcher_rows = self.pitcher_profile_df[self.pitcher_profile_df["pitcher"] == pitcher_id]
        labels |= set(pitcher_rows["pitch_label"])
        details: dict[str, dict | None] = {}
        for label in labels:
            rows = self.zone_risk_df[
                (self.zone_risk_df["pitcher"] == pitcher_id) & (self.zone_risk_df["pitch_label"] == label)
            ]
            if rows.empty:
                details[label] = None
                continue
            details[label] = {
                "extra_base_hit_risk": round(float(rows["extra_base_hit_rate"].mean()), 4),
                "home_run_risk": round(float(rows["home_run_rate"].mean()), 4),
                "hard_hit_risk": round(float(rows["hard_hit_rate"].mean()), 4),
                "ball_rate": round(float(rows["ball_rate"].mean()), 4),
            }
        return details

    # ---- 사용자 코멘트 해석 (rule-based) ----------------------------------

    def _interpret_user_comment(self, comment: str) -> dict:
        text = comment or ""
        tags: list[str] = []
        prefer_low = any(k in text for k in ["낮게", "떨어지는", "바닥", "낮은 코스"])
        prefer_high = any(k in text for k in ["높은 공", "하이", "높게", "위쪽"])
        prefer_corner = any(k in text for k in ["바깥쪽", "아웃코스", "몸쪽", "인코스", "구석", "존 밖"])
        evasive = any(k in text for k in ["빼고", "뺄", "빼려", "고의4구", "볼넷", "피하고 싶", "위험하게 안", "살살"])
        aggressive = any(k in text for k in ["적극적으로", "정면승부", "존 안으로", "스트존 채워", "밀어붙"])

        if prefer_low:
            tags.append("prefer_low_zone")
        if prefer_high:
            tags.append("prefer_high_zone")
        if prefer_corner:
            tags.append("prefer_zone_corner")
        if evasive:
            tags.append("evasive_pitching")
        if aggressive:
            tags.append("aggressive_pitching")

        summary_parts = []
        if evasive:
            summary_parts.append("스트라이크존 밖으로 빼는 볼 배합을 선호하는 것으로 해석됨(볼넷 위험은 감수)")
        if aggressive:
            summary_parts.append("존 안쪽 승부를 선호하는 것으로 해석됨(피안타 위험은 감수)")
        if prefer_low:
            summary_parts.append("낮은 코스 선호")
        if prefer_high:
            summary_parts.append("높은 코스 선호")
        if prefer_corner:
            summary_parts.append("존 모서리 코스 선호")
        summary = ", ".join(summary_parts) if summary_parts else "특별한 코스/전략 선호가 감지되지 않음"

        return {
            "raw_comment": text,
            "tags": tags,
            "prefer_low": prefer_low,
            "prefer_high": prefer_high,
            "prefer_corner": prefer_corner,
            "decrease_strike_risk": evasive,
            "increase_aggression": aggressive,
            "summary": summary,
        }

    # ---- 투수 모드 ---------------------------------------------------------

    def _build_pitcher_mode_result(
        self, request: ScoutingRequest, top3: list[tuple[str, float]],
        composite_scores: dict[str, float], interpretation: dict,
    ) -> dict:
        pitcher_id = request.pitcher_id
        recommended = top3[0][0]
        # 재랭킹 점수(모델확률+구사율+카운트성향+상대약점-위험도)가 가장 낮은, 즉 이 투수의
        # 실제 레퍼토리 중 지금 던지기에 가장 불리한 구종을 회피 구종으로 선정한다.
        avoid_pitch = min(composite_scores, key=composite_scores.get) if composite_scores else None
        heatmap_scores = self._build_zone_heatmap(pitcher_id, recommended, interpretation)
        coaching_message = self._build_coaching_message(recommended, avoid_pitch, interpretation)

        p_throws = request.p_throws or ("R" if request.context.get("p_throws_enc") == 1 else "L")
        batter_weakness = self._build_batter_weakness_summary(request.batter_id, p_throws)

        zone_danger_scores = self._build_zone_danger_scores(
            pitcher_id, recommended, request.batter_id, request.context, interpretation
        )
        best_zone_cell = min(range(1, 10), key=lambda c: zone_danger_scores[c])
        # 화면에 "몇 % 확률로 피안타/위험 타구를 맞는지"를 보여주기 위한 표시 전용 값.
        # 추천 구종/best_zone_cell 선정에 쓰이는 zone_danger_scores는 그대로 두고, 보여주는 숫자의
        # 의미만 risky_contact_rate 우선으로 바꾼다(원본 데이터에 hit_rate 컬럼은 없어 그 다음
        # 우선순위인 risky_contact_rate를 쓰고, 그마저 없으면 기존 조합으로 대체한다).
        zone_hit_risk_scores = self._build_zone_hit_risk_display(
            pitcher_id, recommended, request.batter_id, request.context, interpretation
        )
        # 리포트에 "이 투수의 2025 구종 비율"을 설명하기 위해, 타자 모드에서 쓰는 것과 동일한
        # 구종 구사 비중 요약을 재사용한다 (자기 자신의 구종 패턴이므로 pitcher_id 그대로 전달).
        own_pattern = self._build_pitcher_pattern_summary(pitcher_id)

        return {
            "recommended_pitch": recommended,
            "avoid_pitch": avoid_pitch,
            "zone_heatmap_scores": heatmap_scores,  # zone_cell 1~9 순서의 9개 score (구사 비중, 합=1)
            "coaching_message": coaching_message,
            "batter_weakness": batter_weakness,
            "zone_danger_scores": zone_danger_scores,  # zone_cell 0~9의 피안타/장타 위험 점수 (낮을수록 안전)
            "zone_hit_risk_scores": zone_hit_risk_scores,  # zone_cell 0~9, 화면 표시용 "피안타 위험" 확률(0~1)
            "best_zone_cell": best_zone_cell,
            "own_pitch_pattern": own_pattern,
        }

    # ---- 추천구종 재랭킹 (모델확률 + 실제 데이터 결합) ------------------------

    _BREAKING_OFFSPEED_PITCHES = {"SL", "CU", "ST", "KC", "SV", "FS", "CH"}

    def _count_pitch_ratios(self, pitcher_id: int, balls: int, strikes: int) -> dict[str, float]:
        """투수+카운트별 실제 구종 비율(count_pitch_profile). 2025 표본(해당 카운트 투구 수)이
        3구 미만이면 멀티시즌 가중 프로필로 대체하고, 그마저 부족하면 빈 dict를 반환해 호출부가
        투수 전체 구종 비율로 대체하게 한다. (기존 5구 기준은 카운트별 표본이 원래 작아 실제
        카운트 성향 대신 전체 비율로 자주 대체되어 "카운트를 바꿔도 결과가 안 바뀌는" 원인 중
        하나였다 - 임계값을 낮춰 실제 카운트별 데이터를 더 자주 사용한다.)"""
        rows = self.count_pitch_df[
            (self.count_pitch_df["pitcher"] == pitcher_id)
            & (self.count_pitch_df["balls"] == balls)
            & (self.count_pitch_df["strikes"] == strikes)
        ]
        if not rows.empty and rows["pitch_count"].sum() >= 3:
            return {r["pitch_label"]: float(r["pitch_ratio"]) for _, r in rows.iterrows()}

        multi_rows = self.count_pitch_multi_df[
            (self.count_pitch_multi_df["pitcher"] == pitcher_id)
            & (self.count_pitch_multi_df["balls"] == balls)
            & (self.count_pitch_multi_df["strikes"] == strikes)
        ]
        if not multi_rows.empty and multi_rows["pitch_count"].sum() >= 3:
            return {r["pitch_label"]: float(r["pitch_ratio"]) for _, r in multi_rows.iterrows()}
        return {}

    def _pitch_overall_danger(self, pitcher_id: int, pitch_label: str) -> float:
        """해당 투수+구종의 zone_risk_profile 전체 평균 위험도((장타율+하드히트율)/2). 2025 표본이
        부족하면 멀티시즌 프로필로 보완하고(_zone_risk_rows), 그마저 없으면 MLB 평균에 가까운
        근사치 0.08을 사용한다."""
        rows, _ = self._zone_risk_rows(pitcher_id, pitch_label)
        if rows.empty:
            return 0.08
        return float((rows["extra_base_hit_rate"].mean() + rows["hard_hit_rate"].mean()) / 2)

    def _batter_pitch_effectiveness_for_pitcher(self, batter_id: int | None, pitch_label: str) -> float:
        """상대 타자가 이 구종에 얼마나 약한지(투수 입장에서 유리한 정도)를 0.05~1.0 사이 값으로
        반환한다. 헛스윙률이 높고 장타/하드히트율이 낮을수록 투수에게 유리하다. 타자 미지정이면
        중립값 0.5를 반환하고, 2025 표본이 부족하면 _batter_matchup_rows가 멀티시즌으로 보완한다."""
        if batter_id is None:
            return 0.5
        batter_rows, _ = self._batter_matchup_rows(batter_id)
        rows = batter_rows[batter_rows["pitch_label"] == pitch_label]
        if rows.empty or rows["pitch_count"].sum() < 5:
            return 0.5
        total = rows["pitch_count"].sum()
        whiff = float((rows["whiff_rate"] * rows["pitch_count"]).sum() / total)
        hard_hit = float((rows["hard_hit_rate"] * rows["pitch_count"]).sum() / total)
        xbh = float((rows["extra_base_hit_rate"] * rows["pitch_count"]).sum() / total)
        danger = (hard_hit + xbh) / 2
        # 헛스윙률 기준치(MLB 평균 약 25%)보다 높으면 가점, 위험도가 높으면 감점. 배수(1.4)는
        # "상대 타자가 특정 구종에 강하면 그 구종이 실제로 더 내려가야 한다"는 요구에 맞춰
        # 편차를 증폭한 것 - whiff_rate/hard_hit_rate/extra_base_hit_rate 자체는 조작하지
        # 않고, 그 편차가 최종 점수에 미치는 영향만 키운다.
        effectiveness = 0.5 + (whiff - 0.25) * 1.4 - danger * 1.4
        return max(0.05, min(1.0, effectiveness))

    def _comment_pitch_bias(self, pitch_label: str, interpretation: dict) -> float:
        """전략 코멘트가 구종 '선택' 자체에 주는 가중치(존 위치가 아니라 어떤 구종을 던질지).
        '빼고 싶다' 계열은 유인구 성향이 강한 변화구/오프스피드를, '정면승부' 계열은 제구가
        상대적으로 쉬운 포심을 선호하는 경향을 반영한다."""
        mult = 1.0
        if interpretation["decrease_strike_risk"] and pitch_label in self._BREAKING_OFFSPEED_PITCHES:
            mult *= 1.25
        if interpretation["increase_aggression"] and pitch_label == "FF":
            mult *= 1.2
        return mult

    def _context_adjustment_factor(self, pitch_label: str, relative_danger: float, context: dict) -> float:
        """경기 상황(카운트/주자/점수차/아웃)이 구종 점수에 주는 보정 배수(1.0=중립).

        relative_danger는 절대 위험도(보통 0.05~0.2 범위, 후보 구종 간 차이가 작음)가 아니라
        "이 투수의 후보 구종들 중에서 상대적으로 얼마나 위험한 편인가"를 0~1로 min-max
        정규화한 값이다(호출부 _relative_danger_map 참고). 절대값을 그대로 곱하면 모든 후보
        구종에 거의 같은 배수가 곱해져 정규화(합=1) 이후 차이가 상쇄되어 버려서, 득점권/점수차
        같은 상황을 바꿔도 추천이 거의 안 바뀌는 문제가 있었다 - 상대적 위험도를 쓰면 "이
        투수 기준 가장 위험한 구종"과 "가장 안전한 구종" 사이에 실제로 눈에 띄는 격차가 생긴다."""
        factor = 1.0
        balls, strikes = context.get("balls", 0), context.get("strikes", 0)
        is_breaking = pitch_label in self._BREAKING_OFFSPEED_PITCHES

        # 2스트라이크(특히 0-2): 유인구 성격의 변화구/오프스피드가 더 유리해진다.
        if strikes >= 2:
            factor *= 1.35 if is_breaking else 0.85
        # 3볼(3-0/3-1): 볼넷 부담이 커 제구가 검증된 패스트볼 계열이 더 유리해진다.
        if balls >= 3:
            factor *= 0.75 if is_breaking else 1.25

        runners_in_scoring = bool(context.get("on_2b") or context.get("on_3b"))
        runners_on = runners_in_scoring or bool(context.get("on_1b"))
        if runners_in_scoring:
            # 득점권: 장타 한 방이 실점으로 직결되므로 상대적으로 위험한 구종을 크게 감점한다.
            factor *= max(0.35, 1.0 - 0.65 * relative_danger)
        elif runners_on:
            factor *= max(0.6, 1.0 - 0.35 * relative_danger)

        score_diff = context.get("score_diff", 0)
        if abs(score_diff) <= 1:
            factor *= max(0.5, 1.0 - 0.45 * relative_danger)  # 박빙: 위험 구종을 더 강하게 피한다
        elif score_diff <= -4:
            # 크게 뒤지는 상황: 장타 한 방을 더 내주면 안 되니 위험 구종을 더 피한다
            factor *= max(0.45, 1.0 - 0.5 * relative_danger)
        elif score_diff >= 4:
            # 크게 앞서는 상황: 위험 감수 여유가 있어 감점 폭을 줄여 공격적인 구종도 살린다
            factor *= max(0.85, 1.0 - 0.1 * relative_danger)

        if context.get("outs_when_up", 1) == 0:
            factor *= max(0.65, 1.0 - 0.3 * relative_danger)  # 무사: 신중하게
        elif context.get("outs_when_up", 1) == 2:
            factor *= min(1.2, 1.0 + 0.15 * relative_danger)  # 2아웃: 상대적으로 공격적으로

        return factor

    @staticmethod
    def _relative_danger_map(danger_by_label: dict[str, float]) -> dict[str, float]:
        """후보 구종들의 절대 위험도를 이 투수의 레퍼토리 안에서 0~1로 min-max 정규화한다.
        절대 위험도 값 자체가 후보 간에 별 차이가 없는 경우(예: 전부 0.05~0.15)에도, 그 안에서
        "상대적으로 가장 위험한 구종"이 뚜렷하게 드러나게 하기 위한 것이다."""
        if not danger_by_label:
            return {}
        lo, hi = min(danger_by_label.values()), max(danger_by_label.values())
        if hi - lo < 1e-9:
            return {label: 0.5 for label in danger_by_label}
        return {label: (v - lo) / (hi - lo) for label, v in danger_by_label.items()}

    def _score_pitcher_pitch_candidates(
        self, pitcher_id: int, batter_id: int | None, context: dict,
        full_proba: dict[str, float], interpretation: dict,
    ) -> tuple[dict[str, float], dict, dict]:
        """투수 모드 추천 점수. '다음에 던질 확률이 높은 공'이 아니라 '던졌을 때 아웃/약한
        타구를 유도할 가능성이 높은 공'을 고르기 위해 다음을 결합한다(가중치):
        모델 예측확률 15% + 카운트별 실제 구사 성향 20% + 투수 전체 구사 비율 10%(제구
        신뢰도) + 상대 타자 약점 30%(헛스윙 높고 장타 낮을수록 유리) - 구종별 평균 위험도
        25%(장타/하드히트 낮을수록 유리), 여기에 경기 상황 보정과 전략 코멘트 가중치를 곱한다.
        (이전 버전은 30/25/15/20/10 가중치라 모델확률·구사비율 비중이 너무 커 상대 타자/위험도
        변화가 최종 추천에 거의 반영되지 않았다 - 상대 약점·위험도 비중을 키워 선수/상황
        민감도를 높였다.) 이 투수가 실제로 던지는 구종(pitcher_pitch_profile 기준, 2025 표본
        부족 시 멀티시즌 프로필로 보완)으로만 후보를 제한한다. 두 번째 반환값은 fallback
        여부/사유, 세 번째는 구종별 점수 구성요소(model_score 등, Q&A/리포트 근거용)다."""
        pitcher_rows, pitcher_multi_used = self._pitcher_rows(pitcher_id)
        thrown = set(pitcher_rows["pitch_label"]) if not pitcher_rows.empty else set(full_proba)
        if not thrown:
            thrown = set(full_proba)
        usage = {r["pitch_label"]: float(r["pitch_ratio"]) for _, r in pitcher_rows.iterrows()}

        balls, strikes = context.get("balls", 0), context.get("strikes", 0)
        count_usage = self._count_pitch_ratios(pitcher_id, balls, strikes)

        fallback_reasons = []
        if pitcher_rows.empty:
            fallback_reasons.append("이 투수의 구종 구사 비율 데이터가 없어 모델 예측 확률에만 의존했습니다.")
        elif pitcher_multi_used:
            fallback_reasons.append("이 투수의 2025 표본이 부족해 2021~2025 가중 평균 프로필로 보완했습니다.")
        if not count_usage:
            fallback_reasons.append(f"{balls}B-{strikes}S 카운트의 구종 성향 표본이 부족해 투수 전체 구사 비율로 대체했습니다.")
        if batter_id is None:
            fallback_reasons.append("상대 타자 ID가 없어 타자 약점 데이터를 반영하지 못했습니다.")

        # danger를 먼저 전부 계산해 후보 구종 안에서의 "상대적" 위험도를 구한다 - 절대 danger
        # 값을 그대로 상황 보정에 쓰면 후보 간 차이가 작아(보통 0.05~0.2) 정규화(합=1) 후
        # 사실상 상쇄돼버려 상황을 바꿔도 추천이 안 바뀌는 문제가 있었다.
        danger_by_label = {label: self._pitch_overall_danger(pitcher_id, label) for label in thrown}
        relative_danger_by_label = self._relative_danger_map(danger_by_label)

        raw_scores: dict[str, float] = {}
        breakdown: dict[str, dict[str, float]] = {}
        for label in thrown:
            model_p = full_proba.get(label, 0.0)
            pitch_usage = usage.get(label, 0.05)
            count_p = count_usage.get(label, pitch_usage)
            effectiveness = self._batter_pitch_effectiveness_for_pitcher(batter_id, label)
            danger = danger_by_label[label]
            model_score = 0.15 * model_p
            count_tendency_score = 0.20 * count_p
            pitcher_mix_score = 0.10 * pitch_usage
            batter_weakness_score = 0.30 * effectiveness
            zone_safety_score = -0.25 * danger
            base = model_score + count_tendency_score + pitcher_mix_score + batter_weakness_score + zone_safety_score
            context_adjustment = self._context_adjustment_factor(label, relative_danger_by_label[label], context)
            comment_adjustment = self._comment_pitch_bias(label, interpretation)
            raw = max(base * context_adjustment * comment_adjustment, 0.0001)
            raw_scores[label] = raw
            breakdown[label] = {
                "model_score": round(model_score, 4),
                "pitcher_mix_score": round(pitcher_mix_score, 4),
                "count_tendency_score": round(count_tendency_score, 4),
                "batter_weakness_score": round(batter_weakness_score, 4),
                "zone_safety_score": round(zone_safety_score, 4),
                "context_adjustment": round(context_adjustment, 4),
                "comment_adjustment": round(comment_adjustment, 4),
            }

        total = sum(raw_scores.values())
        normalized = {k: v / total for k, v in raw_scores.items()} if total else {k: 1.0 / len(raw_scores) for k in raw_scores}
        for label, final_score in normalized.items():
            breakdown[label]["final_score"] = round(final_score, 4)
        return normalized, {"used": bool(fallback_reasons), "reason": " ".join(fallback_reasons)}, breakdown

    def _score_batter_expected_pitch(
        self, pitcher_id: int, context: dict, full_proba: dict[str, float], interpretation: dict,
    ) -> tuple[dict[str, float], dict, dict]:
        """타자 모드 예측 점수. 목적이 '상대 투수가 실제로 던질 가능성이 높은 구종을 맞히는 것'
        이므로, 모델 예측확률(35%)보다 카운트별 실제 구사 성향(40%)과 투수 전체 구사 비율
        (25%, 카운트 표본이 부족할 때의 대체값, 2025 표본 부족 시 멀티시즌으로 보완)에 더 큰
        비중을 둔다. 투수가 카운트/주자/점수차에 따라 실제로 구종을 바꾸는 경향은
        _context_adjustment_factor(투수 모드와 동일 로직 - 상대는 결국 투수이므로 행동 패턴은
        같다)로 반영해, 같은 투수라도 카운트/상황이 바뀌면 예상 구종이 달라지게 한다. 세 번째
        반환값은 구종별 점수 구성요소(투수 모드와 동일한 키 체계, 타자 모드 점수식에는 없는
        항목은 0으로 채워 Q&A/리포트에서 동일한 형태로 조회 가능하게 한다)."""
        pitcher_rows, pitcher_multi_used = self._pitcher_rows(pitcher_id)
        thrown = set(pitcher_rows["pitch_label"]) if not pitcher_rows.empty else set(full_proba)
        if not thrown:
            thrown = set(full_proba)
        usage = {r["pitch_label"]: float(r["pitch_ratio"]) for _, r in pitcher_rows.iterrows()}

        balls, strikes = context.get("balls", 0), context.get("strikes", 0)
        count_usage = self._count_pitch_ratios(pitcher_id, balls, strikes)

        fallback_reasons = []
        if pitcher_rows.empty:
            fallback_reasons.append("상대 투수의 구종 구사 비율 데이터가 없어 모델 예측 확률에만 의존했습니다.")
        elif pitcher_multi_used:
            fallback_reasons.append("상대 투수의 2025 표본이 부족해 2021~2025 가중 평균 프로필로 보완했습니다.")
        if not count_usage:
            fallback_reasons.append(f"{balls}B-{strikes}S 카운트의 구종 성향 표본이 부족해 투수 전체 구사 비율로 대체했습니다.")

        danger_by_label = {label: self._pitch_overall_danger(pitcher_id, label) for label in thrown}
        relative_danger_by_label = self._relative_danger_map(danger_by_label)

        raw_scores: dict[str, float] = {}
        breakdown: dict[str, dict[str, float]] = {}
        for label in thrown:
            model_p = full_proba.get(label, 0.0)
            pitch_usage = usage.get(label, 0.05)
            count_p = count_usage.get(label, pitch_usage)
            danger = danger_by_label[label]
            # 카운트별 실제 구사 성향 비중을 더 키워(40→50%), 같은 투수라도 카운트가 바뀌면
            # 예상 구종이 더 뚜렷하게 달라지게 한다("타자 모드 카운트별 패턴 반영 강화" 요구).
            model_score = 0.25 * model_p
            count_tendency_score = 0.50 * count_p
            pitcher_mix_score = 0.25 * pitch_usage
            base = model_score + count_tendency_score + pitcher_mix_score
            context_adjustment = self._context_adjustment_factor(label, relative_danger_by_label[label], context)
            raw_scores[label] = max(base * context_adjustment, 0.0001)
            breakdown[label] = {
                "model_score": round(model_score, 4),
                "pitcher_mix_score": round(pitcher_mix_score, 4),
                "count_tendency_score": round(count_tendency_score, 4),
                "batter_weakness_score": 0.0,  # 타자 모드 점수식에는 해당 없음(상대는 투수이므로)
                "zone_safety_score": round(-danger, 4),  # 참고용(재랭킹에는 미포함, context_adjustment에 danger가 이미 반영됨)
                "context_adjustment": round(context_adjustment, 4),
                "comment_adjustment": 1.0,
            }

        total = sum(raw_scores.values())
        normalized = {k: v / total for k, v in raw_scores.items()} if total else {k: 1.0 / len(raw_scores) for k in raw_scores}
        for label, final_score in normalized.items():
            breakdown[label]["final_score"] = round(final_score, 4)
        return normalized, {"used": bool(fallback_reasons), "reason": " ".join(fallback_reasons)}, breakdown

    def _build_zone_heatmap(self, pitcher_id: int, pitch_label: str, interpretation: dict) -> list[float]:
        """3x3 스트라이크존 히트맵용 9개 score(zone_cell 1~9 순, 합=1). 해당 투수+구종의
        zone_risk_profile pitch_count를 가중치로 사용하고, 데이터가 없으면 균등 분포로 대체."""
        rows = self.zone_risk_df[
            (self.zone_risk_df["pitcher"] == pitcher_id)
            & (self.zone_risk_df["pitch_label"] == pitch_label)
            & (self.zone_risk_df["zone_cell"] >= 1)
            & (self.zone_risk_df["zone_cell"] <= 9)
        ]
        if rows.empty:
            scores = [1.0 / 9] * 9
        else:
            counts = {int(r["zone_cell"]): float(r["pitch_count"]) for _, r in rows.iterrows()}
            total = sum(counts.values())
            scores = [counts.get(cell, 0.0) / total if total else 1.0 / 9 for cell in range(1, 10)]

        scores = self._apply_comment_bias(scores, interpretation)
        return [round(s, 4) for s in scores]

    def _apply_comment_bias(self, scores: list[float], interpretation: dict) -> list[float]:
        biased = list(scores)
        for cell in range(1, 10):
            idx = cell - 1
            row, col = ZONE_ROW_OF_CELL[cell], ZONE_COL_OF_CELL[cell]
            if interpretation["prefer_low"] and row == 0:
                biased[idx] *= 1.5
            if interpretation["prefer_high"] and row == 2:
                biased[idx] *= 1.5
            if interpretation["prefer_corner"] and col != 1:
                biased[idx] *= 1.4
            if interpretation["decrease_strike_risk"] and row == 1 and col == 1:
                biased[idx] *= 0.4
            if interpretation["increase_aggression"] and row == 1 and col == 1:
                biased[idx] *= 1.4
        total = sum(biased)
        return [v / total for v in biased] if total else [1.0 / 9] * 9

    def _build_coaching_message(self, recommended: str, avoid_pitch: str | None, interpretation: dict) -> str:
        recommended_kr = pitch_label_kr(recommended)
        parts = [f"다음 투구는 {recommended_kr}({recommended}) 위주로 승부하는 것을 추천합니다."]
        if avoid_pitch and avoid_pitch != recommended:
            avoid_kr = pitch_label_kr(avoid_pitch)
            parts.append(f"{avoid_kr}({avoid_pitch})는 이 카운트에서 상대적으로 예측 확률이 낮아 피하는 것이 좋습니다.")
        if interpretation["summary"] != "특별한 코스/전략 선호가 감지되지 않음":
            parts.append(f"코멘트 반영: {interpretation['summary']}.")
        return " ".join(parts)

    def _build_batter_weakness_summary(self, batter_id: int | None, p_throws: str) -> dict:
        """batter_matchup_profile(타자별 구종 대응 성적)에서 헛스윙률이 가장 높은 구종을
        약점으로, 장타율이 가장 높은 구종을 강점으로 요약한다."""
        if batter_id is None:
            return {
                "summary": "상대 타자 ID가 입력되지 않아 약점 데이터를 조회할 수 없습니다.",
                "weak_pitch": None, "strong_pitch": None,
            }

        batter_rows, multi_year_used = self._batter_matchup_rows(batter_id)
        rows = batter_rows[batter_rows["p_throws"] == p_throws]
        if rows.empty:
            rows = batter_rows
        if not rows.empty and (rows["pitch_count"] >= 5).any():
            rows = rows[rows["pitch_count"] >= 5]
        if rows.empty:
            return {
                "summary": f"{get_batter_display(batter_id)}의 구종별 대응 데이터가 부족합니다.",
                "weak_pitch": None, "strong_pitch": None, "multi_year_used": multi_year_used,
            }

        weakest = rows.sort_values("whiff_rate", ascending=False).iloc[0]
        strongest = rows.sort_values("extra_base_hit_rate", ascending=False).iloc[0]
        summary = (
            f"{pitch_label_kr(weakest['pitch_label'])}({weakest['pitch_label']})에 헛스윙률 "
            f"{weakest['whiff_rate']:.1%}로 약점을 보이고, "
            f"{pitch_label_kr(strongest['pitch_label'])}({strongest['pitch_label']})에는 장타율 "
            f"{strongest['extra_base_hit_rate']:.1%}로 강한 편입니다."
        )
        if multi_year_used:
            summary += " (2025 표본이 부족해 2021~2025 가중 평균으로 보완한 값입니다.)"
        return {
            "summary": summary, "weak_pitch": weakest["pitch_label"], "strong_pitch": strongest["pitch_label"],
            "multi_year_used": multi_year_used,
        }

    def _build_zone_hit_risk_display(
        self, pitcher_id: int, pitch_label: str, batter_id: int | None, context: dict, interpretation: dict,
    ) -> dict[int, float]:
        """STRIKE ZONE BOARD에 표시할 "피안타 위험" 값(zone_cell 0~9, 0~1). 원본 데이터에는
        타구 결과가 안타/장타로 세분화된 hit_rate 컬럼이 없어, 사용자가 지정한 우선순위대로
        risky_contact_rate(있으면)를 쓰고 없으면 기존 (extra_base_hit_rate+hard_hit_rate)/2
        조합으로 대체한다.

        이전 버전은 이 값에 상황/상대 타자 보정을 전혀 적용하지 않아, best_zone_cell(별표)은
        카운트/주자/점수차에 따라 움직여도 화면에 찍히는 실제 % 숫자는 항상 고정돼 있었다 -
        "히트맵 값이 안 바뀐다"는 체감의 핵심 원인이었다. 이제 _build_zone_danger_scores(추천
        로직)와 동일한 근거(상대 타자 장타 성향, 경기 상황, 전략 코멘트) 곱셈 보정을 그대로
        재사용해, 표시되는 숫자 자체가 상황/선수에 따라 실제로 달라지게 한다(숫자를 새로
        지어내지 않고 기존 위험도 기반 보정 로직을 표시값에도 동일하게 적용하는 것)."""
        rows, _ = self._zone_risk_rows(pitcher_id, pitch_label)
        default = self._pitch_overall_danger(pitcher_id, pitch_label)
        base_scores: dict[int, float] = {}
        for cell in range(0, 10):
            row = rows[rows["zone_cell"] == cell] if not rows.empty else rows
            if row.empty:
                base_scores[cell] = default
            else:
                r = row.iloc[0]
                if "risky_contact_rate" in r.index and pd.notna(r["risky_contact_rate"]):
                    base_scores[cell] = float(r["risky_contact_rate"])
                else:
                    base_scores[cell] = float((r["extra_base_hit_rate"] + r["hard_hit_rate"]) / 2)

        batter_factor = self._batter_pitch_risk_factor(batter_id, pitch_label)
        situational = self._situational_danger_multipliers(context)
        comment = self._comment_danger_multipliers(interpretation)

        scores: dict[int, float] = {}
        for cell in range(0, 10):
            value = base_scores[cell]
            if cell != 0:
                value *= batter_factor
            value *= situational[cell] * comment[cell]
            scores[cell] = round(min(value, 1.0), 4)
        return scores

    def get_zone_cell_estimate(self, pitcher_id: int, pitch_label: str) -> int:
        """이 투수+구종이 실제로 가장 많이 던진 zone_cell(1~9). STRIKE ZONE BOARD의 구종별
        궤적(Top-2/3 포함) 목적지를 계산하는 공개 헬퍼."""
        return self._estimate_location(pitcher_id, pitch_label)["zone_cell"]

    def _build_zone_danger_scores(
        self, pitcher_id: int, pitch_label: str, batter_id: int | None, context: dict, interpretation: dict,
    ) -> dict[int, float]:
        """HOT & COLD ZONE(투수용) 점수: zone_cell 0~9별 (장타율+하드히트율)/2를 기본 '위험 점수'로
        삼고, ① 상대 타자의 이 구종 상대 성적(강/약점), ② 경기 상황(볼/스트라이크/주자/점수차/아웃),
        ③ 전략 코멘트 순으로 곱셈 가중치를 적용한다. 낮을수록 안전(추천)."""
        rows, _ = self._zone_risk_rows(pitcher_id, pitch_label)
        default = self._pitch_overall_danger(pitcher_id, pitch_label)

        base_scores: dict[int, float] = {}
        for cell in range(0, 10):
            row = rows[rows["zone_cell"] == cell]
            if row.empty:
                base_scores[cell] = default
            else:
                r = row.iloc[0]
                base_scores[cell] = float((r["extra_base_hit_rate"] + r["hard_hit_rate"]) / 2)

        batter_factor = self._batter_pitch_risk_factor(batter_id, pitch_label)
        situational = self._situational_danger_multipliers(context)
        comment = self._comment_danger_multipliers(interpretation)

        scores: dict[int, float] = {}
        for cell in range(0, 10):
            value = base_scores[cell]
            if cell != 0:
                # 존 밖(0)은 컨택 자체가 안 나는 영역이라 타자의 파워(장타력)와는 무관하다.
                value *= batter_factor
            value *= situational[cell] * comment[cell]
            scores[cell] = round(value, 4)
        return scores

    def _batter_pitch_risk_factor(self, batter_id: int | None, pitch_label: str) -> float:
        """상대 타자가 이 구종에 특히 강한지(장타율 높음)를 0.6~1.8배 위험 배수로 변환한다.
        MLB 평균 장타율을 대략 6%로 보고, 그보다 높으면 위험을 올리고 낮으면 내린다.
        (기존 0.7~1.5배*0.5 계수는 배터를 바꿔도 화면상 체감이 작다는 피드백을 받아 폭을
        넓혔다 - "상대 타자가 특정 구종에 강하면 그 구종은 실제로 더 내려가야 한다"는 요구에
        맞춰, 강점 구종일수록 이 배수가 zone_hit_risk_scores/zone_danger_scores 양쪽에서
        확실히 위험도를 끌어올려 재랭킹 점수에서도 더 크게 내려가게 한다.)"""
        if batter_id is None:
            return 1.0
        batter_rows, _ = self._batter_matchup_rows(batter_id)
        rows = batter_rows[batter_rows["pitch_label"] == pitch_label]
        if rows.empty or rows["pitch_count"].sum() < 5:
            return 1.0
        total = rows["pitch_count"].sum()
        xbh_rate = float((rows["extra_base_hit_rate"] * rows["pitch_count"]).sum() / total)
        baseline = 0.06
        factor = 1.0 + (xbh_rate - baseline) / baseline * 0.7
        return max(0.6, min(1.8, factor))

    def _situational_danger_multipliers(self, context: dict) -> dict[int, float]:
        """경기 상황이 존별 위험 가중치에 미치는 영향(곱셈 계수, 1.0=중립).
        zone_cell 0(존 밖)과 1~9(존 안)에 서로 다른 논리를 적용한다.

        1차 버전은 배수가 작아(무주자든 득점권이든 같은 1.15배) 화면 숫자/추천 존 변화가
        잘 안 느껴진다는 피드백을 받아, ① 무주자와 득점권(2·3루)을 확실히 다른 배수로
        분리하고 ② 전 항목의 배수 폭을 넓혔다."""
        mult = {cell: 1.0 for cell in range(0, 10)}

        if context.get("balls", 0) >= 3:
            # 3볼: 여기서 더 빼면 볼넷이므로 존 밖의 '위험'을 올려 확실히 존 안쪽이 추천되게 한다.
            mult[0] *= 1.8

        if context.get("strikes", 0) >= 2:
            # 2스트라이크: 굳이 존 안에 넣지 않아도 되므로 유인구(존 밖/모서리)의 위험을 크게 낮춘다.
            mult[0] *= 0.6
            for cell in (1, 3, 7, 9):
                mult[cell] *= 0.75
            mult[5] *= 0.85

        on_2b, on_3b, on_1b = (
            bool(context.get("on_2b")), bool(context.get("on_3b")), bool(context.get("on_1b")),
        )
        if on_2b or on_3b:
            # 득점권: 장타 한 방이 곧바로 실점으로 이어지므로 존 안쪽 전체를 크게 감점한다.
            for cell in range(1, 10):
                mult[cell] *= 1.45
        elif on_1b:
            for cell in range(1, 10):
                mult[cell] *= 1.15

        score_diff = context.get("score_diff", 0)
        if abs(score_diff) <= 1:
            # 박빙 승부에서는 같은 위험이라도 더 보수적으로(위험하게) 평가한다.
            for cell in range(1, 10):
                mult[cell] *= 1.25
        elif score_diff <= -4:
            # 크게 뒤지는 상황도 장타 한 방을 더 내주면 안 되니 위험을 더 높게 평가한다.
            for cell in range(1, 10):
                mult[cell] *= 1.15
        elif score_diff >= 4:
            # 크게 앞서는 상황은 위험 감수 여유가 있어 위험 평가를 완화한다.
            for cell in range(1, 10):
                mult[cell] *= 0.8

        outs = context.get("outs_when_up", 1)
        if outs == 0:
            # 무사는 실점으로 이어질 여지가 커 신중하게, 2아웃은 상대적으로 공격적으로 평가한다.
            for cell in range(1, 10):
                mult[cell] *= 1.15
        elif outs == 2:
            for cell in range(1, 10):
                mult[cell] *= 0.85

        return mult

    def _comment_danger_multipliers(self, interpretation: dict) -> dict[int, float]:
        """전략 코멘트가 danger score에 미치는 영향(곱셈 계수). 확률 분포용 _apply_comment_bias와
        달리 이 값은 '위험도'이므로 반대 방향으로 적용된다 (그 존을 선호한다 = 위험을 낮춰 추천되게 함)."""
        mult = {cell: 1.0 for cell in range(0, 10)}
        if interpretation["decrease_strike_risk"]:  # "빼고 싶다" 계열 코멘트
            mult[5] *= 1.4
            for cell in (0, 1, 3, 7, 9):
                mult[cell] *= 0.7
        if interpretation["increase_aggression"]:  # "존 안으로 승부" 계열 코멘트
            mult[5] *= 0.7
            mult[0] *= 1.3
        if interpretation["prefer_low"]:
            for cell in (1, 2, 3):
                mult[cell] *= 0.8
        if interpretation["prefer_high"]:
            for cell in (7, 8, 9):
                mult[cell] *= 0.8
        if interpretation["prefer_corner"]:
            for cell in (1, 3, 7, 9):
                mult[cell] *= 0.8
        return mult

    # ---- 타자 모드 ---------------------------------------------------------

    def _build_batter_mode_result(self, request: ScoutingRequest, top3: list[tuple[str, float]], interpretation: dict) -> dict:
        target_zone = self._describe_target_zone(interpretation)
        counter_strategy = self._build_counter_strategy(top3, interpretation)
        expected_locations = [
            {"pitch_label": label, "probability": prob, **self._estimate_location(request.pitcher_id, label)}
            for label, prob in top3
        ]
        pitcher_pattern = self._build_pitcher_pattern_summary(request.pitcher_id)

        zone_probability_scores = self._build_batter_zone_probabilities(
            request.pitcher_id, top3, request.context, interpretation
        )
        target_zone_cell = max(range(1, 10), key=lambda c: zone_probability_scores[c])

        return {
            "expected_top3_pitches": [{"pitch_label": label, "probability": prob} for label, prob in top3],
            "target_zone": target_zone,
            "counter_strategy": counter_strategy,
            "expected_locations": expected_locations,
            "pitcher_pattern": pitcher_pattern,
            "zone_probability_scores": zone_probability_scores,  # zone_cell 0~9의 투구 확률 (합=1)
            "target_zone_cell": target_zone_cell,
        }

    def _describe_target_zone(self, interpretation: dict) -> str:
        if interpretation["decrease_strike_risk"]:
            return "존 바깥으로 빠지는 공이 예상되니 무리하게 노리지 말고 존 안쪽 공만 선별"
        if interpretation["prefer_high"]:
            return "높은 코스"
        if interpretation["prefer_low"]:
            return "낮은 코스"
        if interpretation["prefer_corner"]:
            return "존 모서리 코스"
        return "존 가운데~중간대 코스"

    def _build_counter_strategy(self, top3: list[tuple[str, float]], interpretation: dict) -> str:
        top_label, top_prob = top3[0]
        top_label_kr = pitch_label_kr(top_label)
        strategy = f"{top_label_kr}({top_label}) 구종이 올 확률이 {top_prob:.0%}로 가장 높으니 초구부터 노려볼 만합니다."
        if interpretation["decrease_strike_risk"]:
            strategy += " 상대가 스트라이크를 피해 빠지는 공을 던질 가능성이 있으니 유인구에 배트가 나가지 않도록 주의하세요."
        if interpretation["increase_aggression"]:
            strategy += " 상대가 존 안쪽 승부를 걸어올 가능성이 높으니 초구부터 적극적으로 스윙하는 것도 방법입니다."
        return strategy

    def _build_pitcher_pattern_summary(self, pitcher_id: int) -> dict:
        """pitcher_pitch_profile 기준 상대 투수의 구종 구사 비중 상위 3개를 요약한다."""
        rows = self.pitcher_profile_df[self.pitcher_profile_df["pitcher"] == pitcher_id].sort_values(
            "pitch_ratio", ascending=False
        )
        if rows.empty:
            return {"summary": "상대 투수 데이터가 부족합니다.", "top_pitches": []}
        top = rows.head(3)
        parts = [f"{pitch_label_kr(r['pitch_label'])}({r['pitch_label']}) {r['pitch_ratio']:.0%}" for _, r in top.iterrows()]
        summary = f"이 투수는 {', '.join(parts)} 순으로 구종을 구사합니다."
        return {
            "summary": summary,
            "top_pitches": [
                {"pitch_label": r["pitch_label"], "ratio": round(float(r["pitch_ratio"]), 4)} for _, r in top.iterrows()
            ],
        }

    def _build_zone_distribution_full(self, pitcher_id: int, pitch_label: str) -> dict[int, float]:
        """zone_cell 0~9(0=존 밖) 전체에 대한 해당 투수+구종의 pitch_count 가중 분포(합=1).
        HOT & COLD ZONE(타자용) 확률 계산에 사용한다."""
        rows = self.zone_risk_df[
            (self.zone_risk_df["pitcher"] == pitcher_id) & (self.zone_risk_df["pitch_label"] == pitch_label)
        ]
        if rows.empty:
            return {cell: 1.0 / 10 for cell in range(0, 10)}
        counts = {
            int(r["zone_cell"]): float(r["pitch_count"])
            for _, r in rows.iterrows() if 0 <= r["zone_cell"] <= 9
        }
        total = sum(counts.values())
        return {cell: (counts.get(cell, 0.0) / total if total else 1.0 / 10) for cell in range(0, 10)}

    def _build_batter_zone_probabilities(
        self, pitcher_id: int, top3: list[tuple[str, float]], context: dict, interpretation: dict,
    ) -> dict[int, float]:
        """top3 구종 각각의 zone 분포를 예측 확률로 가중 합산한 뒤, 현재 카운트와 전략 코멘트를
        반영해 다음 투구가 각 zone_cell로 들어올 전체 확률(합=1)을 추정한다."""
        combined = {cell: 0.0 for cell in range(0, 10)}
        for label, prob in top3:
            dist = self._build_zone_distribution_full(pitcher_id, label)
            for cell in range(0, 10):
                combined[cell] += prob * dist[cell]

        count_mult = self._count_zone_probability_multipliers(context)
        comment_mult = self._comment_probability_multipliers(interpretation)
        for cell in range(0, 10):
            combined[cell] *= count_mult[cell] * comment_mult[cell]

        total = sum(combined.values())
        return {cell: round(v / total if total else 1.0 / 10, 4) for cell, v in combined.items()}

    def _count_zone_probability_multipliers(self, context: dict) -> dict[int, float]:
        """현재 카운트/주자/점수차가 투수의 다음 투구 위치 확률에 미치는 영향(곱셈 계수).
        3볼이면 투수가 스트라이크를 던져야 하는 압박이 커 존 안 확률이 오르고, 2스트라이크면
        유인구(존 밖/모서리)를 던질 여유가 생겨 그 확률이 오른다. (기존에는 카운트만 반영해
        타자 모드 히트맵이 주자/점수차를 바꿔도 안 변한다는 피드백이 있었다 - 득점권/박빙
        상황에서는 투수가 가운데로 몰아넣을 확률이 낮아진다는 논리를 추가로 반영한다.)"""
        mult = {cell: 1.0 for cell in range(0, 10)}
        if context.get("balls", 0) >= 3:
            mult[0] *= 0.35
        if context.get("strikes", 0) >= 2:
            mult[0] *= 1.7
            for cell in (1, 3, 7, 9):
                mult[cell] *= 1.35
            mult[5] *= 0.8

        if context.get("on_2b") or context.get("on_3b"):
            mult[5] *= 0.6
            for cell in (1, 3, 7, 9):
                mult[cell] *= 1.25

        if abs(context.get("score_diff", 0)) <= 1:
            mult[5] *= 0.75

        return mult

    def _comment_probability_multipliers(self, interpretation: dict) -> dict[int, float]:
        """전략 코멘트(투수의 예상 행동에 대한 해석)가 존별 투구 확률에 미치는 영향(곱셈 계수).
        _build_zone_heatmap에서 쓰는 확률 편향과 같은 방향이다(그 존을 선호할수록 확률이 오름)."""
        mult = {cell: 1.0 for cell in range(0, 10)}
        if interpretation["decrease_strike_risk"]:
            mult[0] *= 1.3
            for cell in (1, 3, 7, 9):
                mult[cell] *= 1.2
            mult[5] *= 0.7
        if interpretation["increase_aggression"]:
            mult[5] *= 1.3
            mult[0] *= 0.7
        if interpretation["prefer_low"]:
            for cell in (1, 2, 3):
                mult[cell] *= 1.2
        if interpretation["prefer_high"]:
            for cell in (7, 8, 9):
                mult[cell] *= 1.2
        if interpretation["prefer_corner"]:
            for cell in (1, 3, 7, 9):
                mult[cell] *= 1.2
        return mult

    def _estimate_location(self, pitcher_id: int, pitch_label: str) -> dict:
        """해당 투수+구종의 zone_risk_profile pitch_count 가중 평균 위치를 타자 시점
        시각화용 좌표(plate_x_estimate, zone_height_fraction_estimate)로 추정한다."""
        rows = self.zone_risk_df[
            (self.zone_risk_df["pitcher"] == pitcher_id)
            & (self.zone_risk_df["pitch_label"] == pitch_label)
            & (self.zone_risk_df["zone_cell"] >= 1)
            & (self.zone_risk_df["zone_cell"] <= 9)
        ]
        if rows.empty:
            return {"plate_x_estimate": 0.0, "zone_height_fraction_estimate": 0.5, "zone_cell": 5}

        weights = rows["pitch_count"].to_numpy(dtype="float64")
        cells = rows["zone_cell"].to_numpy(dtype="int64")
        total = weights.sum()
        x = sum(w * ZONE_CELL_X_CENTER[int(c)] for w, c in zip(weights, cells)) / total
        z = sum(w * ZONE_CELL_Z_FRACTION[int(c)] for w, c in zip(weights, cells)) / total
        dominant_cell = int(cells[weights.argmax()])
        return {
            "plate_x_estimate": round(float(x), 3),
            "zone_height_fraction_estimate": round(float(z), 3),
            "zone_cell": dominant_cell,
        }
