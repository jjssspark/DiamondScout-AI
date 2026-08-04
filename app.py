"""
DiamondScout AI - Gradio 데모 UI (투수 모드 / 타자 모드 중심 개편판)
services/scouting_service.py의 ScoutingService를 사용해 "내가 투수라면" / "내가 타자라면"
관점으로 전력분석을 실행하는 화면. 사용자는 선수 ID/경기 상황/전략 코멘트만 입력하고,
최근 5구·타자 타석 방향·투수 투구 방향은 내부에서 자동 추정한다. 각 모드 결과 화면
하단에는 그 모드의 최신 분석 결과를 바로 참조하는 Instant Scout Q&A가 함께 배치된다.
모델/서비스 파일은 이 파일에서만 조립한다.

실행:
    python app.py
    또는: gradio app.py   (코드 변경 시 자동 리로드)
    (이 프로젝트는 venv를 쓰므로 실제로는 ./venv/bin/python app.py 로 실행)
"""

import os
import re
import textwrap
from datetime import datetime

import gradio as gr
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Ellipse, FancyBboxPatch

from services.scouting_service import (
    ZONE_COL_OF_CELL,
    ZONE_ROW_OF_CELL,
    ScoutingRequest,
    ScoutingService,
    get_batter_display,
    pitch_label_kr,
)

# matplotlib 기본 폰트(DejaVu Sans)는 한글 글리프가 없어 히트맵/위치 그래프의 한글 라벨이
# 깨지므로(빈 네모) macOS 기본 한글 폰트로 지정한다.
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

scouting_service = ScoutingService()

# RAG(임베딩+FAISS)/LLM(Ollama)은 무거운 선택적 의존성이라 초기화 실패가 앱 전체를
# 죽이지 않도록 감싸고, 실패 시 Instant Scout Q&A는 rule-based 안내만 제공한다.
try:
    from services.rag_service import RAGService

    rag_service = RAGService()
except Exception as exc:  # noqa: BLE001 - 임베딩/FAISS 초기화 실패는 다양한 예외로 나타날 수 있음
    print(f"[경고] RAGService 초기화 실패, 도메인 문서 검색 없이 진행합니다: {exc}")
    rag_service = None

try:
    from services.coach_agent import CoachAgent

    coach_agent = CoachAgent()
except Exception as exc:  # noqa: BLE001
    print(f"[경고] CoachAgent 초기화 실패, Instant Scout Q&A를 사용할 수 없습니다: {exc}")
    coach_agent = None

# DBService는 자체적으로 연결/저장 실패를 삼키고 None을 반환하지만(services/db_service.py),
# import 자체가 실패하는 경우까지 대비해 여기서도 감싼다.
try:
    from services.db_service import DBService

    db_service = DBService()
except Exception as exc:  # noqa: BLE001
    print(f"[경고] DBService 초기화 실패, DB 로깅 없이 진행합니다: {exc}")
    db_service = None


def db_save_analysis_log(mode, pitcher_id, context, recent_pitches, user_comment, result):
    if db_service is None:
        return None
    try:
        return db_service.save_analysis_log(mode, pitcher_id, context, recent_pitches, user_comment, result)
    except Exception as exc:  # noqa: BLE001
        print(f"[경고] analysis_logs 저장 실패: {exc}")
        return None


