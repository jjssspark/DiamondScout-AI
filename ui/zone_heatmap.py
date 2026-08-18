"""STRIKE ZONE BOARD (SVG) 렌더러 + zone_cell 라벨 변환.
app.py에서 순수 이동됨 (Task 2, 동작 변경 없음)."""

from services.scouting_service import ZONE_COL_OF_CELL, ZONE_ROW_OF_CELL, pitch_label_kr
from ui.trajectory_view import _trajectory_path

# ============================================================================
# STRIKE ZONE BOARD (HTML/SVG, 웹 화면 전용 - "스포츠 중계 그래픽 + 게임 HUD" 스타일)
# 위 matplotlib 함수(render_pitcher_hotcold_zone 등)는 PDF 등에 필요할 경우를 대비해 그대로
# 남겨두고, 실제 웹 화면(gr.HTML)에는 이 SVG 보드를 대신 사용한다. 계산값(zone_danger_scores /
# zone_probability_scores / best_cell / target_cell)은 그대로 재사용하고 시각화 레이어만 바꾼다.
# ============================================================================

def _zone_color(norm: float) -> str:
    """0(안전/낮음)~1(위험·노림/높음) 정규화 값을 시안(차가움)->로즈(뜨거움) 그라디언트 색으로 변환."""
    norm = max(0.0, min(1.0, norm))
    cold, hot = (8, 145, 178), (225, 29, 72)
    r = round(cold[0] + (hot[0] - cold[0]) * norm)
    g = round(cold[1] + (hot[1] - cold[1]) * norm)
    b = round(cold[2] + (hot[2] - cold[2]) * norm)
    return f"rgb({r},{g},{b})"

def _svg_batter_silhouette(cx: float, ground_y: float, side: str) -> str:
    """부드러운 SVG path + 베지어 곡선으로 그린 타자 실루엣(막대인간 금지, 단 완벽한 인체
    묘사보다는 어두운 보드 배경에서 확실히 눈에 띄는 것을 우선한다). 저지/하의/헬멧/배트/
    피부를 서로 다른 색으로 구분해 형체가 잘 보이게 하고, 이전 단색 버전보다 대비를 높인
    밝은 톤을 쓴다. side="left"/"right"는 보드 위에서 실루엣이 서는 위치이며, 실루엣은
    항상 스트라이크존(중앙)을 바라보는 타격 자세로 그린다."""
    sign = 1 if side == "left" else -1
    navy, navy_dark, pants, helmet, bat, skin = "#9db4dc", "#1c2740", "#eef2f9", "#22d3ee", "#d99a56", "#eab383"
    return f"""
    <g transform="translate({cx},{ground_y}) scale({sign},1)">
      <path d="M -24,-2 C -27,-22 -26,-42 -21,-60 C -19,-64 -8,-64 -7,-60 C -9,-42 -8,-22 -5,-2 Z" fill="{pants}" />
      <path d="M 5,-2 C 3,-24 6,-44 13,-60 C 15,-64 27,-64 29,-59 C 34,-40 33,-20 27,-2 Z" fill="{pants}" />
      <path d="M -27,-2 C -27,2 -25,6 -21,7 L -4,7 C -3,4 -3,0 -4,-2 Z" fill="{navy_dark}" />
      <path d="M 24,-2 C 24,2 26,6 30,7 L 33,7 C 35,3 35,-1 33,-2 Z" fill="{navy_dark}" />
      <path d="M -20,-58 C -22,-80 -19,-104 -11,-124 C -7,-134 4,-139 14,-136
               C 24,-133 28,-119 25,-104 C 22,-86 20,-70 16,-58 Z" fill="{navy}" />
      <path d="M -20,-59 C -12,-63 8,-63 17,-59 L 16,-53 C 6,-57 -11,-57 -19,-53 Z" fill="{navy_dark}" />
      <path d="M -6,-128 Q 10,-118 20,-152" fill="none" stroke="{navy_dark}" stroke-width="11" stroke-linecap="round" />
      <path d="M 12,-124 Q 22,-116 28,-150" fill="none" stroke="{navy}" stroke-width="12" stroke-linecap="round" />
      <circle cx="28" cy="-151" r="6.5" fill="{skin}" />
      <path d="M 28,-151 Q 16,-185 -2,-216" fill="none" stroke="{bat}" stroke-width="6.5" stroke-linecap="round" />
      <circle cx="-2" cy="-216" r="7.5" fill="{bat}" />
      <ellipse cx="9" cy="-172" rx="20" ry="21" fill="{helmet}" />
      <path d="M 22,-174 C 32,-178 44,-180 49,-186 C 50,-192 46,-196 40,-195
               C 32,-193 24,-188 18,-183 Z" fill="{helmet}" />
    </g>"""

