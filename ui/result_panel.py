"""위험도 카드 / Top-3 랭킹 카드 / 히어로 추천 카드 / 인사이트 카드 렌더러.
app.py에서 순수 이동됨 (Task 2, 동작 변경 없음)."""

import html
from datetime import datetime

from services.scouting_service import pitch_label_kr

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

def render_risk_badges(risk_summary: dict) -> str:
    """위험도 4종을 한 줄짜리 행 4개로. 목업의 #risks 블록과 같은 마크업이다.

    기존 render_risk_cards는 150px 카드 4개를 가로로 늘어놓아 결과 열을 다 잡아먹었다.
    콘솔은 존이 주인공이므로 위험도는 훑어보는 정보로 내린다.
    """
    rows = []
    for key, label_kr in RISK_LABELS_KR.items():
        value = risk_summary.get(key)
        level, color, _ = risk_level(key, value)
        # risk_level의 pct는 정수 반올림이라 1.7%가 2%로 뭉개진다. 표시값은 원값에서 만든다.
        value_text = "데이터 부족" if value is None else f"{value:.1%}"
        # 배지는 4칸을 나눠 쓰므로 "패턴 노출 위험"이 들어가면 넘친다. 섹션 제목이 이미
        # "위험도"라 접미를 떼도 뜻이 흐려지지 않는다(목업의 RISK_LABEL도 짧은 쪽이다).
        badge_label = label_kr.removesuffix(" 위험")
        rows.append(
            f'<div class="ds-risk">'
            f'<div><span class="ds-risk__dot" style="background:{color}"></span>'
            f'<span class="ds-risk__label">{html.escape(badge_label)}</span></div>'
            f'<div class="ds-risk__lvl" style="color:{color}">{level}</div>'
            f'<div class="ds-risk__pct ds-num">{value_text}</div>'
            f"</div>"
        )
    return f'<div class="ds-risks">{"".join(rows)}</div>'


def render_top3_gauges(top3: list[dict]) -> str:
    """예측 확률 Top-3를 순위 번호 + 가로 게이지로. 목업의 #top3 블록과 같은 마크업이다.

    막대 길이는 1위 대비 비율이다. 절대 확률로 그리면 세 막대가 다 짧아 순위 차이가
    눈에 안 들어온다.
    """
    rank_colors = ("#c8102e", "#14203c", "#8a8375")
    items = top3[:3]
    top_prob = max((item["probability"] for item in items), default=0.0) or 1.0
    rows = []
    for i, item in enumerate(items):
        label = item["pitch_label"]
        prob = item["probability"]
        width = round(100 * prob / top_prob)
        color = rank_colors[i] if i < len(rank_colors) else "#6b6555"
        rows.append(
            f'<div class="ds-rank ds-rank--{i + 1}">'
            f'<span class="ds-rank__no" style="background:{color}">{i + 1}</span>'
            f'<div class="ds-rank__body">'
            f'<div class="ds-rank__line">'
            f'<span class="ds-rank__name">{html.escape(pitch_label_kr(label))} '
            f"<em>({html.escape(str(label))})</em></span>"
            f'<span class="ds-rank__pct ds-num" style="color:{color}">{prob:.1%}</span>'
            f"</div>"
            f'<div class="ds-track"><div class="ds-track__fill" '
            f'style="width:{width}%; background:{color}"></div></div>'
            f"</div></div>"
        )
    return f'<div class="ds-top3">{"".join(rows)}</div>'


def _risk_summary_line(label_kr: str, value: float | None, key: str) -> str:
    level, _, _ = risk_level(key, value)
    if value is None:
        return f"- {label_kr}: 데이터 부족"
    return f"- {label_kr}: {level} ({value:.1%})"

# ============================================================================
# 카드형 결과 표시 (Top-3 랭킹 카드 / 히어로 추천 카드 / 인사이트 카드)
# ============================================================================

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
