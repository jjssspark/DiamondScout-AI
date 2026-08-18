"""HOT & COLD ZONE matplotlib 시각화 + SVG 궤적(trajectory) 경로 계산.
app.py에서 순수 이동됨 (Task 2, 동작 변경 없음)."""

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyBboxPatch

from services.scouting_service import ZONE_COL_OF_CELL, ZONE_ROW_OF_CELL, pitch_label_kr

# ============================================================================
# HOT & COLD ZONE 시각화 (3x3 스트라이크존 + 바깥쪽 영역)
# ============================================================================

def _hotcold_grid(zone_scores: dict[int, float]) -> np.ndarray:
    """zone_cell 0(존 밖)~9를 5x5 격자로 변환한다. 바깥 테두리 16칸은 존 밖 점수로 채우고,
    가운데 3x3(1~9)만 실제 구역별 값을 채운다."""
    grid = np.full((5, 5), zone_scores.get(0, 0.0))
    for cell in range(1, 10):
        r, c = ZONE_ROW_OF_CELL[cell], ZONE_COL_OF_CELL[cell]
        grid[1 + r, 1 + c] = zone_scores.get(cell, 0.0)
    return grid

def _draw_ground_background(ax) -> None:
    """스트라이크존 격자(imshow, zorder=2) 뒤쪽 여백에 어두운 그라운드 톤 타원을 깔아, 미래지향적인
    다크 테마 안에서도 실루엣/홈플레이트가 붕 뜬 것처럼 보이지 않게 한다."""
    ax.add_patch(Ellipse((2.0, -0.5), width=9.6, height=4.8, facecolor="#132018", edgecolor="none", zorder=1))
    ax.add_patch(Ellipse((2.0, -0.5), width=9.6, height=4.8, facecolor="none", edgecolor="#22c55e", alpha=0.18, linewidth=10, zorder=1))

