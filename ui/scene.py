"""캔버스 스트라이크 존 씬의 Python 쪽 — 좌표 변환과 페이로드 조립.

실제 렌더링은 ui/static/scene.js가 한다. 이 모듈은 앱의 존 좌표(cell 1~9)를
씬 엔진의 좌표(idx 0~8)로 옮기고 엔진이 먹을 JSON을 만든다.

변환을 JS 안에 두지 않고 여기로 뺀 이유는 테스트 때문이다. 좌표가 뒤집혀도
앱은 정상 기동하고 화면도 그려져서, 야구를 아는 사람이 화면을 뜯어보기 전까지
아무도 모른다(TROUBLESHOOTING.md TS-007과 같은 실패 모양).
"""

SCENE_CELL_COUNT = 9

# 씬 엔진의 칸 이름 (ui/static/scene.js와 같은 순서). 라벨 자체는 엔진이 그리지만,
# 여기 두면 변환이 맞는지 사람이 눈으로 대조할 수 있다.
SCENE_CELL_NAME = (
    "높은 바깥쪽", "높은 한가운데", "높은 몸쪽",
    "가운데 바깥쪽", "한가운데", "가운데 몸쪽",
    "낮은 바깥쪽", "낮은 한가운데", "낮은 몸쪽",
)


def to_scene_index(cell: int, stand: str) -> int:
    """앱의 존 칸(1~9)을 씬 엔진의 칸(0~8)으로 옮긴다.

    두 좌표계는 행·열이 둘 다 다르다.
      앱   : row 0 = 하단(낮은 코스), col = 투수 시점 화면 좌→우
      엔진 : row 0 = 상단(높은 코스), col 0 = 바깥쪽 / col 2 = 몸쪽 (타자 기준)

    따라서 행은 항상 반전이고, 열은 우타일 때만 반전이다. 열 규칙의 근거는
    ui/zone_heatmap.py의 _zone_hand_label — 우타는 화면 왼쪽(col 0)이 몸쪽,
    좌타는 바깥쪽이다.
    """
    row, col = (cell - 1) // 3, (cell - 1) % 3
    scene_row = 2 - row
    scene_col = col if stand == "L" else 2 - col
    return scene_row * 3 + scene_col


def build_scene_payload(
    mode: str,
    stand: str,
    zone_scores: dict[int, float],
    highlight_cell: int,
    metric: str,
    trajectories: list[dict] | None = None,
) -> dict:
    """씬 엔진이 그대로 먹을 수 있는 JSON 직렬화 가능한 dict를 만든다.

    zone_scores의 키 0은 존 밖 점수라 9칸에 섞지 않고 따로 넘긴다.
    궤적 목적지도 칸과 같은 변환을 태워야 공이 엉뚱한 자리로 날아가지 않는다.
    """
    cells = [0.0] * SCENE_CELL_COUNT
    for cell in range(1, SCENE_CELL_COUNT + 1):
        cells[to_scene_index(cell, stand)] = zone_scores.get(cell, 0.0)

    mapped_trajectories = [
        {
            "idx": to_scene_index(traj["cell"], stand),
            "label": traj.get("pitch_label", ""),
            "rank": traj.get("rank", 3),
        }
        for traj in (trajectories or [])
        # 모델이 존 밖(0)이나 결측을 낼 수 있다. 엔진은 0~8만 안다.
        if traj.get("cell") in range(1, SCENE_CELL_COUNT + 1)
    ]

    return {
        "mode": mode,
        "bats": stand,
        "cells": cells,
        "target": to_scene_index(highlight_cell, stand),
        "outZone": zone_scores.get(0, 0.0),
        "metric": metric,
        "trajectories": mapped_trajectories,
    }