def _render_strike_zone_board(
    zone_scores: dict[int, float], highlight_cell: int, stand: str, view_mode: str,
    header_label: str, sub_caption: str, unit_caption: str, metric_badge: str,
    trajectories: list[dict] | None = None,
) -> str:
    """"스포츠 중계 그래픽 + 게임 HUD" 스타일 STRIKE ZONE BOARD를 SVG로 그려 HTML 문자열로
    반환한다(gr.HTML용, matplotlib/컬러바 없음). 시점/좌우 로직은 기존 matplotlib 버전과 동일한
    규칙을 그대로 따른다: 투수 시점(캐노니컬)에서 상대가 좌타(L)면 왼쪽·우타(R)면 오른쪽에
    실루엣을 세우고, 타자 시점은 좌우를 통째로 뒤집는다(실루엣 위치 + 몸쪽/바깥쪽 라벨 순서 모두).
    trajectories: [{"pitch_label":..., "cell": int, "rank": 1|2|3}, ...] - 마운드/상단에서
    각 구종의 예상 목적지 셀로 향하는 궤적. rank=1이 가장 밝고, 2/3은 흐리게 그린다."""
    in_zone_values = [zone_scores.get(c, 0.0) for c in range(1, 10)]
    vmin = min(in_zone_values) if in_zone_values else 0.0
    vmax = max(in_zone_values) if in_zone_values else 1.0
    if vmin == vmax:
        vmin, vmax = vmin - 0.01, vmax + 0.01

    W, H = 640, 460
    CELL, GRID_LEFT, GRID_TOP = 88, 228, 78
    grid_cx, grid_bottom_y = GRID_LEFT + 1.5 * CELL, GRID_TOP + 3 * CELL
    trajectory_start = (grid_cx, GRID_TOP - 40)

    # 투수 시점 기준(캐노니컬) 좌우: 타자 모드는 col을 뒤집어 전체를 거울 대칭시킨다
    # (matplotlib의 ax.invert_xaxis()와 동일한 효과를 좌표 계산으로 직접 구현).
    def cell_xy(cell: int) -> tuple[float, float]:
        row, col = ZONE_ROW_OF_CELL[cell], ZONE_COL_OF_CELL[cell]
        disp_col = col if view_mode == "pitcher" else (2 - col)
        x = GRID_LEFT + disp_col * CELL
        y = GRID_TOP + (2 - row) * CELL  # row0(하단)이 아래쪽(큰 y)에 오도록 반전
        return x, y

    # 궤적: 숫자보다 먼저 그려서 셀/텍스트 아래(뒤)에 깔리게 하고, 최고 순위만 살짝 진하게 한다.
    lateral_sign = 1.0 if view_mode == "pitcher" else -1.0
    trajectory_svg_parts = []
    for traj in (trajectories or []):
        cell = traj.get("cell")
        if cell is None or cell not in ZONE_ROW_OF_CELL:
            continue
        x, y = cell_xy(cell)
        end = (x + CELL / 2, y + CELL / 2)
        rank = traj.get("rank", 3)
        path_d = _trajectory_path(trajectory_start, end, traj.get("pitch_label", "OTHER"), lateral_sign)
        if rank == 1:
            color, width, opacity, ball_r = "#c8102e", 4.2, 0.85, 7
        elif rank == 2:
            color, width, opacity, ball_r = "#14203c", 2.6, 0.30, 5
        else:
            color, width, opacity, ball_r = "#14203c", 2.2, 0.18, 4
        trajectory_svg_parts.append(
            f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" opacity="{opacity}" />'
        )
        if rank != 1:  # rank=1의 끝점 마커는 강조 셀의 볼 마커와 겹치므로 생략
            trajectory_svg_parts.append(f'<circle cx="{end[0]:.1f}" cy="{end[1]:.1f}" r="{ball_r}" fill="{color}" opacity="{opacity+0.2}" />')
    trajectory_svg = "".join(trajectory_svg_parts)

    cells_svg = []
    for cell in range(1, 10):
        x, y = cell_xy(cell)
        val = zone_scores.get(cell, 0.0)
        norm = (val - vmin) / (vmax - vmin) if vmax > vmin else 0.5
        color = _zone_color(norm)
        is_best = cell == highlight_cell
        glow = 'filter="url(#zoneGlow)"' if is_best else ""
        border = "#1f8a4c" if is_best else "rgba(20,32,60,0.18)"
        border_w = 3.5 if is_best else 1.2
        cells_svg.append(f"""
        <rect x="{x+3}" y="{y+3}" width="{CELL-6}" height="{CELL-6}" rx="12" fill="{color}" fill-opacity="0.55"
              stroke="{border}" stroke-width="{border_w}" {glow} />""")
        if is_best:
            cx_ball, cy_ball = x + CELL / 2, y + CELL / 2
            cells_svg.append(f"""
            <circle cx="{cx_ball}" cy="{cy_ball}" r="30" fill="#1f8a4c" opacity="0.14" />
            <circle cx="{cx_ball}" cy="{cy_ball}" r="13" fill="#ffffff" stroke="#1f8a4c" stroke-width="1.8" />""")
        cells_svg.append(f"""
        <text x="{x + CELL/2}" y="{y + CELL/2 + 10}" text-anchor="middle" font-size="32" font-weight="800"
              fill="#f8fafc" style="paint-order: stroke; stroke: #05070c; stroke-width: 3.5px;">{val:.0%}</text>""")

    out_val = zone_scores.get(0, 0.0)
    border_labels = [
        (grid_cx, GRID_TOP - 22), (grid_cx, grid_bottom_y + 30),
        (GRID_LEFT - 30, GRID_TOP + 1.5 * CELL), (GRID_LEFT + 3 * CELL + 30, GRID_TOP + 1.5 * CELL),
    ]
    border_svg = "".join(
        f'<text x="{bx}" y="{by}" text-anchor="middle" font-size="13" fill="#6b6555">{out_val:.0%}</text>'
        for bx, by in border_labels
    )

    # 실루엣: 캐노니컬(투수 시점) 규칙은 "좌타=왼쪽/우타=오른쪽", 타자 시점은 반전.
    canonical_side = "left" if stand == "L" else "right"
    side = canonical_side if view_mode == "pitcher" else ("right" if canonical_side == "left" else "left")
    silhouette_cx = 95 if side == "left" else W - 95
    silhouette = _svg_batter_silhouette(silhouette_cx, grid_bottom_y + 40, side)

    ground_svg = f"""
    <ellipse cx="{W/2}" cy="{grid_bottom_y + 70}" rx="290" ry="95" fill="#132018" opacity="0.7" />
    <ellipse cx="{W/2}" cy="{grid_bottom_y + 70}" rx="290" ry="95" fill="none" stroke="#22c55e" stroke-width="10" opacity="0.12" />"""
    plate_svg = f"""
    <polygon points="{grid_cx-42},{grid_bottom_y+18} {grid_cx+42},{grid_bottom_y+18} {grid_cx+52},{grid_bottom_y+40}
                     {grid_cx},{grid_bottom_y+58} {grid_cx-52},{grid_bottom_y+40}"
             fill="#ffffff" stroke="#14203c" stroke-width="1.5" />"""
    mound_svg = ""
    if view_mode == "pitcher":
        mound_svg = f"""
        <circle cx="{grid_cx}" cy="{GRID_TOP-46}" r="17" fill="#a16207" />
        <circle cx="{grid_cx}" cy="{GRID_TOP-46}" r="17" fill="none" stroke="#f5e6c8" stroke-width="1.6" />
        <line x1="{grid_cx}" y1="{GRID_TOP-29}" x2="{grid_cx}" y2="{GRID_TOP-14}" stroke="#a16207" stroke-width="2.5" />"""

    inside_label, outside_label = ("몸쪽", "바깥쪽") if stand == "R" else ("바깥쪽", "몸쪽")
    left_label, right_label = (outside_label, inside_label) if view_mode == "batter" else (inside_label, outside_label)
    hand_kr = "좌타" if stand == "L" else "우타"
    view_name_en = "PITCHER VIEW" if view_mode == "pitcher" else "BATTER VIEW"

    return f"""
    <div class="ds-zone-card">
      <div class="ds-zone-header">
        <span class="ds-zone-header-en">{view_name_en}</span>
        <span class="ds-zone-header-sep">|</span>
        <span class="ds-zone-header-kr">HOT &amp; COLD ZONE</span>
        <span class="ds-zone-badge">{metric_badge}</span>
      </div>
      <div class="ds-zone-sub">{header_label} &middot; {hand_kr}({stand}) 기준 &middot; {sub_caption}</div>
      <svg viewBox="0 0 {W} {H}" class="ds-zone-svg" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="zoneGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {ground_svg}
        {plate_svg}
        {mound_svg}
        {silhouette}
        {trajectory_svg}
        <rect x="{GRID_LEFT}" y="{GRID_TOP}" width="{3*CELL}" height="{3*CELL}" rx="16" fill="none"
              stroke="#14203c" stroke-width="2.2" />
        {"".join(cells_svg)}
        {border_svg}
      </svg>
      <div class="ds-zone-footer">
        <span>&#9664; 타자 기준 {left_label}</span>
        <div class="ds-zone-legend">
          <span class="ds-zone-legend-label">안전/낮음</span>
          <span class="ds-zone-legend-pill"></span>
          <span class="ds-zone-legend-label">위험·노림/높음</span>
        </div>
        <span>타자 기준 {right_label} &#9654;</span>
      </div>
      <div class="ds-zone-caption">{unit_caption}</div>
    </div>"""

