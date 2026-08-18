"""위험도 카드 / Top-3 랭킹 카드 / 히어로 추천 카드 / 인사이트 카드 렌더러.
app.py에서 순수 이동됨 (Task 2, 동작 변경 없음)."""

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
