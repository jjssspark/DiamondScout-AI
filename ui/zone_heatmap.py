"""존 칸의 좌/중/우 열을 타자 기준 몸쪽/바깥쪽으로 옮기는 규칙.

원래는 SVG 스트라이크 존 보드 렌더러가 함께 있었으나 Task 5Z에서 캔버스 씬
(ui/scene.py + ui/static/scene.js)으로 교체되면서 호출부가 사라져 제거했다.
그 보드는 col 0을 화면 왼쪽에 그렸는데 실제 plate_x 위치는 오른쪽이라
좌우가 뒤집혀 있었다(TROUBLESHOOTING.md TS-008). 되살리지 말 것.

여기 남은 규칙 자체는 그 버그와 무관하게 처음부터 맞았다. plate_x 부호를
직접 근거로 삼기 때문이다.
"""

from services.scouting_service import ZONE_COL_OF_CELL


def _zone_hand_label(cell: int, stand: str) -> str:
    """zone_cell의 좌/중/우 열을 타자의 타석 방향(stand) 기준 몸쪽/바깥쪽/가운데로 변환한다.
    우타 기준 plate_x 음수쪽=몸쪽·양수쪽=바깥쪽, 좌타는 그 반대로 해석한다."""
    col = ZONE_COL_OF_CELL[cell]
    if col == 1:
        return "가운데"
    if stand == "R":
        return "몸쪽" if col == 0 else "바깥쪽"
    return "바깥쪽" if col == 0 else "몸쪽"