def db_save_qa_log(question, answer, answer_source, used_context, analysis_log_id):
    if db_service is None:
        return
    try:
        db_service.save_qa_log(question, answer, answer_source, used_context, analysis_log_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[경고] qa_logs 저장 실패: {exc}")


# 시연용 기본 ID. 투수는 2025 데이터 3,214구(Rodón, Carlos), 타자는 2025 데이터 3,071구
# (batter_matchup_profile에 선수 이름 컬럼이 없어 항상 "Batter ID {id}"로 표시됨).
DEFAULT_PITCHER_ID = 607074
DEFAULT_BATTER_ID = 621566
DEFAULT_COMMENT_PITCHER = "고의4구 느낌으로 존 바깥으로 빼고 싶어"
DEFAULT_COMMENT_BATTER = "상대가 초구부터 존 안으로 승부할 것 같다"

EXAMPLE_QUESTIONS = [
    "왜 이 구종을 추천했어?",
    "어느 존으로 던지는 게 좋아?",
    "존 바깥으로 빼다가 패스트볼이면 컨택되면 어떡해?",
    "상대 타자의 약점은 뭐야?",
    "이 공을 노려도 돼?",
]

# 발표 시연용: 2025 데이터 표본이 풍부한 투수 5명/타자 5명 후보 (data/processed/demo_players_2025.csv).
# 드롭다운에서 고르면 ID 입력창에 해당 ID가 채워진다.
_demo_players_df = pd.read_csv(os.path.join("data", "processed", "demo_players_2025.csv"))
DEMO_PITCHER_CHOICES = [
    (row["name"], int(row["id"]))
    for _, row in _demo_players_df[_demo_players_df["role"] == "pitcher"].iterrows()
]
# 데모 CSV에 타자는 이름 데이터가 없어(name 컬럼 공란) 이름을 보여줄 수 없다 —
# 대신 원시 ID 나열("596019 | L | 2894구")보다 읽기 쉬운 "타자 {id}" 형태로만 표시한다.
DEMO_BATTER_CHOICES = [
    (f"타자 {int(row['id'])}", int(row["id"]))
    for _, row in _demo_players_df[_demo_players_df["role"] == "batter"].iterrows()
]


def _hand_kr(hand: str) -> str:
    return "우" if hand == "R" else "좌"


def _score_situation_label(user_score_diff: int) -> str:
    """항상 "우리팀 점수 - 상대팀 점수"(user_score_diff) 기준. 모델에 넘기는 model_score_diff와는
    부호가 다를 수 있어(타자 모드는 모델이 투수팀 기준을 쓰므로) 별도로 계산한다."""
    if user_score_diff == 0:
        return "동점"
    if abs(user_score_diff) >= 5:
        return "큰 점수차"
    if abs(user_score_diff) == 1:
        return "박빙"
    return "리드" if user_score_diff > 0 else "열세"


def _build_context(balls, strikes, outs, inning, topbot_kr, on1b, on2b, on3b, score_diff, stand: str, throws: str) -> dict:
    return {
        "balls": int(balls),
        "strikes": int(strikes),
        "outs_when_up": int(outs),
        "inning": int(inning),
        "inning_topbot_enc": 1 if topbot_kr.startswith("초") else 0,
        "on_1b": int(on1b),
        "on_2b": int(on2b),
        "on_3b": int(on3b),
        "score_diff": int(score_diff),
        "stand_enc": 1 if stand == "R" else 0,
        "p_throws_enc": 1 if throws == "R" else 0,
    }


# ============================================================================
# 위험도 카드 (JSON 대신 사람이 읽는 카드/게이지 표시)
# ============================================================================

RISK_THRESHOLDS = {
    "pattern_exposure_risk": (0.35, 0.55),
    "extra_base_hit_risk": (0.05, 0.09),
    "home_run_risk": (0.02, 0.035),
    "walk_risk": (0.35, 0.45),
}
RISK_LABELS_KR = {
    "pattern_exposure_risk": "패턴 노출 위험",
    "extra_base_hit_risk": "장타 위험",
    "home_run_risk": "홈런 위험",
    "walk_risk": "볼넷 위험",
}


def risk_level(key: str, value: float | None) -> tuple[str, str, int]:
    """(등급 낮음/보통/높음, 색상, 0~100 점수)를 반환한다. 값이 없으면 '데이터 부족'."""
    if value is None:
        return "데이터 부족", "#9e9e9e", 0
    low, high = RISK_THRESHOLDS[key]
    pct = max(0, min(100, round(value * 100)))
    if value < low:
        return "낮음", "#1f8a4c", pct
    if value < high:
        return "보통", "#b8860b", pct
    return "높음", "#c8102e", pct


def render_risk_cards(risk_summary: dict) -> str:
    cards = []
    for key, label_kr in RISK_LABELS_KR.items():
        value = risk_summary.get(key)
        level, color, pct = risk_level(key, value)
        value_text = "데이터 부족" if value is None else f"{value:.1%}"
        cards.append(f"""
        <div style="flex:1; min-width:150px; border:1px solid {color}55; border-radius:14px; padding:16px 18px; margin:4px;
                    background:#ffffff; box-shadow: 0 2px 8px rgba(20,32,60,0.06);">
          <div style="font-size:14px; color:#6b6555;">{label_kr}</div>
          <div style="font-size:22px; font-weight:800; color:{color}; margin:4px 0;">{level}</div>
          <div style="font-size:13px; color:#6b6555;">{value_text}</div>
          <div style="background:#f0ece0; border-radius:6px; height:9px; margin-top:10px;">
            <div style="background:{color}; width:{pct}%; height:9px; border-radius:6px;"></div>
          </div>
        </div>""")
    return f'<div style="display:flex; flex-wrap:wrap; gap:8px;">{"".join(cards)}</div>'


def _risk_summary_line(label_kr: str, value: float | None, key: str) -> str:
    level, _, _ = risk_level(key, value)
    if value is None:
        return f"- {label_kr}: 데이터 부족"
    return f"- {label_kr}: {level} ({value:.1%})"


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


# ============================================================================
# Markdown 리포트 + PDF
# ============================================================================

def _context_summary_lines(context: dict) -> list[str]:
    topbot = "초" if context["inning_topbot_enc"] == 1 else "말"
    runners = []
    if context["on_1b"]:
        runners.append("1루")
    if context["on_2b"]:
        runners.append("2루")
    if context["on_3b"]:
        runners.append("3루")
    runners_text = ", ".join(runners) if runners else "없음"
    stand = "우타" if context["stand_enc"] == 1 else "좌타"
    throws = "우투" if context["p_throws_enc"] == 1 else "좌투"
    return [
        f"- 카운트: {context['balls']}B-{context['strikes']}S, {context['outs_when_up']}아웃, {context['inning']}회 {topbot}",
        f"- 주자: {runners_text} / 점수차(투수팀 기준): {context['score_diff']}",
        f"- 타자 타석: {stand} / 투수 투구: {throws}",
    ]


def _situation_reasoning_lines(context: dict) -> list[str]:
    """경기 상황(볼/스트라이크/주자/점수차)이 추천에 왜 영향을 주는지 사람이 읽는 문장으로 설명한다.
    services/scouting_service.py의 _situational_danger_multipliers / _count_zone_probability_multipliers
    가 실제로 반영하는 가중치 로직을 말로 풀어쓴 것이다."""
    lines = []
    balls, strikes = context["balls"], context["strikes"]
    if balls >= 3:
        lines.append("- 3볼 상황이라 여기서 스트라이크를 놓치면 볼넷으로 이어질 수 있어, 존 안쪽 승부 비중이 높아질 가능성이 있습니다.")
    if strikes >= 2:
        lines.append("- 2스트라이크라 여유가 있어, 존 경계를 살짝 벗어나는 유인구로 헛스윙을 유도하기 좋은 카운트입니다.")
    if not (balls >= 3 or strikes >= 2):
        lines.append(f"- 현재 카운트({balls}B-{strikes}S)는 특별히 유·불리가 크지 않아, 기본 구종 성향이 비교적 그대로 반영됩니다.")
    if context["on_1b"] or context["on_2b"] or context["on_3b"]:
        lines.append("- 주자가 있어 장타 한 방의 실점 위험이 커지므로, 존 한가운데로 몰리는 공은 더 주의할 필요가 있습니다.")
    if abs(context["score_diff"]) <= 1:
        lines.append("- 점수차가 크지 않은 박빙 상황이라, 같은 위험이라도 더 보수적으로 접근하는 것이 안전할 수 있습니다.")
    return lines


_SENSITIVITY_FACTOR_KR = {
    "model_score": "모델 예측 확률", "pitcher_mix_score": "투수 구사 비율",
    "count_tendency_score": "카운트 성향", "batter_weakness_score": "상대 타자 약점/강점",
    "zone_safety_score": "구종 위험도",
}


def _sensitivity_summary_lines(result: dict) -> list[str]:
    """result["sensitivity_debug"]를 근거로 "이번 결과가 바뀐 주요 요인"을 2~3줄로 요약한다.
    수치를 새로 만들지 않고 scouting_service._build_sensitivity_debug가 이미 계산해둔
    top_factors/changed_by_context/changed_by_player/zone_variation_summary를 그대로 인용한다."""
    debug = result.get("sensitivity_debug") or {}
    top_factors = debug.get("top_factors") or []
    if not top_factors:
        return []
    top_label = _SENSITIVITY_FACTOR_KR.get(top_factors[0]["factor"], top_factors[0]["factor"])
    lines = [f"- 이번 추천에 가장 크게 작용한 요인은 **{top_label}**입니다."]
    changed_context = debug.get("changed_by_context")
    if changed_context is not None and abs(changed_context) > 0.001:
        direction = "낮추는" if changed_context < 0 else "높이는"
        lines.append(f"- 카운트·주자·점수차 등 경기 상황 보정이 이 구종 점수를 {abs(changed_context):.0%}만큼 {direction} 방향으로 조정했습니다.")
    changed_player = debug.get("changed_by_player")
    if changed_player is not None:
        lines.append(f"- 상대 타자 약점/강점 반영도가 {changed_player:.2f}만큼 최종 점수에 기여했습니다.")
    zone_range = (debug.get("zone_variation_summary") or {}).get("range")
    if zone_range is not None:
        lines.append(f"- 존별 값의 최대-최소 편차는 {zone_range:.1%}로, 상황이 바뀌면 히트맵 색상/숫자도 함께 달라집니다.")
    return lines


def _zone_hand_label(cell: int, stand: str) -> str:
    """zone_cell의 좌/중/우 열을 타자의 타석 방향(stand) 기준 몸쪽/바깥쪽/가운데로 변환한다.
    우타 기준 plate_x 음수쪽=몸쪽·양수쪽=바깥쪽, 좌타는 그 반대로 해석한다."""
    col = ZONE_COL_OF_CELL[cell]
    if col == 1:
        return "가운데"
    if stand == "R":
        return "몸쪽" if col == 0 else "바깥쪽"
    return "바깥쪽" if col == 0 else "몸쪽"


def build_markdown_report(mode: str, result: dict, meta: dict) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode_kr = "투수 모드" if mode == "pitcher" else "타자 모드"
    context = meta["context"]
    stand = meta.get("batter_stand", "R")

    lines = [
        "# ⚾ DiamondScout AI 전력분석 리포트",
        f"_생성 시간: {generated_at} · 모드: {mode_kr}_",
        "",
        f"## {meta['my_label']}",
        f"### {meta['opponent_label']}",
        "",
    ]

    lines.append("### 📋 입력 상황 요약")
    lines.extend(_context_summary_lines(context))
    if "our_score" in meta:
        lines.append(
            f"- 스코어: 우리팀 {meta['our_score']} : 상대팀 {meta['opponent_score']} "
            f"({meta['score_situation_label']}, 우리팀 기준 {meta['user_score_diff']:+d}점)"
        )

    lines.append("\n### 🎯 Top-3 예측과 근거")
    for i, item in enumerate(result["predicted_top3_pitches"], start=1):
        label = item["pitch_label"]
        lines.append(f"{i}. **{pitch_label_kr(label)}({label})** - 종합 점수 {item['probability']:.1%}")
    model_top3 = result.get("model_top3_pitches") or []
    model_top3_text = ", ".join(f"{pitch_label_kr(m['pitch_label'])}({m['pitch_label']}) {m['probability']:.1%}" for m in model_top3)
    role_text = "던졌을 때 아웃/약한 타구를 유도할 가능성이 높은 구종" if mode == "pitcher" else "실제로 들어올 가능성이 높은 구종"
    lines.append(
        f"\n이 Top-3는 모델의 다음 구종 예측 확률(참고: 모델 원 예측 Top-3는 {model_top3_text})에, "
        f"실제 구종 구사 비율(pitcher_pitch_profile), 현재 카운트별 구종 성향(count_pitch_profile), "
        + ("상대 타자의 구종별 약점/강점(batter_matchup_profile), 구종·존별 위험도(zone_risk_profile), " if mode == "pitcher" else "")
        + f"전략 코멘트 의도를 함께 반영해 재계산한 결과이며, '다음에 던질 확률'이 아니라 '{role_text}'을 "
        "기준으로 순위를 매깁니다. 실제 결과를 보장하지는 않지만 데이터상 가능성이 높은 선택입니다."
    )
    if result.get("fallback_used"):
        lines.append(f"\n> ⚠️ 데이터 표본 부족으로 일부 기본값이 사용되었습니다: {result.get('fallback_reason')}")
    lines.append("\n#### 경기 상황이 추천에 미치는 영향")
    situation_lines = _situation_reasoning_lines(context)
    lines.extend(situation_lines if situation_lines else ["- 특별히 두드러지는 상황 변수는 없습니다."])

    lines.append("\n#### 이번 결과가 바뀐 주요 요인")
    sensitivity_lines = _sensitivity_summary_lines(result)
    lines.extend(sensitivity_lines if sensitivity_lines else ["- 민감도 분석 데이터가 부족합니다."])

    if mode == "pitcher":
        pr = result["pitcher_mode_result"]
        recommended_kr = pitch_label_kr(pr["recommended_pitch"])
        lines.append(
            f"\n가장 유리할 가능성이 높은 구종은 **{recommended_kr}({pr['recommended_pitch']})**입니다. "
            "모델 예측 확률과 이 투수의 실제 구사 성향, 상대 타자 매치업, 구종별 위험도를 종합한 점수가 "
            "가장 높아, 상대를 압도하거나 약한 타구를 유도할 가능성이 큰 선택입니다."
        )
        if pr["avoid_pitch"]:
            avoid_kr = pitch_label_kr(pr["avoid_pitch"])
            lines.append(
                f"반대로 **{avoid_kr}({pr['avoid_pitch']})**는 이 투수가 실제로 던지는 구종 중 "
                "예측 확률이 가장 낮아 이번 투구에서는 피하는 편이 안전할 수 있습니다."
            )

        lines.append("\n### 🧢 이 투수의 2025 구종 비율")
        lines.append(pr["own_pitch_pattern"]["summary"])
        lines.append("실제 구종 선택도 이 비율에 가까운 경향을 보일 가능성이 높습니다.")

        lines.append("\n### 🧑‍💼 상대 타자 분석 (약점/강점)")
        lines.append(pr["batter_weakness"]["summary"])
        lines.append("다만 표본이 적은 조합에서는 이 경향이 실제와 다를 수 있어 참고용으로만 활용하는 것이 좋습니다.")

        lines.append("\n### 🎯 존 공략 전략 (왜 이 존이 안전한가)")
        danger = pr["zone_danger_scores"]
        best_cell = pr["best_zone_cell"]
        other_cells = [c for c in range(1, 10) if c != best_cell]
        avg_other = sum(danger[c] for c in other_cells) / len(other_cells) if other_cells else danger[best_cell]
        hand_label = _zone_hand_label(best_cell, stand)
        lines.append(
            f"위험 점수가 가장 낮은 존은 zone_cell {best_cell}번({hand_label}, 위험 점수 {danger[best_cell]:.2f})으로, "
            f"나머지 존 평균({avg_other:.2f})보다 낮아 상대적으로 안전한 선택일 가능성이 높습니다. "
            f"{recommended_kr}({pr['recommended_pitch']})를 이 구역 위주로 던지는 것을 추천합니다."
        )

        lines.append("\n### ⚠️ 이 선택의 리스크")
        detail = (result.get("pitch_risk_details") or {}).get(pr["recommended_pitch"])
        if detail:
            lines.append(
                f"- 그럼에도 존 안으로 몰리면 장타 확률 약 {detail['extra_base_hit_risk']:.1%}, "
                f"강한 타구(하드히트) 확률 약 {detail['hard_hit_risk']:.1%}는 감수해야 하는 리스크입니다."
            )
        if context["balls"] >= 3:
            lines.append("- 3볼 상황에서 존 밖으로 완전히 빠지면 볼넷 위험이 커지므로 스트라이크존 경계를 벗어나지 않도록 주의할 필요가 있습니다.")
    else:
        br = result["batter_mode_result"]
        top_expected = br["expected_top3_pitches"][0]
        top_kr = pitch_label_kr(top_expected["pitch_label"])
        lines.append(
            f"\n상대 투수가 다음에 던질 가능성이 가장 높은 구종은 "
            f"**{top_kr}({top_expected['pitch_label']})**입니다({top_expected['probability']:.1%})."
        )

        lines.append("\n### 🎯 상대 투수의 구종 패턴")
        lines.append(br["pitcher_pattern"]["summary"])

        lines.append("\n### 🎯 존 공략 전략 (어떤 존을 노려야 하는가)")
        prob = br["zone_probability_scores"]
        target_cell = br["target_zone_cell"]
        hand_label = _zone_hand_label(target_cell, stand)
        lines.append(
            f"{br['target_zone']} — zone_cell {target_cell}번({hand_label}, 투구 확률 {prob[target_cell]:.1%})의 "
            f"확률이 가장 높습니다. {br['counter_strategy']}"
        )

        lines.append("\n### ⚠️ 잘못 노렸을 때의 리스크")
        miss_prob = 1 - prob[target_cell]
        lines.append(
            f"- 이 존이 아닌 다른 곳으로 올 가능성도 약 {miss_prob:.0%} 존재하므로, 예상이 빗나갈 경우 "
            "무리하게 배트가 나가지 않도록 존을 벗어난 유인구는 주의할 필요가 있습니다."
        )

    lines.append("\n### 💬 코멘트 반영 내용")
    interp = result["user_comment_interpretation"]
    lines.append(f"입력 코멘트: \"{interp['raw_comment']}\"" if interp["raw_comment"] else "입력된 전략 코멘트가 없습니다.")
    lines.append(f"해석: {interp['summary']}")

    lines.append("\n### ⚠️ 종합 리스크와 주의점")
    rs = result["risk_summary"]
    lines.append(_risk_summary_line("패턴 노출 위험", rs.get("pattern_exposure_risk"), "pattern_exposure_risk"))
    lines.append(_risk_summary_line("장타 위험", rs.get("extra_base_hit_risk"), "extra_base_hit_risk"))
    lines.append(_risk_summary_line("홈런 위험", rs.get("home_run_risk"), "home_run_risk"))
    lines.append(_risk_summary_line("볼넷 위험", rs.get("walk_risk"), "walk_risk"))
    if rs.get("note"):
        lines.append(f"- 참고: {rs['note']}")

    lines.append("\n### ✅ 최종 코칭 한 줄")
    if mode == "pitcher":
        lines.append(result["pitcher_mode_result"]["coaching_message"])
    else:
        lines.append(result["batter_mode_result"]["counter_strategy"])

    return "\n".join(lines)


_EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    # matplotlib+AppleGothic 조합은 이모지 글리프가 없어 PDF에서 빈 네모(tofu box)로 깨진다.
    # PDF 섹션 제목은 이모지를 빼고 텍스트만 사용한다 (Markdown/브라우저 쪽은 이모지 그대로 유지).
    return _EMOJI_PATTERN.sub("", text).strip()


def _parse_report_sections(report_text: str) -> list[tuple[str, list[str]]]:
    """build_markdown_report()가 만든 "### 제목" 섹션들을 (제목, 본문 줄 리스트)로 되돌린다.
    PDF는 이 구조를 그대로 구분 박스로 그려서, 리포트 문구를 두 곳에 중복 작성하지 않는다."""
    sections: list[tuple[str, list[str]]] = []
    title: str | None = None
    body: list[str] = []
    for raw_line in report_text.split("\n"):
        if raw_line.startswith("### ") or raw_line.startswith("#### "):
            if title is not None:
                sections.append((title, body))
            title = _strip_emoji(raw_line.lstrip("#").strip())
            body = []
        elif raw_line.startswith("# ") or raw_line.startswith("## ") or raw_line.startswith("_생성"):
            continue  # 최상단 타이틀/생성시간/선수 라벨은 PDF 1페이지 헤더에서 별도로 그린다
        else:
            clean = raw_line.replace("**", "").strip()
            if clean:
                body.append(clean)
    if title is not None:
        sections.append((title, body))
    return sections


def build_pdf_report(mode: str, result: dict, meta: dict) -> str:
    """DiamondScout 전력분석 리포트를 A4 PDF로 렌더링한다. matplotlib PdfPages를 쓰는 이유는
    이미 AppleGothic 한글 폰트 설정이 검증되어 있어 한글 깨짐 없이 바로 재사용할 수 있어서다.
    1페이지는 헤더(제목/생성시간/모드/선수/경기상황) + Top-3 표 + 위험도 표로, 이후 페이지는
    build_markdown_report()의 각 섹션을 구분 박스로 그린다. JSON 원문은 어디에도 포함하지 않는다."""
    os.makedirs("reports", exist_ok=True)
    pitcher_id, batter_id = meta["pitcher_id"], meta["batter_id"]
    filename = f"DiamondScout_report_{mode}_{pitcher_id}_vs_{batter_id}.pdf"
    path = os.path.join("reports", filename)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode_kr = "투수 모드" if mode == "pitcher" else "타자 모드"
    sections = _parse_report_sections(build_markdown_report(mode, result, meta))

    with PdfPages(path) as pdf:
        # ---- 1페이지: 헤더 + Top-3 표 + 위험도 표 ----
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        fig.text(0.5, 0.96, "DiamondScout AI 전력분석 리포트", ha="center", fontsize=18, fontweight="bold")
        fig.text(0.5, 0.935, f"생성 시간: {generated_at}    |    모드: {mode_kr}", ha="center", fontsize=10, color="#555555")
        fig.text(0.08, 0.895, meta["my_name_line"], fontsize=12, fontweight="bold")
        fig.text(0.08, 0.872, meta["opponent_name_line"], fontsize=12, fontweight="bold")

        y = 0.835
        fig.text(0.08, y, "경기 상황", fontsize=11, fontweight="bold", color="#1d4ed8")
        y -= 0.026
        for cl in _context_summary_lines(meta["context"]):
            fig.text(0.09, y, cl.replace("- ", "• "), fontsize=9.5)
            y -= 0.023

        top3 = result["predicted_top3_pitches"]
        top3_ax = fig.add_axes((0.08, 0.565, 0.84, 0.16))
        top3_ax.axis("off")
        top3_ax.set_title("Top-3 예측 구종", fontsize=12, fontweight="bold", loc="left")
        top3_rows = [
            [str(i), f"{pitch_label_kr(item['pitch_label'])}({item['pitch_label']})", f"{item['probability']:.1%}"]
            for i, item in enumerate(top3, start=1)
        ]
        top3_table = top3_ax.table(cellText=top3_rows, colLabels=["순위", "구종", "예측 확률"], loc="center", cellLoc="center")
        top3_table.auto_set_font_size(False)
        top3_table.set_fontsize(10)
        top3_table.scale(1, 1.7)

        rs = result["risk_summary"]
        risk_rows = []
        for key, label_kr in RISK_LABELS_KR.items():
            value = rs.get(key)
            level, _, _ = risk_level(key, value)
            value_text = "데이터 부족" if value is None else f"{value:.1%}"
            risk_rows.append([label_kr, level, value_text])
        risk_ax = fig.add_axes((0.08, 0.335, 0.84, 0.16))
        risk_ax.axis("off")
        risk_ax.set_title("위험도 요약", fontsize=12, fontweight="bold", loc="left")
        risk_table = risk_ax.table(cellText=risk_rows, colLabels=["항목", "등급", "수치"], loc="center", cellLoc="center")
        risk_table.auto_set_font_size(False)
        risk_table.set_fontsize(10)
        risk_table.scale(1, 1.7)

        fig.text(0.5, 0.04, "본 리포트는 2025 시즌 데이터 기반 통계적 예측이며, 실제 경기 결과를 보장하지 않습니다.",
                 ha="center", fontsize=8, color="#999999")
        pdf.savefig(fig)
        plt.close(fig)

        # ---- 이후 페이지: 섹션별 구분 박스 ----
        y_top = 0.95
        fig = plt.figure(figsize=(8.27, 11.69))
        y = y_top
        for title, body_lines in sections:
            wrapped: list[str] = []
            for line in body_lines:
                # 한글은 영문 대비 글자 폭이 훨씬 넓어(약 2배) textwrap의 "문자 수" 기준 width를
                # 그대로 쓰면 박스 오른쪽 바깥으로 글자가 넘친다. 폭을 절반 가까이 좁게 잡는다.
                wrapped.extend(textwrap.wrap(line, width=38) or [""])
            box_height = 0.05 + 0.021 * len(wrapped)
            if y - box_height < 0.06:
                pdf.savefig(fig)
                plt.close(fig)
                fig = plt.figure(figsize=(8.27, 11.69))
                y = y_top
            box_top, box_bottom = y, y - box_height
            box = plt.Rectangle((0.06, box_bottom), 0.88, box_height, transform=fig.transFigure,
                                 facecolor="#f5f7fa", edgecolor="#d0d5dd", linewidth=1)
            fig.add_artist(box)
            fig.text(0.09, box_top - 0.026, title, fontsize=12, fontweight="bold", color="#1d4ed8")
            ty = box_top - 0.05
            for wl in wrapped:
                fig.text(0.09, ty, wl, fontsize=9.5)
                ty -= 0.021
            y = box_bottom - 0.02
        pdf.savefig(fig)
        plt.close(fig)

    return path


# ============================================================================
# 투수 모드 / 타자 모드 분석 실행
# ============================================================================

def run_pitcher_analysis(
    my_pitcher_id, opponent_batter_id, balls, strikes, outs, inning, topbot_kr,
    on1b, on2b, on3b, our_score, opponent_score, comment,
):
    pitcher_id = int(my_pitcher_id)
    batter_id = int(opponent_batter_id)

    # 좌타/우타, 좌투/우투를 사용자가 직접 고르지 않고 실제 데이터 기반으로 자동 추정한다.
    batter_stand = scouting_service.get_batter_stand(batter_id)
    pitcher_throws = scouting_service.get_pitcher_throws(pitcher_id)
    matchup_hand_text = (
        f"🧍 상대 타자 타석 방향: **{_hand_kr(batter_stand)}타({batter_stand})**"
        f"  ⚾ 내 투구 방향: **{_hand_kr(pitcher_throws)}투({pitcher_throws})** _(데이터 기반 자동 추정)_"
    )

    # 투수 모드: 우리팀 = 투수팀이므로 우리팀 기준 점수차가 곧 모델이 쓰는 "투수팀 기준" score_diff다.
    our_score, opponent_score = int(our_score), int(opponent_score)
    user_score_diff = our_score - opponent_score
    model_score_diff = user_score_diff
    score_situation_label = _score_situation_label(user_score_diff)

    context = _build_context(balls, strikes, outs, inning, topbot_kr, on1b, on2b, on3b, model_score_diff, batter_stand, pitcher_throws)
    recent_pitches = scouting_service.build_default_recent_pitches(pitcher_id)

    request = ScoutingRequest(
        mode="pitcher", pitcher_id=pitcher_id, batter_id=batter_id,
        context=context, recent_pitches=recent_pitches, user_comment=comment or "",
        stand=batter_stand, p_throws=pitcher_throws,
    )
    result = scouting_service.analyze(request)
    # Instant Scout Q&A(services/coach_agent.py)가 "지금 몇 볼-몇 스트라이크인지, 주자가 있는지, 지금
    # 내가 투수/타자 중 어느 쪽인지" 같은 맥락을 근거로 답할 수 있도록, 분석 로직 자체는 건드리지
    # 않고 결과 dict에 그대로 얹어둔다.
    result["game_context"] = context
    result["mode"] = "pitcher"
    result["our_score"], result["opponent_score"] = our_score, opponent_score
    result["user_score_diff"], result["model_score_diff"] = user_score_diff, model_score_diff
    result["score_situation_label"] = score_situation_label
    analysis_log_id = db_save_analysis_log("pitcher", pitcher_id, context, recent_pitches, comment or "", result)

    top3_html = render_top3_cards(result["predicted_top3_pitches"], "던지면 유리한 구종 Top-3 (아웃/약한 타구 유도)")
    risk_html = render_risk_cards(result["risk_summary"])

    pr = result["pitcher_mode_result"]
    recommended_text = f"{pitch_label_kr(pr['recommended_pitch'])} ({pr['recommended_pitch']})"
    avoid_text = f"{pitch_label_kr(pr['avoid_pitch'])} ({pr['avoid_pitch']})" if pr["avoid_pitch"] else "-"
    recommend_card_html = render_hero_recommend_card(
        "추천 구종", recommended_text, "예측 확률·구사 성향·매치업·위험도를 종합한 1순위 선택",
        "피해야 할 구종", avoid_text, accent="#1f8a4c",
    )
    batter_weakness_html = render_insight_card("상대 타자 약점 요약", pr["batter_weakness"]["summary"])
    # Top-3 각 구종이 실제로 가장 많이 들어간 zone_cell을 궤적 목적지로 사용(구종별 궤적 표시).
    pitcher_trajectories = [
        {"pitch_label": item["pitch_label"], "rank": i + 1,
         "cell": scouting_service.get_zone_cell_estimate(pitcher_id, item["pitch_label"])}
        for i, item in enumerate(result["predicted_top3_pitches"])
    ]
    hotcold_html = render_pitcher_zone_board(
        pr["zone_hit_risk_scores"], pr["best_zone_cell"], pr["recommended_pitch"], batter_stand, pitcher_trajectories,
    )

    meta = {
        "my_label": f"🧑‍⚾ 내 투수: {scouting_service.get_pitcher_name(pitcher_id)} (ID {pitcher_id})",
        "opponent_label": f"🎯 상대 타자: {get_batter_display(batter_id)}",
        "my_name_line": f"내 투수: {scouting_service.get_pitcher_name(pitcher_id)} (ID {pitcher_id})",
        "opponent_name_line": f"상대 타자: {get_batter_display(batter_id)}",
        "pitcher_id": pitcher_id, "batter_id": batter_id, "context": context,
        "batter_stand": batter_stand, "pitcher_throws": pitcher_throws,
        "our_score": our_score, "opponent_score": opponent_score,
        "user_score_diff": user_score_diff, "score_situation_label": score_situation_label,
        "score_team_label": "투수팀(우리팀)",
    }
    report_md = build_markdown_report("pitcher", result, meta)
    pitcher_state = {"mode": "pitcher", "result": result, "meta": meta, "analysis_log_id": analysis_log_id}
    status_html = render_analysis_status(done=True)

    return (
        matchup_hand_text, top3_html, risk_html, recommend_card_html, batter_weakness_html,
        hotcold_html, report_md, pitcher_state, status_html,
    )


def run_batter_analysis(
    my_batter_id, opponent_pitcher_id, balls, strikes, outs, inning, topbot_kr,
    on1b, on2b, on3b, our_score, opponent_score, comment,
):
    pitcher_id = int(opponent_pitcher_id)
    batter_id = int(my_batter_id)

    my_stand = scouting_service.get_batter_stand(batter_id)
    opponent_throws = scouting_service.get_pitcher_throws(pitcher_id)
    matchup_hand_text = (
        f"🧍 내 타석 방향: **{_hand_kr(my_stand)}타({my_stand})**"
        f"  ⚾ 상대 투수 투구 방향: **{_hand_kr(opponent_throws)}투({opponent_throws})** _(데이터 기반 자동 추정)_"
    )

    # 타자 모드: 우리팀 = 타자팀. 모델 context의 score_diff는 "투수팀(=상대팀) 기준"이므로 부호를
    # 반전해서 넘긴다. 사용자에게 보여줄 때는 항상 우리팀 기준(user_score_diff)을 쓴다.
    our_score, opponent_score = int(our_score), int(opponent_score)
    user_score_diff = our_score - opponent_score
    model_score_diff = opponent_score - our_score
    score_situation_label = _score_situation_label(user_score_diff)

    context = _build_context(balls, strikes, outs, inning, topbot_kr, on1b, on2b, on3b, model_score_diff, my_stand, opponent_throws)
    recent_pitches = scouting_service.build_default_recent_pitches(pitcher_id)

    request = ScoutingRequest(
        mode="batter", pitcher_id=pitcher_id, batter_id=batter_id,
        context=context, recent_pitches=recent_pitches, user_comment=comment or "",
        stand=my_stand, p_throws=opponent_throws,
    )
    result = scouting_service.analyze(request)
    result["game_context"] = context
    result["mode"] = "batter"
    result["our_score"], result["opponent_score"] = our_score, opponent_score
    result["user_score_diff"], result["model_score_diff"] = user_score_diff, model_score_diff
    result["score_situation_label"] = score_situation_label
    analysis_log_id = db_save_analysis_log("batter", pitcher_id, context, recent_pitches, comment or "", result)

    top3_html = render_top3_cards(result["predicted_top3_pitches"], "상대 투수가 던질 가능성이 높은 구종 Top-3")
    risk_html = render_risk_cards(result["risk_summary"])

    br = result["batter_mode_result"]
    recommend_card_html = render_hero_recommend_card(
        "노릴 코스", br["target_zone"], "예상 투구 확률·상대 패턴·전략 코멘트를 종합한 최우선 코스",
        "대응 전략", br["counter_strategy"], accent="#1f8a4c",
    )
    pitcher_pattern_html = render_insight_card("상대 투수 패턴 요약", br["pitcher_pattern"]["summary"])
    batter_trajectories = [
        {"pitch_label": loc["pitch_label"], "rank": i + 1, "cell": loc["zone_cell"]}
        for i, loc in enumerate(br["expected_locations"])
    ]
    hotcold_html = render_batter_zone_board(
        br["zone_probability_scores"], br["target_zone_cell"], my_stand, batter_trajectories,
    )

    meta = {
        "my_label": f"🏏 내 타자: {get_batter_display(batter_id)}",
        "opponent_label": f"🎯 상대 투수: {scouting_service.get_pitcher_name(pitcher_id)} (ID {pitcher_id})",
        "my_name_line": f"내 타자: {get_batter_display(batter_id)}",
        "opponent_name_line": f"상대 투수: {scouting_service.get_pitcher_name(pitcher_id)} (ID {pitcher_id})",
        "pitcher_id": pitcher_id, "batter_id": batter_id, "context": context,
        "batter_stand": my_stand, "pitcher_throws": opponent_throws,
        "our_score": our_score, "opponent_score": opponent_score,
        "user_score_diff": user_score_diff, "score_situation_label": score_situation_label,
        "score_team_label": "타자팀(우리팀)",
    }
    report_md = build_markdown_report("batter", result, meta)
    batter_state = {"mode": "batter", "result": result, "meta": meta, "analysis_log_id": analysis_log_id}
    status_html = render_analysis_status(done=True)

    return (
        matchup_hand_text, top3_html, risk_html, recommend_card_html, pitcher_pattern_html,
        hotcold_html, report_md, batter_state, status_html,
    )


def generate_pdf(state: dict | None):
    if not state:
        raise gr.Error("먼저 분석을 실행해주세요.")
    path = build_pdf_report(state["mode"], state["result"], state["meta"])
    return path


# ============================================================================
# Instant Scout Q&A (각 모드 탭 안에서 그 모드의 최신 분석 결과를 바로 참조)
# ============================================================================

def _minimal_chat_fallback(last_result: dict | None) -> str:
    """Instant Scout 답변 생성이 (coach_agent 내부 안전망을 뚫고) 완전히 실패했을 때도, 빈
    에러 메시지 대신 지금 가진 분석 결과만으로 만들 수 있는 최소한의 답변을 반환한다."""
    if not last_result:
        return "지금은 답변 생성에 문제가 있었어. 분석을 다시 실행한 뒤 다시 물어봐줘."
    pitcher_result = last_result.get("pitcher_mode_result")
    if pitcher_result and pitcher_result.get("recommended_pitch"):
        recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
        return f"지금은 질문을 정확히 처리하지 못했는데, 현재 추천 구종은 {recommended_kr}이야. 질문을 조금 다르게 다시 물어봐줘."
    batter_result = last_result.get("batter_mode_result")
    if batter_result and batter_result.get("target_zone"):
        return f"지금은 질문을 정확히 처리하지 못했는데, 현재 노릴 코스는 {batter_result['target_zone']}야. 질문을 조금 다르게 다시 물어봐줘."
    return "지금은 답변 생성에 문제가 있었어. 질문을 조금 다르게 다시 물어봐줘."


def handle_chat(message, history, state: dict | None):
    """RAG로 컨텍스트를 찾고 LLMScout으로 답한다. RAG/LLM 어느 단계가 실패해도 예외를
    흡수해 채팅만 안내 메시지로 대체하고 앱은 죽지 않는다."""
    history = history or []
    if not message or not message.strip():
        return history, ""

    context_chunks: list[str] = []
    answer_source = "no_analysis"
    last_result = state["result"] if state else None
    last_analysis_log_id = state.get("analysis_log_id") if state else None

    if last_result is None:
        answer = "먼저 왼쪽에서 분석을 실행한 뒤 질문해주세요."
    else:
        try:
            if rag_service is not None:
                rag_service.build_index(last_result)
                context_chunks = rag_service.retrieve(message, k=3)
        except Exception as exc:  # noqa: BLE001
            print(f"[경고] RAG 검색 실패, 컨텍스트 없이 진행합니다: {exc}")
            context_chunks = []

        try:
            if coach_agent is not None:
                # history(이전 대화)를 함께 넘겨 CoachAgent가 대화 상태/반복 감지에 쓰게 한다.
                # CoachAgent.answer 내부에도 자체 try/except(Ollama 실패 시 evidence 기반
                # fallback)가 있지만, RAG 결합·예상 밖 state 구조 등 그 바깥에서 터질 수 있는
                # 예외까지 대비해 이 레벨에서도 한 번 더 방어한다.
                answer_info = coach_agent.answer(message, history, last_result)
                answer = answer_info["answer"]
                answer_source = answer_info["source"]
                # intent/focus는 화면에 노출하지 않고 서버 로그에만 남겨 개발 확인용으로 쓴다.
                print(f"[Q&A] intent={answer_info.get('intent')} focus={answer_info.get('focus')}")
            else:
                answer = "Instant Scout Q&A를 사용할 수 없습니다 (LLM/RAG 초기화 실패)."
                answer_source = "unavailable"
        except Exception as exc:  # noqa: BLE001
            print(f"[경고] Instant Scout 답변 생성 실패: {exc}")
            answer = _minimal_chat_fallback(last_result)
            answer_source = "error"

    db_save_qa_log(message, answer, answer_source, context_chunks, last_analysis_log_id)

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]
    return history, ""


