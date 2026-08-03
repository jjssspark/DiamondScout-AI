"""
DiamondScout AI - 타석 시뮬레이션
공 하나씩 입력하면서 볼카운트/최근 5구/ScoutingService 분석 결과를 갱신하는 상태 기계.
기존 ScoutingService/PredictionService는 그대로 재사용하고 이 파일은 수정하지 않는다.
"""

import json
import os

from services.scouting_service import ScoutingRequest, ScoutingService

RECENT_PITCH_WINDOW = 5

RESULT_BALL = "ball"
RESULT_CALLED_STRIKE = "called_strike"
RESULT_SWINGING_STRIKE = "swinging_strike"
RESULT_FOUL = "foul"
RESULT_IN_PLAY = "in_play"
VALID_RESULTS = {RESULT_BALL, RESULT_CALLED_STRIKE, RESULT_SWINGING_STRIKE, RESULT_FOUL, RESULT_IN_PLAY}

OUTCOME_WALK = "walk"
OUTCOME_STRIKEOUT = "strikeout"
OUTCOME_IN_PLAY = "in_play"


def _load_label_mapping(root_dir: str) -> tuple[dict[str, int], dict[int, str]]:
    path = os.path.join(root_dir, "data", "processed", "pitch_label_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    label_to_id = mapping["label_to_id"]
    id_to_label = {int(k): v for k, v in mapping["id_to_label"].items()}
    return label_to_id, id_to_label


class AtBatSimulator:
    """투구 단위로 볼카운트/최근 5구를 갱신하고, 매 투구 후 ScoutingService.analyze()를
    재실행하는 타석 시뮬레이터. 최근 5구 히스토리는 실제 학습 데이터(next_pitch_dataset)와
    동일하게 타석이 아닌 투수의 이번 등판 전체 기준으로 이어진다(reset_at_bat으로 카운트만
    초기화되고 최근 5구/주자/아웃/이닝은 유지됨)."""

    def __init__(
        self,
        pitcher_id: int,
        context: dict,
        initial_recent_pitches: list[dict],
        scouting_service: ScoutingService | None = None,
        root_dir: str | None = None,
    ):
        """context: outs_when_up, inning, inning_topbot_enc, on_1b, on_2b, on_3b,
        score_diff, stand_enc, p_throws_enc (balls/strikes는 시뮬레이터가 직접 관리하므로
        전달돼도 0으로 덮어쓴다). initial_recent_pitches는 과거->최근 순 정확히 5개."""
        if len(initial_recent_pitches) != RECENT_PITCH_WINDOW:
            raise ValueError(
                f"initial_recent_pitches는 정확히 {RECENT_PITCH_WINDOW}개(과거->최근 순)여야 합니다. "
                f"받은 개수: {len(initial_recent_pitches)}"
            )

        self.root_dir = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.label_to_id, self.id_to_label = _load_label_mapping(self.root_dir)
        self.scouting_service = scouting_service or ScoutingService(root_dir=self.root_dir)

        self.pitcher_id = pitcher_id
        self.context = dict(context)
        self.context["balls"] = 0
        self.context["strikes"] = 0

        self.pitch_window: list[dict] = [self._normalize_pitch(p) for p in initial_recent_pitches]
        self.at_bat_over = False
        self.at_bat_outcome: str | None = None

    @property
    def balls(self) -> int:
        return self.context["balls"]

    @property
    def strikes(self) -> int:
        return self.context["strikes"]

    def _normalize_pitch(self, pitch: dict) -> dict:
        """pitch_label_id/pitch_label 중 하나만 있어도 서로 채워 넣고, pfx_x/pfx_z가 없으면
        0.0(중립 무브먼트)으로 기본값을 채운다."""
        pitch = dict(pitch)
        if "pitch_label_id" not in pitch and "pitch_label" in pitch:
            pitch["pitch_label_id"] = self.label_to_id[str(pitch["pitch_label"]).strip().upper()]
        if "pitch_label" not in pitch and "pitch_label_id" in pitch:
            pitch["pitch_label"] = self.id_to_label[int(pitch["pitch_label_id"])]
        pitch.setdefault("pfx_x", 0.0)
        pitch.setdefault("pfx_z", 0.0)
        return pitch

    def record_pitch(
        self,
        pitch_label: str,
        release_speed: float,
        plate_x: float,
        plate_z: float,
        zone_cell: int,
        result: str,
        user_comment: str = "",
        mode: str = "pitcher",
    ) -> dict:
        """투구 결과를 기록해 최근 5구 창을 갱신하고 카운트를 반영한 뒤
        ScoutingService.analyze()를 재실행한다."""
        if self.at_bat_over:
            raise ValueError("이미 종료된 타석입니다. reset_at_bat()으로 새 타석을 시작하세요.")

        label = pitch_label.strip().upper()
        if label not in self.label_to_id:
            raise ValueError(f"알 수 없는 구종: {pitch_label} (가능한 값: {', '.join(self.label_to_id)})")
        if result not in VALID_RESULTS:
            raise ValueError(f"알 수 없는 결과: {result} (가능한 값: {', '.join(sorted(VALID_RESULTS))})")

        pitch_record = {
            "pitch_label_id": self.label_to_id[label],
            "pitch_label": label,
            "release_speed": float(release_speed),
            # 시뮬레이션 입력 항목에 무브먼트(pfx_x/pfx_z)가 없어 중립값으로 고정한다.
            "pfx_x": 0.0,
            "pfx_z": 0.0,
            "plate_x": float(plate_x),
            "plate_z": float(plate_z),
            "zone_cell": int(zone_cell),
            "balls": self.balls,  # 이 투구가 던져지기 직전(투구 시점)의 카운트
            "strikes": self.strikes,
            "result": result,
        }
        self.pitch_window = [*self.pitch_window[1:], pitch_record]

        self._apply_count(result)

        request = ScoutingRequest(
            mode=mode,
            pitcher_id=self.pitcher_id,
            context=dict(self.context),
            recent_pitches=list(self.pitch_window),
            user_comment=user_comment,
        )
        analysis = self.scouting_service.analyze(request)

        return {
            "pitch_record": pitch_record,
            "count": {"balls": self.balls, "strikes": self.strikes, "outs_when_up": self.context["outs_when_up"]},
            "at_bat_over": self.at_bat_over,
            "at_bat_outcome": self.at_bat_outcome,
            "analysis": analysis,
        }

    def _apply_count(self, result: str) -> None:
        if result == RESULT_IN_PLAY:
            self.at_bat_over = True
            self.at_bat_outcome = OUTCOME_IN_PLAY
            return

        if result == RESULT_BALL:
            self.context["balls"] += 1
            if self.context["balls"] >= 4:
                self.at_bat_over = True
                self.at_bat_outcome = OUTCOME_WALK
            return

        if result in (RESULT_CALLED_STRIKE, RESULT_SWINGING_STRIKE):
            self.context["strikes"] += 1
        elif result == RESULT_FOUL and self.context["strikes"] < 2:
            # 2스트라이크 이후의 파울은 스트라이크로 카운트되지 않는다 (야구 규칙).
            self.context["strikes"] += 1

        if self.context["strikes"] >= 3:
            self.at_bat_over = True
            self.at_bat_outcome = OUTCOME_STRIKEOUT

    def reset_at_bat(self) -> None:
        """카운트만 초기화해 새 타석을 시작한다. 주자/아웃/이닝/최근 5구 히스토리는 유지한다."""
        self.context["balls"] = 0
        self.context["strikes"] = 0
        self.at_bat_over = False
        self.at_bat_outcome = None
