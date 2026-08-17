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

import html
import os
import re
import textwrap
from datetime import datetime

import gradio as gr
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from services.scouting_service import (
    ScoutingRequest,
    ScoutingService,
    get_batter_display,
    pitch_label_kr,
)
from ui.console import (
    MAX_BALLS,
    MAX_OUTS,
    MAX_STRIKES,
    cycle_value,
    render_base_diamond,
    render_count_lamps,
    render_player_card,
    render_scoreboard,
    toggle_base,
)
from ui.result_panel import (
    RISK_LABELS_KR,
    _risk_summary_line,
    render_analysis_status,
    render_hero_recommend_card,
    render_insight_card,
    render_risk_cards,
    render_top3_cards,
    risk_level,
)
from ui.styles import CUSTOM_CSS
from ui.trajectory_view import render_batter_hotcold_zone, render_pitcher_hotcold_zone
from ui.zone_heatmap import (
    _zone_hand_label,
    render_batter_zone_board,
    render_pitcher_zone_board,
)

# matplotlib 기본 폰트(DejaVu Sans)는 한글 글리프가 없어 히트맵/위치 그래프의 한글 라벨이
# 깨지므로(빈 네모) macOS 기본 한글 폰트로 지정한다. AppleGothic 단독으로는 í/ó/ñ 같은 라틴
# 악센트 글리프가 없어 해외 선수 이름에서 글자가 통째로 빠지므로(TS-005), 폴백 폰트를 같이 지정한다.
plt.rcParams["font.family"] = ["AppleGothic", "Arial Unicode MS"]
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

    # 투수 모드: 우리팀 = 투수팀이므로 우리팀 기준 점수차가 곧 모델이 쓰는 "투수팀 기준" score_diff다.
    if our_score is None or opponent_score is None:
        raise gr.Error("점수를 입력해주세요.")
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
        "피해야 할 구종", avoid_text, accent="#c8102e",
    )
    batter_weakness_html = render_insight_card("상대 타자 약점 요약", pr["batter_weakness"]["summary"])
    # Top-3 각 구종이 실제로 가장 많이 들어간 zone_cell을 궤적 목적지로 사용(구종별 궤적 표시).
    pitcher_trajectories = [
        {"pitch_label": item["pitch_label"], "rank": i + 1,
         "cell": scouting_service.get_zone_cell_estimate(pitcher_id, item["pitch_label"])}
        for i, item in enumerate(result["predicted_top3_pitches"])
    ]
    zone_html = render_pitcher_zone_board(
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
    matchup_html = render_matchup_column(
        "pitcher", pitcher_id, batter_id,
        pitcher_gauges=_pitch_gauges(pr["own_pitch_pattern"]),
        pitcher_note=pr["own_pitch_pattern"]["summary"],
        batter_note=pr["batter_weakness"]["summary"],
    )
    result_html = _compose_result_html(
        meta, recommend_card_html, top3_html, risk_html, batter_weakness_html,
    )
    pitcher_state = {"mode": "pitcher", "result": result, "meta": meta, "analysis_log_id": analysis_log_id}

    return (
        matchup_html, zone_html, result_html, report_md, pitcher_state, render_analysis_status(done=True),
    )


def run_batter_analysis(
    my_batter_id, opponent_pitcher_id, balls, strikes, outs, inning, topbot_kr,
    on1b, on2b, on3b, our_score, opponent_score, comment,
):
    pitcher_id = int(opponent_pitcher_id)
    batter_id = int(my_batter_id)

    my_stand = scouting_service.get_batter_stand(batter_id)
    opponent_throws = scouting_service.get_pitcher_throws(pitcher_id)

    # 타자 모드: 우리팀 = 타자팀. 모델 context의 score_diff는 "투수팀(=상대팀) 기준"이므로 부호를
    # 반전해서 넘긴다. 사용자에게 보여줄 때는 항상 우리팀 기준(user_score_diff)을 쓴다.
    if our_score is None or opponent_score is None:
        raise gr.Error("점수를 입력해주세요.")
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
        "대응 전략", br["counter_strategy"], accent="#c8102e",
    )
    pitcher_pattern_html = render_insight_card("상대 투수 패턴 요약", br["pitcher_pattern"]["summary"])
    batter_trajectories = [
        {"pitch_label": loc["pitch_label"], "rank": i + 1, "cell": loc["zone_cell"]}
        for i, loc in enumerate(br["expected_locations"])
    ]
    zone_html = render_batter_zone_board(
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
    matchup_html = render_matchup_column(
        "batter", pitcher_id, batter_id,
        pitcher_gauges=_pitch_gauges(br["pitcher_pattern"]),
        pitcher_note=br["pitcher_pattern"]["summary"],
    )
    result_html = _compose_result_html(
        meta, recommend_card_html, top3_html, risk_html, pitcher_pattern_html,
    )
    batter_state = {"mode": "batter", "result": result, "meta": meta, "analysis_log_id": analysis_log_id}

    return (
        matchup_html, zone_html, result_html, report_md, batter_state, render_analysis_status(done=True),
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


def _pitch_gauges(pattern: dict | None) -> list[tuple[str, float]]:
    """구종 비율 상위 3개를 선수 카드 게이지(라벨, 0~1 비율)로 변환한다."""
    if not pattern:
        return []
    return [
        (f"{pitch_label_kr(p['pitch_label'])}({p['pitch_label']})", float(p["ratio"]))
        for p in pattern.get("top_pitches", [])[:3]
    ]


def render_matchup_column(
    mode: str, pitcher_id, batter_id,
    pitcher_gauges: list[tuple[str, float]] | None = None,
    pitcher_note: str = "분석을 실행하면 구종 비율이 표시됩니다",
    batter_note: str = "분석을 실행하면 약점 구종이 표시됩니다",
) -> str:
    """좌측 매치업 컬럼. 투수/타자 카드는 항상 같은 순서로 그리고, 역할 배지만 모드에 따라 뒤집는다.
    선수 이름은 CSV에서 온 외부 문자열이므로 render_player_card 안에서 html.escape 된다."""
    pitcher_role, batter_role = ("내 투수", "상대 타자") if mode == "pitcher" else ("상대 투수", "내 타자")
    pitcher_card = render_player_card(
        scouting_service.get_pitcher_name(pitcher_id),
        f"{_hand_kr(scouting_service.get_pitcher_throws(pitcher_id))}투",
        pitcher_note, pitcher_gauges or [],
    )
    batter_card = render_player_card(
        get_batter_display(batter_id),
        f"{_hand_kr(scouting_service.get_batter_stand(batter_id))}타",
        batter_note, [],
    )
    mine = "ds-mu-slot--mine" if mode == "pitcher" else "ds-mu-slot--rival"
    rival = "ds-mu-slot--rival" if mode == "pitcher" else "ds-mu-slot--mine"
    return f"""
<div class="ds-matchup">
  <div class="ds-mu-slot {mine}"><div class="ds-mu-role">{pitcher_role}</div>{pitcher_card}</div>
  <div class="ds-vs"><span class="ds-vs__txt">VS</span></div>
  <div class="ds-mu-slot {rival}"><div class="ds-mu-role">{batter_role}</div>{batter_card}</div>
</div>
""".strip()


def _runners_text(on1b: int, on2b: int, on3b: int) -> str:
    names = [name for name, on in (("1루", on1b), ("2루", on2b), ("3루", on3b)) if on]
    return ", ".join(names) if names else "없음"


def _compose_result_html(meta: dict, hero_html: str, top3_html: str, risk_html: str, insight_html: str) -> str:
    """우측 결과 컬럼 한 덩어리. 상황 요약 → 히어로 추천 → Top-3 → 위험도 → 참고 순서는 목업과 같다."""
    c = meta["context"]
    topbot = "초" if c["inning_topbot_enc"] == 1 else "말"
    situation = (
        f"<b>{c['inning']}회{topbot}</b> · {c['balls']}B–{c['strikes']}S–{c['outs_when_up']}아웃 · "
        f"주자 {_runners_text(c['on_1b'], c['on_2b'], c['on_3b'])} · "
        f"우리 <b>{meta['our_score']}</b> : 상대 <b>{meta['opponent_score']}</b> ({meta['score_situation_label']})"
    )
    return f"""
<p class="ds-situation">{situation}</p>
{hero_html}
<div class="ds-sec"><div class="ds-sec__t">예측 확률 Top-3</div>{top3_html}</div>
<div class="ds-sec"><div class="ds-sec__t">위험도</div>{risk_html}</div>
<div class="ds-sec"><div class="ds-sec__t">참고</div>{insight_html}</div>
""".strip()


def _zone_placeholder_html(mode: str) -> str:
    """분석 전 존 카드 자리. 빈 공간을 두면 3열 균형이 무너져 보여 안내 카드를 채운다."""
    view = "투수 시점 — 내가 던지는 코스" if mode == "pitcher" else "타자 시점 — 상대가 던져올 코스"
    return f"""
<div class="ds-zone-card ds-zone-empty">
  <div class="ds-zone-header"><span class="ds-zone-header-en">STRIKE ZONE</span>
    <span class="ds-zone-header-sep">|</span><span class="ds-zone-header-kr">스트라이크 존</span></div>
  <div class="ds-zone-sub">{html.escape(view)}</div>
  <p class="ds-zone-caption">상황을 맞춘 뒤 <b>분석 실행</b>을 누르면 이 자리에 존 보드가 그려집니다.</p>
</div>
""".strip()


# ============================================================================
# Gradio 레이아웃
# ============================================================================

MODE_CHOICES = [("투수 모드", "pitcher"), ("타자 모드", "batter")]
TOPBOT_CHOICES = ["초(Top)", "말(Bot)"]
MAX_INNING = 20
MAX_SCORE = 30

HEADER_HTML = """
<header class="ds-top">
  <div class="ds-brand">
    <span class="ds-brand__mark" aria-hidden="true"></span>
    <span class="ds-brand__word">DiamondScout</span>
    <span class="ds-brand__sub">덕아웃 콘솔</span>
  </div>
  <div class="ds-top__note">다음 구종 예측 · 위험도 · 상대 분석을 한 화면에서 확인합니다</div>
</header>
"""

RESULT_EMPTY_HTML = (
    '<p class="ds-situation">아직 분석하지 않았습니다. 상황을 맞춘 뒤 좌측 <b>분석 실행</b>을 누르세요.</p>'
)


# ---------------------------------------------------------------------------
# 상태 → 렌더 (HTML은 표시 전용, 값의 단일 진실 공급원은 gr.State)
# ---------------------------------------------------------------------------

def _topbot_code(topbot_kr: str) -> str:
    return "Top" if str(topbot_kr).startswith("초") else "Bot"


def _on_count_click(kind: str, balls, strikes, outs):
    """램프를 누르면 해당 카운트만 한 칸 올라가고, 최대치에서 한 번 더 누르면 0으로 돌아간다."""
    balls, strikes, outs = int(balls), int(strikes), int(outs)
    if kind == "balls":
        balls = cycle_value(balls, MAX_BALLS)
    elif kind == "strikes":
        strikes = cycle_value(strikes, MAX_STRIKES)
    else:
        outs = cycle_value(outs, MAX_OUTS)
    return balls, strikes, outs, render_count_lamps(balls, strikes, outs)


def _on_base_click(index: int, bases):
    updated = toggle_base(tuple(int(b) for b in bases), index)
    return updated, render_base_diamond(*updated)


def _on_step(field: str, delta: int, inning, topbot, us, them):
    inning, us, them = int(inning), int(us), int(them)
    if field == "inning":
        inning = max(1, min(MAX_INNING, inning + delta))
    elif field == "us":
        us = max(0, min(MAX_SCORE, us + delta))
    else:
        them = max(0, min(MAX_SCORE, them + delta))
    return inning, us, them, render_scoreboard(inning, _topbot_code(topbot), us, them)


def _on_topbot_change(topbot, inning, us, them):
    return render_scoreboard(int(inning), _topbot_code(topbot), int(us), int(them))


def _on_mode_change(mode, pitcher_id, batter_id, comment):
    """모드를 바꾸면 직전 결과는 반대 관점의 값이라 그대로 두면 오독을 부른다. 결과를 비운다.
    코멘트는 사용자가 손대지 않은 기본 문구일 때만 그 모드의 기본값으로 갈아 끼운다."""
    defaults = {"pitcher": DEFAULT_COMMENT_PITCHER, "batter": DEFAULT_COMMENT_BATTER}
    next_comment = defaults[mode] if comment in defaults.values() else comment
    return (
        render_matchup_column(mode, pitcher_id, batter_id),
        _zone_placeholder_html(mode),
        RESULT_EMPTY_HTML,
        "",
        None,
        "",
        next_comment,
    )


def run_analysis(
    mode, pitcher_id, batter_id, balls, strikes, outs, inning, topbot, bases, our_score, opponent_score, comment,
):
    """모드에 따라 투수/타자 분석으로 갈라준다. 두 함수 모두 (내 선수, 상대 선수) 순서라 인자가 뒤집힌다."""
    on1b, on2b, on3b = (int(b) for b in bases)
    args = (balls, strikes, outs, inning, topbot, on1b, on2b, on3b, our_score, opponent_score, comment)
    if mode == "pitcher":
        return run_pitcher_analysis(pitcher_id, batter_id, *args)
    return run_batter_analysis(batter_id, pitcher_id, *args)


with gr.Blocks(title="DiamondScout AI", css=CUSTOM_CSS) as demo:
    gr.HTML(HEADER_HTML)

    balls_state = gr.State(0)
    strikes_state = gr.State(0)
    outs_state = gr.State(0)
    bases_state = gr.State((0, 0, 0))
    inning_state = gr.State(1)
    us_state = gr.State(0)
    them_state = gr.State(0)
    result_state = gr.State(None)

    with gr.Row(elem_classes=["ds-console"]):
        # ------------------------------------------------------------------
        # 좌 · 매치업
        # ------------------------------------------------------------------
        with gr.Column(scale=3, elem_classes=["ds-col-matchup"]):
            with gr.Column(elem_classes=["ds-card"]):
                gr.HTML('<div class="ds-card__title">매치업</div>')
                pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="투수")
                batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="타자")
                matchup_html = gr.HTML(render_matchup_column("pitcher", DEFAULT_PITCHER_ID, DEFAULT_BATTER_ID))
                comment_input = gr.Textbox(value=DEFAULT_COMMENT_PITCHER, label="작전 지시 (전략 의도)", lines=2)
                analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn", "ds-btn--primary"])
                status_output = gr.HTML()

        # ------------------------------------------------------------------
        # 중 · 스트라이크 존 + 상황 조작
        # ------------------------------------------------------------------
        with gr.Column(scale=5, elem_classes=["ds-col-zone"]):
            mode_input = gr.Radio(
                MODE_CHOICES, value="pitcher", label="시점 모드", elem_classes=["ds-seg", "ds-seg--wide"],
            )
            zone_html = gr.HTML(_zone_placeholder_html("pitcher"))

            with gr.Column(elem_classes=["ds-card", "ds-ctrl-card"]):
                gr.HTML('<div class="ds-card__title">상황 조작</div>')

                gr.HTML('<div class="ds-ctrl__label">카운트 — 램프를 눌러 올립니다</div>')
                # 램프 HTML 위에 투명 버튼 3개를 겹쳐, 목업처럼 램프 줄 자체를 누르게 한다.
                # 값은 버튼이 아니라 state가 갖고 있으므로 화면값과 실제값이 갈라지지 않는다.
                with gr.Column(elem_classes=["ds-lamp-stack"]):
                    count_html = gr.HTML(render_count_lamps(0, 0, 0))
                    with gr.Column(elem_classes=["ds-lamp-hits"]):
                        balls_btn = gr.Button("볼 카운트 올리기", elem_classes=["ds-hit-btn"])
                        strikes_btn = gr.Button("스트라이크 카운트 올리기", elem_classes=["ds-hit-btn"])
                        outs_btn = gr.Button("아웃 카운트 올리기", elem_classes=["ds-hit-btn"])

                gr.HTML('<div class="ds-ctrl__label">주자 — 베이스를 눌러 올리고 내립니다</div>')
                with gr.Column(elem_classes=["ds-diamond-stack"]):
                    diamond_html = gr.HTML(render_base_diamond(0, 0, 0))
                    with gr.Column(elem_classes=["ds-base-hits"]):
                        base1_btn = gr.Button("1루 주자", elem_classes=["ds-base-hit", "ds-base-hit--1"])
                        base2_btn = gr.Button("2루 주자", elem_classes=["ds-base-hit", "ds-base-hit--2"])
                        base3_btn = gr.Button("3루 주자", elem_classes=["ds-base-hit", "ds-base-hit--3"])

                gr.HTML('<div class="ds-ctrl__label">이닝 · 스코어</div>')
                scoreboard_html = gr.HTML(render_scoreboard(1, "Top", 0, 0))
                with gr.Row(elem_classes=["ds-steprow"]):
                    inning_minus_btn = gr.Button("이닝 −", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])
                    inning_plus_btn = gr.Button("이닝 +", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])
                    topbot_input = gr.Radio(TOPBOT_CHOICES, value="초(Top)", label="초/말", elem_classes=["ds-seg"])
                with gr.Row(elem_classes=["ds-steprow"]):
                    us_minus_btn = gr.Button("우리 −", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])
                    us_plus_btn = gr.Button("우리 +", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])
                    them_minus_btn = gr.Button("상대 −", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])
                    them_plus_btn = gr.Button("상대 +", elem_classes=["ds-btn", "ds-btn--ghost", "ds-step-btn"])

        # ------------------------------------------------------------------
        # 우 · 결과
        # ------------------------------------------------------------------
        with gr.Column(scale=4, elem_classes=["ds-col-result"]):
            with gr.Column(elem_classes=["ds-card", "ds-result"]):
                gr.HTML('<div class="ds-card__title">추천 결과</div>')
                result_html = gr.HTML(RESULT_EMPTY_HTML)

    with gr.Accordion("코칭 리포트", open=False, elem_classes=["ds-report-accordion"]):
        report_md = gr.Markdown(elem_classes=["ds-report-md"])
        pdf_btn = gr.Button("PDF 리포트 다운로드 생성", elem_classes=["ds-btn", "ds-btn--ghost", "ds-btn-pdf"])
        # 초기값은 visible=True로 두고 demo.load()에서 실제 이벤트로 한 번 False로 되돌린다
        # (Gradio가 정적 초기값에서 첫 visible= 전환을 간헐적으로 누락하는 문제 회피).
        pdf_file_output = gr.File(label="다운로드 파일", visible=True, elem_classes=["ds-pdf-file"])

    with gr.Accordion("Instant Scout Q&A", open=False, elem_classes=["ds-report-accordion"]):
        with gr.Row(elem_classes=["ds-qa-chips"]):
            example_btns = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]
        chatbot = gr.Chatbot(label="Q&A", show_label=False, height=340, elem_classes=["ds-chatbot"])
        with gr.Row(elem_classes=["ds-qa-input-row"]):
            chat_input = gr.Textbox(label="", placeholder="분석 결과에 대해 질문해보세요", scale=4, container=False)
            chat_send_btn = gr.Button("전송", scale=1, elem_classes=["ds-btn-send"])

    # ----------------------------------------------------------------------
    # 이벤트 배선: 클릭 → state 갱신 → state가 렌더러를 다시 호출 → HTML 갱신
    # ----------------------------------------------------------------------
    count_inputs = [balls_state, strikes_state, outs_state]
    count_outputs = [balls_state, strikes_state, outs_state, count_html]
    for btn, kind in ((balls_btn, "balls"), (strikes_btn, "strikes"), (outs_btn, "outs")):
        btn.click(
            fn=lambda b, s, o, k=kind: _on_count_click(k, b, s, o),
            inputs=count_inputs, outputs=count_outputs,
        )

    for btn, index in ((base1_btn, 0), (base2_btn, 1), (base3_btn, 2)):
        btn.click(
            fn=lambda bases, i=index: _on_base_click(i, bases),
            inputs=[bases_state], outputs=[bases_state, diamond_html],
        )

    step_inputs = [inning_state, topbot_input, us_state, them_state]
    step_outputs = [inning_state, us_state, them_state, scoreboard_html]
    for btn, field, delta in (
        (inning_minus_btn, "inning", -1), (inning_plus_btn, "inning", 1),
        (us_minus_btn, "us", -1), (us_plus_btn, "us", 1),
        (them_minus_btn, "them", -1), (them_plus_btn, "them", 1),
    ):
        btn.click(
            fn=lambda i, t, u, th, f=field, d=delta: _on_step(f, d, i, t, u, th),
            inputs=step_inputs, outputs=step_outputs,
        )

    topbot_input.change(
        fn=_on_topbot_change,
        inputs=[topbot_input, inning_state, us_state, them_state], outputs=[scoreboard_html],
    )

    matchup_inputs = [mode_input, pitcher_id_input, batter_id_input]
    for comp in (pitcher_id_input, batter_id_input):
        comp.change(fn=render_matchup_column, inputs=matchup_inputs, outputs=[matchup_html])
    mode_input.change(
        fn=_on_mode_change, inputs=matchup_inputs + [comment_input],
        outputs=[matchup_html, zone_html, result_html, report_md, result_state, status_output, comment_input],
    )

    analyze_btn.click(
        fn=lambda: render_analysis_status(done=False), outputs=[status_output],
    ).then(
        fn=run_analysis,
        inputs=[
            mode_input, pitcher_id_input, batter_id_input, balls_state, strikes_state, outs_state,
            inning_state, topbot_input, bases_state, us_state, them_state, comment_input,
        ],
        outputs=[matchup_html, zone_html, result_html, report_md, result_state, status_output],
    )

    pdf_btn.click(
        fn=generate_pdf, inputs=[result_state], outputs=[pdf_file_output],
    ).then(
        fn=lambda: gr.File(visible=True), outputs=[pdf_file_output],
    )

    chat_send_btn.click(
        fn=handle_chat, inputs=[chat_input, chatbot, result_state], outputs=[chatbot, chat_input],
    )
    chat_input.submit(
        fn=handle_chat, inputs=[chat_input, chatbot, result_state], outputs=[chatbot, chat_input],
    )
    for btn, question in zip(example_btns, EXAMPLE_QUESTIONS):
        btn.click(fn=lambda q=question: q, outputs=[chat_input]).then(
            fn=handle_chat, inputs=[chat_input, chatbot, result_state], outputs=[chatbot, chat_input],
        )

    demo.load(fn=lambda: gr.File(visible=False), outputs=[pdf_file_output])



if __name__ == "__main__":
    # 배포 플랫폼(Render 등)은 바인딩할 포트를 PORT 환경변수로 지정하고 자체 공개 URL을
    # 제공한다. 그 환경에서는 Gradio share 터널이 불필요하므로 로컬 실행일 때만 켠다.
    port = os.environ.get("PORT")
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(port) if port else 7862,
        share=port is None,
    )