def render_pitcher_zone_board(
    zone_hit_risk_scores: dict[int, float], best_cell: int, recommended_label: str, stand: str,
    trajectories: list[dict] | None = None,
) -> str:
    recommended_kr = pitch_label_kr(recommended_label)
    return _render_strike_zone_board(
        zone_hit_risk_scores, best_cell, stand, "pitcher",
        f"{recommended_kr}({recommended_label}) 피안타 위험", "낮을수록 안전",
        "낮은 코스로 던지는 게 안전해요", "HIT RISK", trajectories,
    )

def render_batter_zone_board(
    zone_probability_scores: dict[int, float], target_cell: int, stand: str,
    trajectories: list[dict] | None = None,
) -> str:
    return _render_strike_zone_board(
        zone_probability_scores, target_cell, stand, "batter",
        "예상 투구 확률", "높을수록 노림",
        "높은 코스를 노려보세요", "PITCH PROB", trajectories,
    )

def _zone_hand_label(cell: int, stand: str) -> str:
    """zone_cell의 좌/중/우 열을 타자의 타석 방향(stand) 기준 몸쪽/바깥쪽/가운데로 변환한다.
    우타 기준 plate_x 음수쪽=몸쪽·양수쪽=바깥쪽, 좌타는 그 반대로 해석한다."""
    col = ZONE_COL_OF_CELL[cell]
    if col == 1:
        return "가운데"
    if stand == "R":
        return "몸쪽" if col == 0 else "바깥쪽"
    return "바깥쪽" if col == 0 else "몸쪽"
