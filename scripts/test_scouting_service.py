"""
DiamondScout AI - ScoutingService 수동 테스트 스크립트
투수 모드 / 타자 모드 예시 입력을 넣고 분석 결과를 print한다.
예시 값은 data/processed/next_pitch_dataset_2025.csv의 실제 투수(Rodón, Carlos, pitcher=607074)
샘플 행을 기반으로 구성했다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.scouting_service import ScoutingRequest, ScoutingService

# 현재 상황 (2사, 1회 초, 주자 없음, 동점, 우타 타자 vs 우투수)
SAMPLE_CONTEXT = {
    "balls": 0,
    "strikes": 0,
    "outs_when_up": 2,
    "inning": 1,
    "inning_topbot_enc": 1,
    "on_1b": 0,
    "on_2b": 0,
    "on_3b": 0,
    "score_diff": 0,
    "stand_enc": 0,
    "p_throws_enc": 0,
}

# 과거 -> 최근 순 정확히 5구 (recent_pitches[-1]이 바로 직전 투구 = lag1)
SAMPLE_RECENT_PITCHES = [
    {"pitch_label_id": 0, "release_speed": 92.8, "pfx_x": 0.98, "pfx_z": 1.44, "plate_x": 0.014, "plate_z": 2.107, "zone_cell": 5, "balls": 0, "strikes": 0},
    {"pitch_label_id": 0, "release_speed": 92.4, "pfx_x": 0.82, "pfx_z": 1.35, "plate_x": 1.181, "plate_z": 2.444, "zone_cell": 0, "balls": 0, "strikes": 0},
    {"pitch_label_id": 0, "release_speed": 92.3, "pfx_x": 1.06, "pfx_z": 1.49, "plate_x": 0.495, "plate_z": 2.598, "zone_cell": 6, "balls": 1, "strikes": 0},
    {"pitch_label_id": 0, "release_speed": 91.5, "pfx_x": 0.99, "pfx_z": 1.35, "plate_x": -0.634, "plate_z": 3.376, "zone_cell": 7, "balls": 1, "strikes": 1},
    {"pitch_label_id": 0, "release_speed": 93.1, "pfx_x": 0.84, "pfx_z": 1.41, "plate_x": -0.941, "plate_z": 1.978, "zone_cell": 0, "balls": 1, "strikes": 2},
]

PITCHER_ID = 607074  # Rodón, Carlos


def print_result(title: str, result: dict) -> None:
    print(f"\n===== {title} =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    service = ScoutingService()

    pitcher_request = ScoutingRequest(
        mode="pitcher",
        pitcher_id=PITCHER_ID,
        context=SAMPLE_CONTEXT,
        recent_pitches=SAMPLE_RECENT_PITCHES,
        user_comment="이번엔 고의4구 느낌으로 존 바깥으로 빼고 싶어",
    )
    print_result("투수 모드 결과", service.analyze(pitcher_request))

    batter_request = ScoutingRequest(
        mode="batter",
        pitcher_id=PITCHER_ID,
        context=SAMPLE_CONTEXT,
        recent_pitches=SAMPLE_RECENT_PITCHES,
        user_comment="적극적으로 존 안으로 승부해올 것 같다",
    )
    print_result("타자 모드 결과", service.analyze(batter_request))


if __name__ == "__main__":
    main()