def _draw_batter_silhouette(ax, side: str, y_center: float = 1.55) -> None:
    """헬멧/상체/팔/다리/배트를 갖춘 타격 자세 실루엣을 채워진 도형으로 그린다(막대인간 금지).
    side="left"/"right"는 실루엣이 서는 화면 쪽이며, 타자는 항상 스트라이크존(화면 중앙) 쪽을
    바라보는 타격 자세로 그려진다. 좌/우 어느 쪽에 서든 같은 모양을 거울처럼 반전해 재사용한다."""
    sign = 1.0 if side == "left" else -1.0
    cx = -1.55 if side == "left" else 5.55

    def pt(lx: float, ly: float) -> tuple[float, float]:
        return (cx + sign * lx, y_center + ly)

    navy = "#7c94b8"
    navy_dark = "#4b5f7f"
    pants_color = "#d8dee9"
    helmet_color = "#22d3ee"
    bat_color = "#d4a15c"
    skin = "#e0ac7c"

    # 다리(밝은 회색 유니폼 바지): 뒷다리는 곧게, 앞다리는 존 쪽으로 벌리고 굽힌 타격 자세.
    # 상의(navy)와 톤을 분리해 "상체/하체"가 한 덩어리로 뭉쳐 보이지 않게 한다.
    ax.add_patch(plt.Polygon([pt(-0.30, 0.05), pt(-0.08, 0.05), pt(-0.14, -0.95), pt(-0.34, -0.95)],
                              closed=True, facecolor=pants_color, edgecolor="none", zorder=5))
    ax.add_patch(plt.Polygon([pt(0.06, 0.05), pt(0.30, 0.05), pt(0.46, -0.95), pt(0.20, -0.95)],
                              closed=True, facecolor=pants_color, edgecolor="none", zorder=5))
    # 신발
    ax.add_patch(plt.Polygon([pt(-0.36, -0.95), pt(-0.10, -0.95), pt(-0.10, -1.06), pt(-0.40, -1.06)],
                              closed=True, facecolor=navy_dark, edgecolor="none", zorder=5))
    ax.add_patch(plt.Polygon([pt(0.16, -0.95), pt(0.48, -0.95), pt(0.52, -1.06), pt(0.18, -1.06)],
                              closed=True, facecolor=navy_dark, edgecolor="none", zorder=5))
    # 몸통 (허리보다 어깨가 넓은 사다리꼴 유니폼 상의)
    ax.add_patch(plt.Polygon([pt(-0.22, 0.05), pt(0.10, 0.05), pt(0.34, 0.85), pt(-0.06, 0.90)],
                              closed=True, facecolor=navy, edgecolor="none", zorder=5))
    # 벨트 라인: 상의/하의 경계를 얇은 선으로 또렷하게 구분해 유니폼처럼 보이게 한다.
    ax.add_patch(plt.Polygon([pt(-0.24, 0.02), pt(0.12, 0.02), pt(0.12, 0.08), pt(-0.24, 0.08)],
                              closed=True, facecolor=navy_dark, edgecolor="none", zorder=5.2))
    # 팔: 두 손이 가슴 앞에 모여 배트를 쥔 "타격 준비 자세". 뒤쪽 팔을 먼저 그려 앞쪽 팔에
    # 자연스럽게 가려지게 한다.
    ax.plot([pt(-0.06, 0.82)[0], pt(0.16, 0.62)[0], pt(0.32, 0.68)[0]],
            [pt(-0.06, 0.82)[1], pt(0.16, 0.62)[1], pt(0.32, 0.68)[1]],
            color=navy_dark, linewidth=6, solid_capstyle="round", zorder=5)
    ax.plot([pt(0.18, 0.78)[0], pt(0.30, 0.60)[0], pt(0.34, 0.68)[0]],
            [pt(0.18, 0.78)[1], pt(0.30, 0.60)[1], pt(0.34, 0.68)[1]],
            color=navy, linewidth=7, solid_capstyle="round", zorder=6)
    # 손(배트를 쥔 지점, 가슴 앞)
    grip = pt(0.33, 0.68)
    ax.add_patch(plt.Circle(grip, 0.055, facecolor=skin, edgecolor="none", zorder=6))
    # 배트: 손에서 뒤쪽 어깨 위로 세워 든 "테이크백" 자세 + 배트 헤드
    bat_end = pt(-0.08, 1.48)
    ax.plot([grip[0], bat_end[0]], [grip[1], bat_end[1]], color=bat_color, linewidth=5,
            solid_capstyle="round", zorder=6.5)
    ax.add_patch(plt.Circle(bat_end, 0.075, facecolor=bat_color, edgecolor="none", zorder=6.5))
    # 머리(헬멧) + 챙: 몸통 대비 비율을 조금 키워 "야구 타자"임이 멀리서도 분명히 보이게 한다.
    head_c = pt(0.04, 1.16)
    ax.add_patch(plt.Circle(head_c, 0.23, facecolor=helmet_color, edgecolor="none", zorder=6))
    ax.add_patch(plt.Polygon([pt(0.20, 1.16), pt(0.48, 1.09), pt(0.46, 0.99), pt(0.22, 1.06)],
                              closed=True, facecolor=helmet_color, edgecolor="none", zorder=6))

def _draw_ball_marker(ax, cx: float, cy: float, glow_color: str) -> None:
    """추천/노림 셀 중심에 은은하게 빛나는 공 마커를 그려, 참고 이미지(투수 시점 사진의 노란 글로우
    볼)처럼 '공이 예상되는 위치'가 숫자·강조 테두리뿐 아니라 그림으로도 한눈에 보이게 한다. zorder를
    셀 숫자 텍스트(zorder=4)보다 낮게 잡아, 공 마커가 배경처럼 깔리고 숫자는 항상 그 위에서 잘 보이게 한다."""
    for radius, alpha in [(0.36, 0.10), (0.27, 0.20), (0.19, 0.30)]:
        ax.add_patch(plt.Circle((cx, cy), radius, facecolor="#fde68a", edgecolor="none", alpha=alpha, zorder=3.0))
    ax.add_patch(plt.Circle((cx, cy), 0.13, facecolor="#fffbeb", edgecolor=glow_color, linewidth=1.3, alpha=0.95, zorder=3.2))

def _draw_pitch_trajectory(ax, target_x: float, target_y: float, color: str) -> None:
    """존 위쪽에서 추천/노림 셀로 이어지는 궤적 곡선을 은은하게 그려, 참고 이미지의 '궤적 콘' 느낌을
    직접 그린 곡선으로 재현한다(이미지 자체를 복사하지 않음). 존 상단 테두리 값(zorder=4)이나 강조
    셀 숫자보다 낮은 zorder로 깔아, 궤적이 배경처럼 보이고 숫자를 가리지 않게 한다."""
    start_x, start_y = 2.0, 4.65
    t = np.linspace(0.0, 1.0, 40)
    ctrl_x = (start_x + target_x) / 2 + (0.7 if target_x >= start_x else -0.7)
    ctrl_y = (start_y + target_y) / 2
    xs = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * ctrl_x + t ** 2 * target_x
    ys = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * ctrl_y + t ** 2 * target_y
    for lw, alpha in [(10, 0.05), (5, 0.12), (2, 0.45)]:
        ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha, zorder=2.6, solid_capstyle="round")

