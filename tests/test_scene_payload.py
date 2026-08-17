import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.scene import build_scene_payload, to_scene_index

# 앱과 목업의 존 좌표 규약이 행·열 둘 다 다르다. 이 테스트가 그 변환을 고정한다.
#
#   앱(services/scouting_service.py):  cell 1~9, row=(cell-1)//3, col=(cell-1)%3
#     - row 0 = 하단(낮은 코스)          ui/zone_heatmap.py:78의 (2-row) 반전이 근거
#     - col   = 투수 시점 화면 좌→우
#   목업(dugout-console.html:2034):    idx 0~8, row=idx//3, col=idx%3
#     - row 0 = 상단(높은 코스)
#     - col 0 = 바깥쪽 / col 2 = 몸쪽   (타자 기준. 화면 위치는 insideSign()이 뒤집는다)
#
# 즉 행은 항상 반전, 열은 우타일 때만 반전이다.
# 열 규칙의 근거는 ui/zone_heatmap.py:222-230의 _zone_hand_label —
# 우타는 col 0이 몸쪽, 좌타는 col 0이 바깥쪽.

# 목업의 CELL_NAME(dugout-console.html:1508)과 같은 순서
SCENE_CELL_NAME = [
    "높은 바깥쪽", "높은 한가운데", "높은 몸쪽",
    "가운데 바깥쪽", "한가운데", "가운데 몸쪽",
    "낮은 바깥쪽", "낮은 한가운데", "낮은 몸쪽",
]


def test_bottom_outer_cell_maps_to_low_outside_for_lefty():
    """cell 1은 앱 기준 하단·화면 왼쪽. 좌타는 화면 왼쪽이 바깥쪽이므로 '낮은 바깥쪽'이다."""
    assert to_scene_index(1, "L") == 6
    assert SCENE_CELL_NAME[6] == "낮은 바깥쪽"


def test_bottom_outer_cell_maps_to_low_inside_for_righty():
    """같은 cell 1이라도 우타는 화면 왼쪽이 몸쪽이라 '낮은 몸쪽'으로 간다."""
    assert to_scene_index(1, "R") == 8
    assert SCENE_CELL_NAME[8] == "낮은 몸쪽"


def test_top_cells_flip_columns_by_handedness():
    assert to_scene_index(9, "L") == 2
    assert to_scene_index(9, "R") == 0


def test_center_cell_is_handedness_invariant():
    """한가운데는 좌우 어느 쪽으로 뒤집어도 제자리다 — 반전 로직의 고정점."""
    assert to_scene_index(5, "L") == 4
    assert to_scene_index(5, "R") == 4


def test_row_is_always_inverted_regardless_of_handedness():
    """앱 row0(하단)은 항상 목업 row2로, 앱 row2(상단)는 항상 목업 row0으로 간다."""
    for stand in ("L", "R"):
        assert all(to_scene_index(c, stand) // 3 == 2 for c in (1, 2, 3))
        assert all(to_scene_index(c, stand) // 3 == 1 for c in (4, 5, 6))
        assert all(to_scene_index(c, stand) // 3 == 0 for c in (7, 8, 9))


def test_mapping_is_a_bijection_for_both_stands():
    """전단사가 깨지면 어떤 칸은 두 번 그려지고 어떤 칸은 비는데, 화면만 봐서는 모른다."""
    for stand in ("L", "R"):
        assert {to_scene_index(c, stand) for c in range(1, 10)} == set(range(9))


def test_payload_places_scores_at_mapped_positions():
    zone_scores = {cell: cell / 10 for cell in range(1, 10)}
    payload = build_scene_payload(
        mode="pitcher", stand="L", zone_scores=zone_scores,
        highlight_cell=5, metric="HIT_RISK",
    )
    assert len(payload["cells"]) == 9
    for cell in range(1, 10):
        assert payload["cells"][to_scene_index(cell, "L")] == cell / 10


def test_payload_excludes_out_of_zone_score_from_the_nine_cells():
    """키 0은 존 밖 점수다. 9칸에 섞이면 한 칸의 값이 통째로 틀린다."""
    zone_scores = {cell: 0.5 for cell in range(1, 10)}
    zone_scores[0] = 0.99
    payload = build_scene_payload(
        mode="pitcher", stand="R", zone_scores=zone_scores,
        highlight_cell=1, metric="HIT_RISK",
    )
    assert payload["cells"] == [0.5] * 9
    assert payload["outZone"] == 0.99


def test_payloads_of_both_stands_are_column_mirrors():
    zone_scores = {cell: cell / 10 for cell in range(1, 10)}
    kwargs = dict(zone_scores=zone_scores, highlight_cell=5, metric="HIT_RISK")
    left = build_scene_payload(mode="pitcher", stand="L", **kwargs)["cells"]
    right = build_scene_payload(mode="pitcher", stand="R", **kwargs)["cells"]
    for row in range(3):
        assert left[row * 3: row * 3 + 3] == right[row * 3: row * 3 + 3][::-1]


def test_payload_maps_highlight_cell_through_the_same_transform():
    payload = build_scene_payload(
        mode="batter", stand="R", zone_scores={c: 0.1 for c in range(1, 10)},
        highlight_cell=1, metric="PITCH_PROB",
    )
    assert payload["target"] == to_scene_index(1, "R")


def test_payload_maps_trajectory_cells_too():
    """궤적 목적지도 같은 변환을 타야 한다. 여기만 빠뜨리면 공이 엉뚱한 칸으로 날아간다."""
    payload = build_scene_payload(
        mode="pitcher", stand="R", zone_scores={c: 0.1 for c in range(1, 10)},
        highlight_cell=5, metric="HIT_RISK",
        trajectories=[
            {"pitch_label": "FF", "cell": 1, "rank": 1},
            {"pitch_label": "SL", "cell": 9, "rank": 2},
        ],
    )
    assert [t["idx"] for t in payload["trajectories"]] == [
        to_scene_index(1, "R"), to_scene_index(9, "R"),
    ]
    assert [t["label"] for t in payload["trajectories"]] == ["FF", "SL"]


def test_payload_drops_trajectories_with_unknown_cells():
    """모델이 존 밖(0)이나 결측을 내도 엔진에 넘기지 않는다."""
    payload = build_scene_payload(
        mode="pitcher", stand="L", zone_scores={c: 0.1 for c in range(1, 10)},
        highlight_cell=5, metric="HIT_RISK",
        trajectories=[
            {"pitch_label": "FF", "cell": 0, "rank": 1},
            {"pitch_label": "CH", "cell": None, "rank": 2},
            {"pitch_label": "SL", "cell": 4, "rank": 3},
        ],
    )
    assert [t["label"] for t in payload["trajectories"]] == ["SL"]


def test_payload_carries_mode_and_stand_verbatim():
    payload = build_scene_payload(
        mode="batter", stand="L", zone_scores={c: 0.1 for c in range(1, 10)},
        highlight_cell=5, metric="PITCH_PROB",
    )
    assert payload["mode"] == "batter"
    assert payload["bats"] == "L"
    assert payload["metric"] == "PITCH_PROB"