# ============================================================================
# 라이트 스포츠 브로드캐스트 테마 CSS
# ============================================================================

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Teko:wght@500;600;700&family=Share+Tech+Mono&display=swap');

:root {
    color-scheme: light;
}
.gradio-container {
    background: #f4f2ec !important;
    max-width: 1320px !important;
    margin: 0 auto !important;
    font-size: 17px !important;
    color-scheme: light;
    /* Gradio 6 내부 컴포넌트(슬라이더/드롭다운 등)가 라이트 팔레트를 그대로 쓰도록
       변수 레벨에서 고정한다. .ds-* 클래스만으로는 내부 컴포넌트가 예전 다크 변수값을
       참조해 라이트/다크가 뒤섞여 보이는 문제가 있었다 (2026-08-03 스펙에서 겪은 문제의
       재발 방지). */
    --body-background-fill: #f4f2ec !important;
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #f7f5ef !important;
    --border-color-primary: #e6e1d3 !important;
    --border-color-accent: #c8102e !important;
    --block-background-fill: #ffffff !important;
    --block-border-color: #e6e1d3 !important;
    --block-label-background-fill: #ffffff !important;
    --block-label-text-color: #6b6555 !important;
    --body-text-color: #14203c !important;
    --body-text-color-subdued: #6b6555 !important;
    --input-background-fill: #f7f5ef !important;
    --checkbox-background-color: #f7f5ef !important;
    --checkbox-background-color-selected: #c8102e !important;
    --neutral-950: #14203c !important;
}
.gradio-container, .gradio-container p, .gradio-container span, .gradio-container label {
    color: #14203c;
}
.gradio-container h1, .gradio-container h2, .gradio-container h3, .gradio-container h4,
.gradio-container button, .ds-panel-title, .ds-board-title, .ds-qa-title, .ds-step-dot {
    font-family: 'Teko', 'Pretendard', sans-serif !important;
    letter-spacing: 0.02em;
}
.gradio-container input,
.gradio-container textarea,
.gradio-container select {
    background: #f7f5ef !important;
    color: #14203c !important;
}
.gradio-container h1 { color: #14203c; font-size: 34px !important; margin-bottom: 6px !important; }
.gradio-container h2 { color: #14203c; font-size: 25px !important; }
.gradio-container h3, .gradio-container h4 {
    color: #14203c; font-size: 21px !important; margin-top: 26px !important; margin-bottom: 12px !important;
}
/* 입력 영역 = 경기 설정 패널 / 결과 영역 = 코칭 보드 / Q&A 패널 공통 카드 스타일 */
.ds-panel, .ds-board, .ds-qa-panel {
    border-radius: 16px !important;
    padding: 24px 26px !important;
    margin: 20px 0 !important;
    background: #ffffff !important;
    border: 1px solid #e6e1d3 !important;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-panel-title, .ds-board-title, .ds-qa-title {
    font-weight: 800; letter-spacing: 0.03em; font-size: 20px; padding: 2px 0 14px 12px;
    margin: 0 !important; border-left: 4px solid;
}
.ds-panel-title { color: #c8102e; border-color: #c8102e; }
.ds-board-title { color: #14203c; border-color: #14203c; }
.ds-qa-title { color: #14203c; border-color: #c8102e; }
/* 볼/스트라이크/아웃 스코어보드 */
.ds-scoreboard {
    background: #f7f5ef !important;
    border: 1px solid #e6e1d3 !important;
    border-radius: 12px !important;
    padding: 14px 10px !important;
    margin: 6px 0 16px 0 !important;
}
.ds-scoreboard input[type=range] { accent-color: #c8102e; }
.ds-scoreboard input[type=number] { font-family: 'Share Tech Mono', monospace !important; }
/* 주자 베이스 카드 */
/* ===== 주자 상황 다이아몬드 — 체크박스를 실제 루 위치에 맞춰 배치하고 베이스 모양으로 스타일링 ===== */
.ds-diamond-wrap { justify-content: center !important; padding: 6px 0 26px !important; }
.ds-diamond { position: relative !important; width: 240px; height: 200px; margin: 0 auto; }
.ds-diamond::after {
    content: "HOME"; position: absolute; bottom: -8px; left: 50%; transform: translateX(-50%);
    font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #9a927c; letter-spacing: 0.08em;
}
.ds-base-card {
    position: absolute !important; width: 96px !important; background: transparent !important;
    border: none !important; padding: 0 !important; box-shadow: none !important;
}
.ds-base-card.ds-base-2b { top: 0; left: 50%; transform: translateX(-50%); }
.ds-base-card.ds-base-3b { bottom: 34px; left: 0; }
.ds-base-card.ds-base-1b { bottom: 34px; right: 0; }
.ds-base-card label {
    display: flex !important; flex-direction: column-reverse !important; align-items: center !important; gap: 8px;
    cursor: pointer;
}
.ds-base-card label span { font-size: 14px !important; font-weight: 700; color: #6b6555; }
.ds-base-card input[type=checkbox] {
    appearance: none; -webkit-appearance: none; width: 44px !important; height: 44px !important; margin: 0 !important;
    background: #f7f5ef; border: 2.5px solid #ddd8ca; border-radius: 6px; transform: rotate(45deg);
    cursor: pointer; transition: all 0.15s ease;
}
.ds-base-card input[type=checkbox]:hover { border-color: #c8102e; }
.ds-base-card input[type=checkbox]:checked {
    background: #c8102e !important; border-color: #c8102e !important; box-shadow: 0 0 0 6px rgba(200,16,46,0.15);
}
.ds-base-card:has(input:checked) label span { color: #c8102e; }
/* 버튼: Primary(레드)/Ghost(아웃라인) 2종만 사용 */
.gradio-container button { font-size: 16.5px !important; border-radius: 8px !important; }
.ds-btn-analyze {
    background: #c8102e !important; color: #ffffff !important; border: none !important;
    font-weight: 800 !important; box-shadow: 0 4px 10px rgba(200,16,46,0.28) !important;
}
.ds-btn-analyze:hover { box-shadow: 0 6px 16px rgba(200,16,46,0.4) !important; transform: translateY(-1px); }
/* "다음" 버튼은 "분석 실행"(레드)과 시각적으로 구분되도록 네이비로 분리 */
.ds-btn-next {
    background: #14203c !important; color: #ffffff !important; border: none !important;
    font-weight: 800 !important; box-shadow: 0 4px 10px rgba(20,32,60,0.28) !important;
}
.ds-btn-next:hover { box-shadow: 0 6px 16px rgba(20,32,60,0.4) !important; transform: translateY(-1px); }
.ds-btn-prev, .ds-btn-reset {
    background: transparent !important; color: #6b6555 !important; border: 1.5px solid #ddd8ca !important;
    box-shadow: none !important; font-weight: 700 !important;
}
.ds-btn-prev:hover, .ds-btn-reset:hover { border-color: #14203c !important; color: #14203c !important; }
.ds-btn-reset { margin-bottom: 10px !important; }
/* 이전/다음/분석 실행 버튼은 한 줄(Row)에 나란히 놓이므로 높이를 강제로 맞춘다.
   .ds-btn-analyze는 Gradio variant="primary" 기본 패딩이 달라 그대로 두면 더 커 보였다. */
.ds-btn-prev, .ds-btn-next, .ds-btn-analyze {
    padding: 12px 18px !important; min-height: 46px !important; box-sizing: border-box !important;
    margin-top: 0 !important;
}
.ds-btn-pdf {
    background: transparent !important; color: #14203c !important; border: 1.5px solid #14203c !important;
    font-size: 15px !important; padding: 11px !important; font-weight: 700 !important; box-shadow: none !important;
}
.ds-btn-pdf:hover { background: #14203c !important; color: #ffffff !important; }
/* Gradio가 버튼을 감싸는 .styler 래퍼에 자체 배경(#e6e1d3)을 깔아서, 버튼 자체를
   transparent로 둬도 뒤에서 베이지색이 비쳐 보였다. 래퍼 배경을 투명화해 카드(.ds-board)의
   흰 배경이 그대로 보이게 한다. (Gradio 6.19.0 기준, 버전 업그레이드 시 DOM 구조 변경 여부 재확인 필요) */
.styler:has(> .ds-btn-pdf) { background: transparent !important; }
/* 입력 컴포넌트 라벨/텍스트 가독성 */
.gradio-container label span, .gradio-container .label-wrap span { font-size: 16.5px !important; }
/* STRIKE ZONE BOARD 카드 (내부 SVG 히트맵 자체 색상은 별도 보정) */
.ds-zone-card {
    background: #ffffff;
    border: 1px solid #e6e1d3; border-radius: 16px; padding: 18px 20px 14px;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-zone-header { text-align: center; letter-spacing: 0.06em; font-weight: 800; }
.ds-zone-header-en { color: #c8102e; font-size: 20px; }
.ds-zone-header-sep { color: #b8ae94; margin: 0 10px; font-weight: 400; }
.ds-zone-header-kr { color: #14203c; font-size: 18px; }
.ds-zone-badge {
    background: rgba(200,16,46,0.08); color: #c8102e; border: 1px solid rgba(200,16,46,0.3);
    border-radius: 999px; font-size: 11px; padding: 3px 10px; margin-left: 10px; letter-spacing: 0.05em;
}
.ds-zone-sub { text-align: center; color: #6b6555; font-size: 13.5px; margin-top: 4px; }
.ds-zone-svg { width: 100%; height: auto; display: block; margin-top: 6px; }
.ds-zone-footer {
    display: flex; align-items: center; justify-content: space-between; color: #6b6555;
    font-size: 13px; margin-top: 4px; gap: 10px;
}
.ds-zone-legend { display: flex; align-items: center; gap: 8px; }
.ds-zone-legend-pill {
    width: 70px; height: 8px; border-radius: 999px;
    background: linear-gradient(90deg, rgb(8,145,178), rgb(225,29,72));
}
.ds-zone-legend-label { font-size: 11px; color: #9a927c; }
.ds-zone-caption { text-align: center; color: #14203c; font-weight: 700; font-size: 15px; margin-top: 10px; }
/* 분석 완료/진행 상태 표시 */
.ds-status {
    text-align: center; font-weight: 700; font-size: 14.5px; padding: 10px 14px;
    border-radius: 10px; margin: 6px 0 14px 0;
}
.ds-status-done { background: rgba(31,138,76,0.08); color: #1f8a4c; border: 1px solid rgba(31,138,76,0.3); }
.ds-status-pending { background: rgba(184,134,11,0.08); color: #8a6d00; border: 1px solid rgba(184,134,11,0.3); }

/* ===== 위저드 카드 ===== */
.ds-wizard-card { position: relative; }
.ds-wizard-card[style*="display: none"] {
    display: none !important; height: 0 !important; min-height: 0 !important;
    padding: 0 !important; margin: 0 !important; border: none !important; overflow: hidden !important;
}
/* 스텝 전환 애니메이션 — Gradio가 비활성 스텝에 인라인 style="display: none"을 걸었다가
   빼는 방식으로 전환하므로, display:none에서 벗어날 때마다 애니메이션이 처음부터 다시
   재생된다(별도 JS 트리거 불필요). */
.ds-wizard-card:not([style*="display: none"]) {
    animation: ds-step-in 0.32s ease;
}
@keyframes ds-step-in {
    from { opacity: 0; transform: translateX(14px); }
    to { opacity: 1; transform: translateX(0); }
}
@media (prefers-reduced-motion: reduce) {
    .ds-wizard-card { animation: none !important; }
}
/* 스텝 전환은 위쪽 진행 트랙으로만 하므로 gr.Tabs 기본 헤더는 숨긴다
   (Gradio 6.19.0 기준, 버전 업그레이드 시 DOM 구조 변경 여부 재확인 필요) */
.ds-wizard-tabs > .tab-wrapper { display: none !important; }

/* ===== 위저드 진행 트랙 (완료=레드 밑줄 / 현재=네이비 강조 / 예정=연한 회색) ===== */
.ds-wizard-progress { gap: 4px !important; margin: 4px 0 22px 0 !important; flex-wrap: nowrap !important; }
.ds-step-dot {
    flex: 1; border-radius: 8px 8px 0 0 !important; border: none !important;
    border-bottom: 3px solid #ddd8ca !important; background: transparent !important; box-shadow: none !important;
    color: #b8ae94 !important; font-weight: 700 !important; padding: 10px 6px !important; font-size: 13.5px !important;
}
.ds-step-dot:hover { color: #14203c !important; }
.ds-step-done { border-bottom-color: #c8102e !important; color: #c8102e !important; }
/* 색상만으로 완료 상태를 구분하면 색각 이상 사용자가 인지하기 어려우므로 체크마크를 덧붙인다 */
.ds-step-done::after { content: " \\2713"; }
.ds-step-now {
    border-bottom-color: #14203c !important; color: #14203c !important;
    background: #f7f5ef !important; border-radius: 8px 8px 0 0 !important;
}
.ds-step-next { border-bottom-color: #ddd8ca !important; color: #b8ae94 !important; }

/* ===== 현재 매치업 요약 패널 (데스크톱 전용) — 이름만 크게 보여준다 ===== */
.ds-matchup-panel {
    display: none;
    background: #14203c !important; color: #ffffff !important;
    border-radius: 16px !important; padding: 26px !important;
    flex-direction: column; justify-content: center; align-items: center; text-align: center;
}
.ds-matchup-panel .ds-mp-title {
    font-size: 13px; font-weight: 700; letter-spacing: 0.08em; color: #b9c3dd; text-transform: uppercase;
    border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 12px; margin-bottom: 16px; width: 100%;
}
.ds-matchup-panel .ds-mp-role {
    font-size: 13px; font-weight: 700; letter-spacing: 0.06em; color: #b9c3dd; text-transform: uppercase; margin-top: 16px;
}
.ds-matchup-panel .ds-mp-name { font-size: 25px; font-weight: 800; color: #ffffff; margin-top: 4px; }
.ds-matchup-panel .ds-mp-vs {
    color: #c8102e; font-weight: 800; font-size: 15px; letter-spacing: 0.1em; margin: 18px 0 2px;
}

/* ===== 결과 화면 벤토 그리드 ===== */
.ds-bento { display: grid !important; grid-template-columns: 1fr 1fr; gap: 14px; margin: 10px 0; }
.ds-bento-wide { grid-column: 1 / -1 !important; }

/* ===== 카운트/이닝 시각화 스코어보드 (STEP 2, 원시 입력값을 읽기 쉽게 재표시) ===== */
.ds-count-board {
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
    background: #14203c; border-radius: 12px; padding: 14px 18px; margin: 8px 0 16px 0;
}
.ds-cb-item { display: flex; align-items: center; gap: 6px; }
.ds-cb-label { font-family: 'Share Tech Mono', monospace; color: #b9c3dd; font-weight: 700; font-size: 14px; margin-right: 2px; }
.ds-cb-dot { width: 16px; height: 16px; border-radius: 50%; background: rgba(255,255,255,0.15); display: inline-block; }
.ds-cb-dot.on { background: var(--c); }
.ds-cb-inning {
    margin-left: auto; font-family: 'Share Tech Mono', monospace; color: #ffffff; font-weight: 800; font-size: 17px;
}

/* ===== 반응형 브레이크포인트 ===== */
@media (min-width: 1280px) {
    .ds-matchup-panel { display: flex; }
    .ds-wizard-row { align-items: stretch !important; }
    .ds-bento { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 639px) {
    /* flex:1 인 버튼은 기본 min-width:auto 때문에 텍스트 폭 밑으로 줄어들지 않아, 4개를 한 줄에
       나눠 담을 좁은 화면에서 뒤쪽 스텝(3/4)이 트랙 밖으로 밀려나 보이지 않는 문제가 있었다.
       min-width:0으로 강제 축소를 허용하고, 넘치는 텍스트는 말줄임표로 처리한다. */
    .ds-step-dot {
        font-size: 11.5px !important; padding: 8px 3px !important; letter-spacing: -0.01em !important;
        min-width: 0 !important; overflow: hidden !important; text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }
    .ds-panel, .ds-board, .ds-qa-panel { padding: 16px 14px !important; }
}

/* ===== 좌우 여백(카드 폭 밖) 장식 배경 — 야구 실밥 느낌의 대각선 패턴 + 은은한 포인트 컬러 ===== */
body {
    background:
        radial-gradient(circle at 4% 15%, rgba(200,16,46,0.06) 0%, transparent 42%),
        radial-gradient(circle at 96% 80%, rgba(20,32,60,0.07) 0%, transparent 42%),
        repeating-linear-gradient(135deg, rgba(20,32,60,0.035) 0px, rgba(20,32,60,0.035) 2px, transparent 2px, transparent 26px),
        #f4f2ec !important;
}

/* ===== 랜딩 화면 ===== */
.ds-landing-hero { text-align: center; padding: 34px 20px 10px; }
.ds-landing-badge {
    display: inline-block; background: rgba(200,16,46,0.08); color: #c8102e; border: 1px solid rgba(200,16,46,0.3);
    border-radius: 999px; font-size: 13px; font-weight: 700; padding: 5px 14px; letter-spacing: 0.05em;
}
.ds-landing-title { font-size: 40px; font-weight: 800; color: #14203c; margin: 14px 0 8px; }
.ds-landing-sub { font-size: 18px; color: #4b463c; max-width: 620px; margin: 0 auto; line-height: 1.6; }
.ds-landing-features { gap: 16px !important; margin: 24px 0 !important; }
.ds-landing-feature {
    background: #ffffff; border: 1px solid #e6e1d3; border-radius: 14px; padding: 22px 20px; height: 100%;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-lf-title { font-family: 'Teko', sans-serif; font-size: 21px; font-weight: 800; color: #c8102e; margin-bottom: 8px; }
.ds-lf-desc { font-size: 15px; color: #4b463c; line-height: 1.5; }
.ds-landing-start { display: block !important; margin: 8px auto 30px !important; min-width: 220px; font-size: 19px !important; }
"""


# ============================================================================
# 카드형 결과 표시 (Top-3 랭킹 카드 / 히어로 추천 카드 / 인사이트 카드)
# ============================================================================

def render_top3_cards(top3: list[dict], title: str) -> str:
    """예측 확률 Top-3를 단순 라벨 대신 순위 카드(금/은/동 + 확률 바)로 보여준다."""
    medal_colors = ["#c8102e", "#8a8375", "#b8860b"]
    rows = []
    max_prob = max((item["probability"] for item in top3), default=1.0) or 1.0
    for i, item in enumerate(top3[:3]):
        kr = pitch_label_kr(item["pitch_label"])
        pct = item["probability"]
        bar_width = round(100 * pct / max_prob)
        color = medal_colors[i] if i < len(medal_colors) else "#6b6555"
        rows.append(f"""
        <div style="display:flex; align-items:center; gap:14px; margin:12px 0;">
          <div style="width:32px; height:32px; border-radius:50%; background:{color}; color:#ffffff; font-size:15px;
                      font-weight:800; display:flex; align-items:center; justify-content:center; flex-shrink:0;">{i + 1}</div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; font-size:16px;">
              <span style="font-weight:700; color:#14203c;">{kr} ({item['pitch_label']})</span>
              <span style="color:{color}; font-weight:700;">{pct:.1%}</span>
            </div>
            <div style="background:#f0ece0; border-radius:6px; height:10px; margin-top:6px;">
              <div style="background:{color}; width:{bar_width}%; height:10px; border-radius:6px;"></div>
            </div>
          </div>
        </div>""")
    return f"""
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#6b6555; margin-bottom:10px;">{title}</div>
      {"".join(rows)}
    </div>"""


def render_hero_recommend_card(
    hero_label: str, hero_value: str, hero_note: str, secondary_label: str, secondary_value: str, accent: str = "#1f8a4c",
) -> str:
    """가장 중요한 추천 결과(추천 구종 또는 노릴 코스)를 큰 히어로 카드로, 나머지(피해야 할 구종/대응
    전략)는 아래 보조 카드로 보여준다."""
    return f"""
    <div style="background:linear-gradient(135deg, {accent}1a 0%, #ffffff 70%); border:1.5px solid {accent};
                border-radius:16px; padding:22px 24px;">
      <div style="font-size:15px; color:#6b6555;">{hero_label}</div>
      <div style="font-size:28px; font-weight:900; color:{accent}; margin:8px 0;">{hero_value}</div>
      <div style="font-size:14px; color:#4b463c;">{hero_note}</div>
    </div>
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:16px 20px; margin-top:14px;">
      <div style="font-size:15px; color:#6b6555;">{secondary_label}</div>
      <div style="font-size:16px; color:#14203c; font-weight:600; margin-top:4px;">{secondary_value}</div>
    </div>"""


def render_insight_card(title: str, text: str) -> str:
    return f"""
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#6b6555; margin-bottom:6px;">{title}</div>
      <div style="font-size:16px; color:#14203c; line-height:1.6;">{text}</div>
    </div>"""


def render_analysis_status(done: bool) -> str:
    """분석 실행 버튼을 눌렀을 때 "분석 중..."(done=False) -> "분석 완료"(done=True) 상태를
    명확히 보여준다. 완료 시각을 함께 표시해 같은 문구를 다시 눌러도 갱신됐음을 알 수 있게 한다."""
    if not done:
        return '<div class="ds-status ds-status-pending">⏳ 분석 중입니다...</div>'
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f'<div class="ds-status ds-status-done">✅ 분석 완료 — 코칭 보드가 갱신되었습니다 · 마지막 분석 시간 {timestamp}</div>'


def _render_matchup_panel(my_label: str, my_name: str, opponent_label: str, opponent_name: str) -> str:
    """데스크톱(≥1280px) 2단 레이아웃 우측에 상시 노출되는 "현재 매치업" 패널.
    누가 누구와 붙는지만 크게 보여주는 용도라 이름만 표시한다 — 카운트/이닝은
    STEP 2의 시각화 스코어보드(render_count_scoreboard)에서 이미 보여주므로 중복하지 않는다.
    모바일/태블릿에서는 .ds-matchup-panel이 display:none이라 이 패널 자체가 안 보이므로,
    좁은 화면에서는 STEP 1로 돌아가야 매치업을 다시 확인할 수 있다."""
    return f"""
    <div class="ds-mp-title">현재 매치업</div>
    <div class="ds-mp-role">{my_label}</div>
    <div class="ds-mp-name">{my_name}</div>
    <div class="ds-mp-vs">VS</div>
    <div class="ds-mp-role">{opponent_label}</div>
    <div class="ds-mp-name">{opponent_name}</div>
    """


def render_pitcher_matchup_summary(pitcher_id, batter_id) -> str:
    """pitcher_id/batter_id는 .change() 와이어링에서 gr.Dropdown(choices=(label, id) 튜플)이
    실제로 넘겨주는 id 값이므로, 표시용 이름으로 변환해서 렌더링한다."""
    return _render_matchup_panel(
        "내 투수", scouting_service.get_pitcher_name(pitcher_id),
        "상대 타자", get_batter_display(batter_id),
    )


def render_batter_matchup_summary(batter_id, pitcher_id) -> str:
    return _render_matchup_panel(
        "내 타자", get_batter_display(batter_id),
        "상대 투수", scouting_service.get_pitcher_name(pitcher_id),
    )


def render_count_scoreboard(balls, strikes, outs, inning, topbot) -> str:
    """STEP 2의 슬라이더/숫자 입력값을 게임 스코어보드처럼 한눈에 보이게 재표시한다.
    원시 입력 컴포넌트(gr.Slider 등)는 그대로 두고, 그 값을 읽어 시각화만 추가하는 방식이라
    실제 분석에 쓰이는 값(=원시 입력값)과 화면에 보이는 값이 항상 일치한다."""
    def _dots(n: int, total: int, color: str) -> str:
        n = int(n)
        return "".join(
            f'<span class="ds-cb-dot{" on" if i < n else ""}" style="--c:{color}"></span>'
            for i in range(total)
        )
    inning_display = inning if inning is not None else "-"
    topbot_short = "초" if "초" in topbot else "말"
    return f"""
    <div class="ds-count-board">
      <div class="ds-cb-item"><span class="ds-cb-label">B</span>{_dots(balls, 3, '#1f8a4c')}</div>
      <div class="ds-cb-item"><span class="ds-cb-label">S</span>{_dots(strikes, 2, '#b8860b')}</div>
      <div class="ds-cb-item"><span class="ds-cb-label">O</span>{_dots(outs, 2, '#c8102e')}</div>
      <div class="ds-cb-inning">{inning_display}회 {topbot_short}</div>
    </div>
    """


# ============================================================================
# Gradio 레이아웃
# ============================================================================

WIZARD_STEP_LABELS = ["STEP 1 매치업", "STEP 2 상황판", "STEP 3 베이스&스코어", "STEP 4 작전지시"]


def _step_dot_classes(step: int) -> list[list[str]]:
    """1~4번 스텝 진행 트랙 버튼에 완료(레드)/현재(네이비)/예정(연한 회색) 상태 클래스를 계산한다."""
    classes = []
    for i in range(1, 5):
        if i < step:
            classes.append(["ds-step-dot", "ds-step-done"])
        elif i == step:
            classes.append(["ds-step-dot", "ds-step-now"])
        else:
            classes.append(["ds-step-dot", "ds-step-next"])
    return classes


def _step_dot_updates(step: int):
    c = _step_dot_classes(step)
    return (
        gr.Button(elem_classes=c[0]), gr.Button(elem_classes=c[1]),
        gr.Button(elem_classes=c[2]), gr.Button(elem_classes=c[3]),
    )


def _goto_step_1():
    return (gr.Tabs(selected=0), 1, *_step_dot_updates(1))


def _chip_goto(target: int, current_step) -> tuple:
    """진행 트랙 칩은 이미 지나왔거나 현재 스텝으로는 자유롭게 이동할 수 있지만, 아직
    도달하지 않은(예정) 스텝으로는 건너뛸 수 없다 — 내용을 채우지 않고 앞 스텝으로
    건너뛰는 것을 막기 위해 '다음' 버튼을 눌러야만 전진하도록 강제한다."""
    current = int(current_step)
    step = target if target <= current else current
    return (gr.Tabs(selected=step - 1), step, *_step_dot_updates(step))


def _goto_step_2(current_step):
    return _chip_goto(2, current_step)


def _goto_step_3(current_step):
    return _chip_goto(3, current_step)


def _goto_step_4(current_step):
    return _chip_goto(4, current_step)


def _step_prev(current_step: int):
    """다음/이전 버튼은 gr.Tabs(selected=)로 카드 하나를 전환한다.
    Column 4개를 visible= 로 각각 토글하는 방식은 두 번째 전환부터 간헐적으로
    갱신이 반영되지 않는 문제가 있어 (스텝2->3, 3->4에서 재현), Gradio가 이런
    스텝형 전환을 위해 제공하는 gr.Tabs(selected=) 방식으로 바꿨다."""
    target = max(1, int(current_step) - 1)
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target))


def _step_next(current_step: int):
    target = min(4, int(current_step) + 1)
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target))


with gr.Blocks(title="DiamondScout AI", css=CUSTOM_CSS) as demo:
    gr.Markdown("# ⚾ DiamondScout AI")
    gr.Markdown("투수 모드 / 타자 모드로 나눠, 다음 구종 예측(RandomForest) + 위험도 + 상대 분석 + Q&A를 한 화면에서 확인하는 전력분석 데모")

    with gr.Column(elem_classes=["ds-landing"], visible=True) as landing_view:
        gr.HTML("""
        <div class="ds-landing-hero">
          <div class="ds-landing-badge">전력분석 데모</div>
          <h2 class="ds-landing-title">다음 투구를 미리 읽는다</h2>
          <p class="ds-landing-sub">투수·타자 관점에서 다음 구종을 예측하고, 위험도와 상대 약점을 코칭 보드로 정리해드립니다.</p>
        </div>
        """)
        with gr.Row(elem_classes=["ds-landing-features"]):
            gr.HTML(
                '<div class="ds-landing-feature"><div class="ds-lf-title">다음 구종 예측</div>'
                '<div class="ds-lf-desc">상황·매치업을 종합해 Top-3 구종을 추천합니다</div></div>'
            )
            gr.HTML(
                '<div class="ds-landing-feature"><div class="ds-lf-title">위험도 분석</div>'
                '<div class="ds-lf-desc">패턴 노출·장타·홈런·볼넷 위험을 한눈에 확인합니다</div></div>'
            )
            gr.HTML(
                '<div class="ds-landing-feature"><div class="ds-lf-title">Instant Scout Q&A</div>'
                '<div class="ds-lf-desc">분석 결과를 근거로 후속 질문에 즉석으로 답합니다</div></div>'
            )
        landing_start_btn = gr.Button("시작하기", variant="primary", elem_classes=["ds-btn-analyze", "ds-landing-start"])

    with gr.Tabs(visible=False) as main_tabs:
        # ------------------------------------------------------------------
        # 투수 모드
        # ------------------------------------------------------------------
        with gr.Tab("⚾ 투수 모드"):
            gr.Markdown("내가 투수라는 관점에서, 다음 투구로 상대를 아웃 처리하거나 약한 타구를 유도하기 좋은 구종/코스를 추천합니다.")

            p_step_state = gr.State(1)

            with gr.Row(elem_classes=["ds-wizard-progress"]):
                p_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-step-dot", "ds-step-now"], size="sm")
                p_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                p_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                p_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")

            with gr.Row(elem_classes=["ds-wizard-row"]):
                with gr.Column(scale=3):
                    with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as p_wizard_tabs:
                        with gr.Tab("매치업", id=0):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 1 · 매치업</div>')
                                with gr.Row():
                                    p_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="내 투수 ID")
                                    p_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="상대 타자 ID")
                                gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                        with gr.Tab("상황판", id=1):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 2 · 상황판</div>')
                                gr.Markdown("#### 카운트 스코어보드")
                                with gr.Row(elem_classes=["ds-scoreboard"]):
                                    p_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                                    p_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                                    p_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                                with gr.Row():
                                    p_inning_input = gr.Number(value=1, precision=0, label="이닝")
                                    p_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")
                                p_count_board_output = gr.HTML(render_count_scoreboard(0, 0, 2, 1, "초(Top)"))

                        with gr.Tab("베이스 & 스코어", id=2):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 3 · 베이스 & 스코어</div>')
                                gr.Markdown("#### 주자 상황 — 루를 클릭해 표시하세요")
                                with gr.Row(elem_classes=["ds-diamond-wrap"]):
                                    with gr.Column(elem_classes=["ds-diamond"]):
                                        p_on2b_input = gr.Checkbox(value=False, label="2루", elem_classes=["ds-base-card", "ds-base-2b"])
                                        p_on3b_input = gr.Checkbox(value=False, label="3루", elem_classes=["ds-base-card", "ds-base-3b"])
                                        p_on1b_input = gr.Checkbox(value=False, label="1루", elem_classes=["ds-base-card", "ds-base-1b"])
                                gr.Markdown("#### 스코어")
                                with gr.Row():
                                    p_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                                    gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                                    p_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                        with gr.Tab("작전 지시", id=3):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 4 · 작전 지시</div>')
                                p_comment_input = gr.Textbox(value=DEFAULT_COMMENT_PITCHER, label="코치에게 전달할 전략 의도", lines=2)

                with gr.Column(scale=2, elem_classes=["ds-matchup-panel"]):
                    p_matchup_output = gr.HTML(
                        render_pitcher_matchup_summary(DEFAULT_PITCHER_ID, DEFAULT_BATTER_ID)
                    )

            # 다음/이전/분석 버튼은 스텝 카드 밖, 항상 마운트된 컨트롤바에 둔다.
            with gr.Row():
                p_prev_btn = gr.Button("⬅ 이전", elem_classes=["ds-btn-prev"])
                p_next_btn = gr.Button("다음 ➡", elem_classes=["ds-btn-next"])
                p_analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn-analyze"])

            p_reset_btn = gr.Button("다시 분석", elem_classes=["ds-btn-reset"])
            p_status_output = gr.HTML()

            with gr.Group(elem_classes=["ds-board"], visible=False) as p_board_group:
                gr.HTML('<div class="ds-board-title">코칭 보드</div>')
                p_hand_output = gr.Markdown()
                p_top3_output = gr.HTML()

                with gr.Row(elem_classes=["ds-bento"]):
                    with gr.Column():
                        gr.Markdown("#### 추천 구종")
                        p_recommend_card_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 상대 타자 약점")
                        p_batter_weakness_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 위험도 카드")
                        p_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column(elem_classes=["ds-bento-wide"]):
                        gr.Markdown("#### STRIKE ZONE BOARD")
                        p_hotcold_plot = gr.HTML()

                gr.Markdown("#### 전략 리포트")
                p_report_output = gr.Markdown()
                p_pdf_btn = gr.Button("PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                p_pdf_file_output = gr.File(label="다운로드 파일")

            with gr.Group(elem_classes=["ds-qa-panel"], visible=False) as p_qa_group:
                gr.HTML('<div class="ds-qa-title">Instant Scout Q&A</div>')
                with gr.Row():
                    p_example_btns = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]
                p_chatbot = gr.Chatbot(label="투수 모드 Q&A", height=300)
                with gr.Row():
                    p_chat_input = gr.Textbox(label="", placeholder="분석 결과에 대해 질문해보세요", scale=4)
                    p_chat_send_btn = gr.Button("전송", scale=1)

            p_result_state = gr.State(None)

            p_analyze_btn.click(
                fn=lambda: render_analysis_status(done=False), outputs=[p_status_output],
            ).then(
                fn=run_pitcher_analysis,
                inputs=[
                    p_pitcher_id_input, p_batter_id_input, p_balls_input, p_strikes_input, p_outs_input,
                    p_inning_input, p_topbot_input, p_on1b_input, p_on2b_input, p_on3b_input,
                    p_our_score_input, p_opponent_score_input, p_comment_input,
                ],
                outputs=[
                    p_hand_output, p_top3_output, p_risk_html_output, p_recommend_card_output,
                    p_batter_weakness_output, p_hotcold_plot, p_report_output, p_result_state, p_status_output,
                ],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[p_board_group],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[p_qa_group],
            )
            p_pdf_btn.click(fn=generate_pdf, inputs=[p_result_state], outputs=[p_pdf_file_output])

            p_wizard_outputs = [p_wizard_tabs, p_step_state, p_chip1, p_chip2, p_chip3, p_chip4]
            p_matchup_inputs = [p_pitcher_id_input, p_batter_id_input]
            for comp in p_matchup_inputs:
                comp.change(fn=render_pitcher_matchup_summary, inputs=p_matchup_inputs, outputs=[p_matchup_output])
            p_count_inputs = [p_balls_input, p_strikes_input, p_outs_input, p_inning_input, p_topbot_input]
            for comp in p_count_inputs:
                comp.change(fn=render_count_scoreboard, inputs=p_count_inputs, outputs=[p_count_board_output])
            p_prev_btn.click(fn=_step_prev, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_next_btn.click(fn=_step_next, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_chip1.click(fn=_goto_step_1, outputs=p_wizard_outputs)
            p_chip2.click(fn=_goto_step_2, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_chip3.click(fn=_goto_step_3, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_chip4.click(fn=_goto_step_4, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_reset_btn.click(fn=_goto_step_1, outputs=p_wizard_outputs)

            p_chat_send_btn.click(
                fn=handle_chat, inputs=[p_chat_input, p_chatbot, p_result_state], outputs=[p_chatbot, p_chat_input],
            )
            p_chat_input.submit(
                fn=handle_chat, inputs=[p_chat_input, p_chatbot, p_result_state], outputs=[p_chatbot, p_chat_input],
            )
            for btn, question in zip(p_example_btns, EXAMPLE_QUESTIONS):
                btn.click(fn=lambda q=question: q, outputs=[p_chat_input]).then(
                    fn=handle_chat, inputs=[p_chat_input, p_chatbot, p_result_state], outputs=[p_chatbot, p_chat_input],
                )

        # ------------------------------------------------------------------
        # 타자 모드
        # ------------------------------------------------------------------
        with gr.Tab("🏏 타자 모드"):
            gr.Markdown("내가 타자라는 관점에서, 상대 투수가 다음에 던질 가능성이 높은 구종과 노려야 할 코스를 추천합니다.")

            b_step_state = gr.State(1)

            with gr.Row(elem_classes=["ds-wizard-progress"]):
                b_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-step-dot", "ds-step-now"], size="sm")
                b_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                b_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                b_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")

            with gr.Row(elem_classes=["ds-wizard-row"]):
                with gr.Column(scale=3):
                    with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as b_wizard_tabs:
                        with gr.Tab("매치업", id=0):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 1 · 매치업</div>')
                                with gr.Row():
                                    b_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="내 타자 ID")
                                    b_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="상대 투수 ID")
                                gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                        with gr.Tab("상황판", id=1):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 2 · 상황판</div>')
                                gr.Markdown("#### 카운트 스코어보드")
                                with gr.Row(elem_classes=["ds-scoreboard"]):
                                    b_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                                    b_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                                    b_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                                with gr.Row():
                                    b_inning_input = gr.Number(value=1, precision=0, label="이닝")
                                    b_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")
                                b_count_board_output = gr.HTML(render_count_scoreboard(0, 0, 2, 1, "초(Top)"))

                        with gr.Tab("베이스 & 스코어", id=2):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 3 · 베이스 & 스코어</div>')
                                gr.Markdown("#### 주자 상황 — 루를 클릭해 표시하세요")
                                with gr.Row(elem_classes=["ds-diamond-wrap"]):
                                    with gr.Column(elem_classes=["ds-diamond"]):
                                        b_on2b_input = gr.Checkbox(value=False, label="2루", elem_classes=["ds-base-card", "ds-base-2b"])
                                        b_on3b_input = gr.Checkbox(value=False, label="3루", elem_classes=["ds-base-card", "ds-base-3b"])
                                        b_on1b_input = gr.Checkbox(value=False, label="1루", elem_classes=["ds-base-card", "ds-base-1b"])
                                gr.Markdown("#### 스코어")
                                with gr.Row():
                                    b_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                                    gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                                    b_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                        with gr.Tab("작전 지시", id=3):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">STEP 4 · 작전 지시</div>')
                                b_comment_input = gr.Textbox(value=DEFAULT_COMMENT_BATTER, label="코치에게 전달할 전략 의도", lines=2)

                with gr.Column(scale=2, elem_classes=["ds-matchup-panel"]):
                    b_matchup_output = gr.HTML(
                        render_batter_matchup_summary(DEFAULT_BATTER_ID, DEFAULT_PITCHER_ID)
                    )

            with gr.Row():
                b_prev_btn = gr.Button("⬅ 이전", elem_classes=["ds-btn-prev"])
                b_next_btn = gr.Button("다음 ➡", elem_classes=["ds-btn-next"])
                b_analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn-analyze"])

            b_reset_btn = gr.Button("다시 분석", elem_classes=["ds-btn-reset"])
            b_status_output = gr.HTML()

            with gr.Group(elem_classes=["ds-board"], visible=False) as b_board_group:
                gr.HTML('<div class="ds-board-title">코칭 보드</div>')
                b_hand_output = gr.Markdown()
                b_top3_output = gr.HTML()

                with gr.Row(elem_classes=["ds-bento"]):
                    with gr.Column():
                        gr.Markdown("#### 노릴 코스 / 대응 전략")
                        b_recommend_card_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 상대 투수 패턴")
                        b_pitcher_pattern_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 위험도 카드")
                        b_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column(elem_classes=["ds-bento-wide"]):
                        gr.Markdown("#### STRIKE ZONE BOARD")
                        b_hotcold_plot = gr.HTML()

                gr.Markdown("#### 전략 리포트")
                b_report_output = gr.Markdown()
                b_pdf_btn = gr.Button("PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                b_pdf_file_output = gr.File(label="다운로드 파일")

            with gr.Group(elem_classes=["ds-qa-panel"], visible=False) as b_qa_group:
                gr.HTML('<div class="ds-qa-title">Instant Scout Q&A</div>')
                with gr.Row():
                    b_example_btns = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]
                b_chatbot = gr.Chatbot(label="타자 모드 Q&A", height=300)
                with gr.Row():
                    b_chat_input = gr.Textbox(label="", placeholder="분석 결과에 대해 질문해보세요", scale=4)
                    b_chat_send_btn = gr.Button("전송", scale=1)

            b_result_state = gr.State(None)

            b_analyze_btn.click(
                fn=lambda: render_analysis_status(done=False), outputs=[b_status_output],
            ).then(
                fn=run_batter_analysis,
                inputs=[
                    b_batter_id_input, b_pitcher_id_input, b_balls_input, b_strikes_input, b_outs_input,
                    b_inning_input, b_topbot_input, b_on1b_input, b_on2b_input, b_on3b_input,
                    b_our_score_input, b_opponent_score_input, b_comment_input,
                ],
                outputs=[
                    b_hand_output, b_top3_output, b_risk_html_output, b_recommend_card_output,
                    b_pitcher_pattern_output, b_hotcold_plot, b_report_output, b_result_state, b_status_output,
                ],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[b_board_group],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[b_qa_group],
            )
            b_pdf_btn.click(fn=generate_pdf, inputs=[b_result_state], outputs=[b_pdf_file_output])

            b_wizard_outputs = [b_wizard_tabs, b_step_state, b_chip1, b_chip2, b_chip3, b_chip4]
            b_matchup_inputs = [b_batter_id_input, b_pitcher_id_input]
            for comp in b_matchup_inputs:
                comp.change(fn=render_batter_matchup_summary, inputs=b_matchup_inputs, outputs=[b_matchup_output])
            b_count_inputs = [b_balls_input, b_strikes_input, b_outs_input, b_inning_input, b_topbot_input]
            for comp in b_count_inputs:
                comp.change(fn=render_count_scoreboard, inputs=b_count_inputs, outputs=[b_count_board_output])
            b_prev_btn.click(fn=_step_prev, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_next_btn.click(fn=_step_next, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_chip1.click(fn=_goto_step_1, outputs=b_wizard_outputs)
            b_chip2.click(fn=_goto_step_2, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_chip3.click(fn=_goto_step_3, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_chip4.click(fn=_goto_step_4, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_reset_btn.click(fn=_goto_step_1, outputs=b_wizard_outputs)

            b_chat_send_btn.click(
                fn=handle_chat, inputs=[b_chat_input, b_chatbot, b_result_state], outputs=[b_chatbot, b_chat_input],
            )
            b_chat_input.submit(
                fn=handle_chat, inputs=[b_chat_input, b_chatbot, b_result_state], outputs=[b_chatbot, b_chat_input],
            )
            for btn, question in zip(b_example_btns, EXAMPLE_QUESTIONS):
                btn.click(fn=lambda q=question: q, outputs=[b_chat_input]).then(
                    fn=handle_chat, inputs=[b_chat_input, b_chatbot, b_result_state], outputs=[b_chatbot, b_chat_input],
                )

    landing_start_btn.click(
        fn=lambda: (gr.Column(visible=False), gr.Tabs(visible=True)),
        outputs=[landing_view, main_tabs],
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7862,
        share=True
    )