def _draw_home_plate(ax) -> None:
    """스트라이크존 3x3 격자 바로 아래 홈플레이트 오각형을 그려 야구장 시점을 표현한다."""
    pts = [(1.55, -0.85), (2.45, -0.85), (2.65, -0.6), (2.0, -0.35), (1.35, -0.6)]
    ax.add_patch(plt.Polygon(pts, closed=True, facecolor="#e2e8f0", edgecolor="#22d3ee", linewidth=1.3, zorder=3))

def _draw_mound_marker(ax) -> None:
    """투수 모드 전용: 격자 위쪽에 마운드 아이콘을 그려 "투수 시점(마운드에서 홈플레이트를
    바라보는 시야)"임을 시각적으로 표현한다."""
    ax.add_patch(plt.Circle((2, 5.25), 0.34, facecolor="#a16207", edgecolor="none", zorder=3))
    ax.add_patch(plt.Circle((2, 5.25), 0.34, facecolor="none", edgecolor="#f5e6c8", linewidth=1.5, zorder=3))
    ax.plot([2, 2], [4.9, 4.55], color="#a16207", linewidth=2, zorder=3)

def _render_hotcold_zone(
    zone_scores: dict[int, float], highlight_cell: int, title: str, caption: str, stand: str, view_mode: str,
):
    """3x3 스트라이크존 + 바깥 테두리를 HOT & COLD 컬러맵으로 그리고, 홈플레이트/타자 실루엣을
    더해 "투수 시점(마운드에서 타자 쪽을 바라봄)" 또는 "타자 시점(타석에 서서 투수를 바라봄)"을
    구분해 보여준다.
    - 제목이 잘리지 않도록 figure를 넉넉히 잡고 subplots_adjust로 상/하 여백을 확보한다.
    - 바깥 테두리는 상/하/좌/우 중앙 4칸에만 존 밖 평균값을 표시해 "바깥 영역도 의미 있게" 보여준다.
    - 실루엣/좌우 라벨은 항상 "투수 시점(마운드→홈플레이트)" 기준으로 먼저 그리고, view_mode가
      "batter"면 축 전체를 좌우 반전(ax.invert_xaxis)해 "타자가 투수를 바라보는" 정반대 시점을
      만든다. 이렇게 하면 히트맵 셀·강조 테두리·홈플레이트·실루엣이 모두 한 번에 자연스럽게
      거울 대칭되고, 좌표 계산을 모드별로 두 벌 유지할 필요가 없다.
    - 투수 시점 기준 규칙: 상대 타자가 좌타(L)면 실루엣이 화면 왼쪽, 우타(R)면 화면 오른쪽.
      타자 시점은 이 축이 반전되므로 자동으로 좌우가 뒤바뀐다.
    - view_mode="pitcher"면 마운드 아이콘을 함께 그려 투수 시점임을 강조한다.
    """
    grid = _hotcold_grid(zone_scores)
    in_zone_values = [zone_scores.get(c, 0.0) for c in range(1, 10)]
    # 존 밖(0) 값은 종종 in-zone 값들보다 훨씬 커서(예: 볼 판정 확률) 컬러스케일을 같이 쓰면
    # 정작 중요한 3x3 안쪽 대비가 뭉개진다. vmin/vmax를 in-zone 값 범위로 고정하고, 존 밖
    # 셀은 그 범위를 벗어나면 자동으로 극단 색(가장 진한 빨강/파랑)으로 클리핑되게 둔다.
    vmin = min(in_zone_values) if in_zone_values else 0.0
    vmax = max(in_zone_values) if in_zone_values else 1.0
    if vmin == vmax:
        vmin, vmax = vmin - 0.01, vmax + 0.01

    dark_bg = "#05070c"
    fig, ax = plt.subplots(figsize=(7.4, 7.1))
    fig.patch.set_facecolor(dark_bg)
    ax.set_facecolor(dark_bg)
    # "고급 스포츠 분석 화면" 느낌을 위해 전체를 감싸는 둥근 유리 패널을 가장 아래(zorder=0)에
    # 깔아, 그림이 빈 배경에 떠 있지 않고 카드 형태의 분석 보드 안에 담긴 것처럼 보이게 한다.
    ax.add_patch(FancyBboxPatch(
        (-2.55, -1.28), 9.1, 7.25, boxstyle="round,pad=0,rounding_size=0.35",
        linewidth=1.2, edgecolor="#1e3a4f", facecolor="#0a1220", alpha=0.9, zorder=0,
    ))
    _draw_ground_background(ax)
    # 다크 테마에서는 차가운 시안(안전)~뜨거운 주황/빨강(위험) 대비가 네온 느낌에 더 잘 어울려
    # 기존 RdYlBu_r 대신 사용하고, alpha로 살짝 반투명하게 만들어 그리드 라인이 배경과 겹쳐도 붕 뜨지 않게 한다.
    im = ax.imshow(
        grid, cmap="turbo", origin="lower", vmin=vmin, vmax=vmax,
        extent=(-0.5, 4.5, -0.5, 4.5), zorder=2, alpha=0.88,
    )

    for cell in range(1, 10):
        r, c = ZONE_ROW_OF_CELL[cell], ZONE_COL_OF_CELL[cell]
        gr_, gc = 1 + r, 1 + c
        val = zone_scores.get(cell, 0.0)
        ax.text(
            gc, gr_, f"{val:.2f}", ha="center", va="center", fontsize=16, fontweight="bold",
            color="white", zorder=4, path_effects=[pe.withStroke(linewidth=2.5, foreground="#05070c")],
        )

    out_val = zone_scores.get(0, 0.0)
    for gx, gy in [(2, 4), (2, 0), (0, 2), (4, 2)]:  # 상/하/좌/우 테두리 중앙 4칸
        ax.text(gx, gy, f"{out_val:.2f}", ha="center", va="center", fontsize=10, color="#cbd5e1", zorder=4)

    # 추천 존은 네온 초록 glow: 같은 사각형을 굵기/투명도를 바꿔 여러 겹 겹쳐 그려 은은한 발광 효과를 낸다.
    hr, hc = ZONE_ROW_OF_CELL[highlight_cell], ZONE_COL_OF_CELL[highlight_cell]
    # 존 위쪽에서 추천/노림 셀로 이어지는 궤적 곡선(참고 이미지의 "궤적 콘"을 직접 그린 곡선으로 재해석).
    _draw_pitch_trajectory(ax, 1 + hc, 1 + hr, "#4ade80")
    for lw, alpha in [(14, 0.10), (9, 0.20), (5, 0.35)]:
        ax.add_patch(plt.Rectangle(
            (1 + hc - 0.5, 1 + hr - 0.5), 1, 1, fill=False, edgecolor="#22c55e",
            linewidth=lw, alpha=alpha, zorder=4,
        ))
    ax.add_patch(plt.Rectangle((1 + hc - 0.5, 1 + hr - 0.5), 1, 1, fill=False, edgecolor="#4ade80", linewidth=3, zorder=4))
    # 강조 셀 중심에 공 마커를 겹쳐, "숫자/테두리"뿐 아니라 그림으로도 예상 위치가 보이게 한다.
    _draw_ball_marker(ax, 1 + hc, 1 + hr, "#4ade80")

    # 스트라이크존 테두리는 흰색/네온 라인으로 표현.
    zone_border = plt.Rectangle((0.5, 0.5), 3, 3, fill=False, edgecolor="#e2e8f0", linewidth=2.2, zorder=4)
    ax.add_patch(zone_border)

    _draw_home_plate(ax)
    # 투수 시점 기준(캐노니컬) 좌우: 상대 타자가 좌타(L)면 왼쪽, 우타(R)면 오른쪽에 실루엣을 세운다.
    # 타자 모드는 아래에서 축을 반전시켜 이 좌우를 통째로 뒤집는다.
    silhouette_side = "left" if stand == "L" else "right"
    _draw_batter_silhouette(ax, silhouette_side)
    if view_mode == "pitcher":
        _draw_mound_marker(ax)

    ax.set_xlim(-2.6, 6.6)
    ax.set_ylim(-1.3, 6.0 if view_mode == "pitcher" else 4.9)
    if view_mode == "batter":
        # 타자가 투수를 바라보는 시점 = 투수 시점(마운드→홈플레이트)을 좌우로 뒤집은 모습.
        ax.invert_xaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(title, fontsize=12, pad=10, wrap=True, color="#f8fafc")

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.ax.tick_params(labelsize=8, colors="#cbd5e1")
    cbar.outline.set_edgecolor("#334155")

    inside_label, outside_label = ("몸쪽", "바깥쪽") if stand == "R" else ("바깥쪽", "몸쪽")
    # fig.text는 축(ax)과 달리 invert_xaxis()의 영향을 받지 않는 "그림 좌표"라서, 타자 모드에서는
    # 화면 좌/우에 찍히는 라벨 순서를 직접 맞바꿔야 실제로 반전된 그림과 말이 맞는다.
    left_label, right_label = (outside_label, inside_label) if view_mode == "batter" else (inside_label, outside_label)
    hand_kr = "좌타" if stand == "L" else "우타"
    view_name = "투수" if view_mode == "pitcher" else "타자"
    guide = "낮을수록 안전" if view_mode == "pitcher" else "높을수록 노림"
    # 별도 흰색 시점 안내 박스 대신, "시점 | 타석 방향 | 해석 가이드"를 캡션 한 줄에 압축해 보여준다.
    fig.text(0.44, 0.155, f"{view_name} 시점 | {hand_kr}({stand}) 기준 | {guide}", ha="center", fontsize=10, color="#22d3ee", fontweight="bold")
    fig.text(0.44, 0.115, f"◀ 타자 기준 {left_label}          타자 기준 {right_label} ▶  ·  (테두리 숫자 = 존 밖)", ha="center", fontsize=8.5, color="#94a3b8")
    fig.text(0.44, 0.045, caption, ha="center", fontsize=11, fontweight="bold", color="#f1f5f9")

    fig.subplots_adjust(top=0.88, bottom=0.23, left=0.04, right=0.86)
    return fig

def render_pitcher_hotcold_zone(zone_danger_scores: dict[int, float], best_cell: int, recommended_label: str, stand: str):
    recommended_kr = pitch_label_kr(recommended_label)
    return _render_hotcold_zone(
        zone_danger_scores, best_cell,
        f"투수용 HOT & COLD ZONE\n{recommended_kr}({recommended_label}) 위험도 (낮음=파랑/안전, 높음=빨강/위험)",
        "낮은 숫자(파랑) 쪽으로 던지는 게 안전합니다",
        stand, "pitcher",
    )

def render_batter_hotcold_zone(zone_probability_scores: dict[int, float], target_cell: int, stand: str):
    return _render_hotcold_zone(
        zone_probability_scores, target_cell,
        "타자용 HOT & COLD ZONE\n예상 투구 위치 확률 (낮음=파랑, 높음=빨강/노림수)",
        "높은 숫자(빨강) 쪽을 노리세요",
        stand, "batter",
    )

# 구종별 궤적 곡선 느낌(횡변화 비율, 낙차/감속 비율). FF/SI는 거의 직선, SL/ST는 옆으로 크게,
# CH/FS는 속도 죽으며 아래로, CU/KC/SV는 크게 떨어지고, FC는 짧고 살짝 꺾인다.
PITCH_TRAJECTORY_PROFILE = {
    "FF": (0.05, 0.05), "SI": (0.10, 0.12),
    "SL": (0.42, 0.10), "ST": (0.50, 0.10),
    "CH": (0.15, 0.32), "FS": (0.15, 0.38),
    "CU": (0.20, 0.50), "KC": (0.20, 0.50), "SV": (0.32, 0.42),
    "FC": (0.14, 0.05), "OTHER": (0.15, 0.15),
}

def _trajectory_path(start: tuple[float, float], end: tuple[float, float], pitch_label: str, lateral_sign: float) -> str:
    """구종별 궤적 프로필에 따라 cubic bezier 경로 문자열을 만든다. lateral_sign으로 타자 모드
    좌우 반전(cell_xy의 disp_col 반전)과 방향을 맞춘다."""
    sx, sy = start
    ex, ey = end
    lateral, drop = PITCH_TRAJECTORY_PROFILE.get(pitch_label, (0.15, 0.15))
    dx, dy = ex - sx, ey - sy
    c1x, c1y = sx + dx * 0.33 + dx * lateral * lateral_sign, sy + dy * 0.33
    c2x, c2y = sx + dx * 0.66 + dx * lateral * 0.4 * lateral_sign, sy + dy * 0.66 + abs(dy) * drop
    return f"M {sx:.1f},{sy:.1f} C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {ex:.1f},{ey:.1f}"
