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

import json
import os
import re
import textwrap
from datetime import datetime
from pathlib import Path

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
from ui.scene import build_scene_payload, render_scene_canvas, scene_engine_js
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

# FAISS 검색(RAGService)과 LLM(CoachAgent)은 무거운 선택적 의존성이라 초기화 실패가
# 앱 전체를 죽이지 않도록 각각 따로 감싼다. FAISS 검색 결과는 Q&A 로그에만 남기고 답변
# 생성에는 쓰지 않으므로, RAGService가 없어도 Q&A는 그대로 동작한다. Q&A가 안내 메시지로
# 대체되는 건 아래 CoachAgent 초기화가 실패했을 때뿐이다.
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
    matchup_hand_text = (
        f"🧍 상대 타자 타석 방향: **{_hand_kr(batter_stand)}타({batter_stand})**"
        f"  ⚾ 내 투구 방향: **{_hand_kr(pitcher_throws)}투({pitcher_throws})** _(데이터 기반 자동 추정)_"
    )

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
        "피해야 할 구종", avoid_text, accent="#1f8a4c",
    )
    batter_weakness_html = render_insight_card("상대 타자 약점 요약", pr["batter_weakness"]["summary"])
    # Top-3 각 구종이 실제로 가장 많이 들어간 zone_cell을 궤적 목적지로 사용(구종별 궤적 표시).
    pitcher_trajectories = [
        {"pitch_label": item["pitch_label"], "rank": i + 1,
         "cell": scouting_service.get_zone_cell_estimate(pitcher_id, item["pitch_label"])}
        for i, item in enumerate(result["predicted_top3_pitches"])
    ]
    scene_json = json.dumps(build_scene_payload(
        mode="pitcher", stand=batter_stand, zone_scores=pr["zone_hit_risk_scores"],
        highlight_cell=pr["best_zone_cell"], metric="HIT_RISK", trajectories=pitcher_trajectories,
    ))

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
        scene_json, report_md, pitcher_state, status_html,
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
        "대응 전략", br["counter_strategy"], accent="#1f8a4c",
    )
    pitcher_pattern_html = render_insight_card("상대 투수 패턴 요약", br["pitcher_pattern"]["summary"])
    batter_trajectories = [
        {"pitch_label": loc["pitch_label"], "rank": i + 1, "cell": loc["zone_cell"]}
        for i, loc in enumerate(br["expected_locations"])
    ]
    scene_json = json.dumps(build_scene_payload(
        mode="batter", stand=my_stand, zone_scores=br["zone_probability_scores"],
        highlight_cell=br["target_zone_cell"], metric="PITCH_PROB", trajectories=batter_trajectories,
    ))

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
        scene_json, report_md, batter_state, status_html,
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
    """CoachAgent가 방금 나온 분석 결과(last_result)를 근거로 답한다. FAISS 검색도 같은
    요청에서 돌지만 그 결과(context_chunks)는 db_save_qa_log로만 가고 답변 생성에는
    들어가지 않는다. 검색·LLM 어느 단계가 실패해도 예외를 흡수해 채팅만 안내 메시지로
    대체하고 앱은 죽지 않는다."""
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
            print(f"[경고] FAISS 검색 실패, 로그용 컨텍스트 없이 진행합니다: {exc}")
            context_chunks = []

        try:
            if coach_agent is not None:
                # history(이전 대화)를 함께 넘겨 CoachAgent가 대화 상태/반복 감지에 쓰게 한다.
                # CoachAgent.answer 내부에도 자체 try/except(Ollama 실패 시 evidence 기반
                # fallback)가 있지만, 예상 밖 state 구조 등 그 바깥에서 터질 수 있는
                # 예외까지 대비해 이 레벨에서도 한 번 더 방어한다.
                answer_info = coach_agent.answer(message, history, last_result)
                answer = answer_info["answer"]
                answer_source = answer_info["source"]
                # intent/focus는 화면에 노출하지 않고 서버 로그에만 남겨 개발 확인용으로 쓴다.
                print(f"[Q&A] intent={answer_info.get('intent')} focus={answer_info.get('focus')}")
            else:
                answer = "Instant Scout Q&A를 사용할 수 없습니다 (LLM 초기화 실패)."
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


def _analyze_btn_update(step: int):
    """분석 실행 버튼은 마지막 스텝(STEP 4)에서만 노출한다.
    '다음' 버튼은 별도 visible= 토글 대신, 이 버튼이 보일 때 CSS 형제 선택자(.ds-btn-analyze:not(.hidden) ~
    .ds-btn-next)로 숨긴다 — 두 버튼의 visible=을 같은 이벤트에 함께 토글하면 두 번째 전환부터
    간헐적으로 갱신이 반영되지 않는 문제가 있었다(아래 _step_prev 설명과 동일한 Gradio 이슈)."""
    return gr.Button(visible=int(step) == 4)


def _goto_step_1():
    return (gr.Tabs(selected=0), 1, *_step_dot_updates(1), _analyze_btn_update(1))


def _chip_goto(target: int, current_step) -> tuple:
    """진행 트랙 칩은 이미 지나왔거나 현재 스텝으로는 자유롭게 이동할 수 있지만, 아직
    도달하지 않은(예정) 스텝으로는 건너뛸 수 없다 — 내용을 채우지 않고 앞 스텝으로
    건너뛰는 것을 막기 위해 '다음' 버튼을 눌러야만 전진하도록 강제한다."""
    current = int(current_step)
    step = target if target <= current else current
    return (gr.Tabs(selected=step - 1), step, *_step_dot_updates(step), _analyze_btn_update(step))


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
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target), _analyze_btn_update(target))


def _step_next(current_step: int):
    target = min(4, int(current_step) + 1)
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target), _analyze_btn_update(target))


# 씬 엔진은 head=로 넣는다. gr.HTML 안의 <script>는 innerHTML 경로라 실행이 보장되지 않는다.
gr.set_static_paths(paths=[Path(__file__).resolve().parent / "ui" / "static" / "assets"])
SCENE_HEAD = f"<script>{scene_engine_js()}</script>"
# 씬 엔진이 고정 엘리먼트 ID를 써서 탭마다 한 벌씩 둘 수 없다. 그래서 씬 블록은 탭
# 밖에 하나만 두고, 갱신할 때 지금 보이는 탭의 슬롯으로 DOM 노드를 옮긴다. 그래야
# 분석 결과 바로 아래에 존이 나온다 - 탭 밖에 그대로 두면 Q&A 섹션까지 지나 맨 아래에 붙는다.
_SCENE_UPDATE_JS = "(v) => { if (v && window.dsScene) { window.dsScene.update(JSON.parse(v)); } }"
# 결과 영역(board group)은 분석 출력보다 뒤에 보이게 된다. change 시점에는 씬이 아직
# 숨어 있어 그려지지 않으므로, 영역이 나타난 뒤에 한 번 더 그린다.
_SCENE_REFRESH_JS = "() => { if (window.dsScene) { window.dsScene.refresh(); } }"


def _empty_scene_payload(mode: str) -> str:
    """분석 전의 씬. 9칸을 전부 0으로 두면 엔진이 중립색으로 그린다."""
    return json.dumps(build_scene_payload(
        mode=mode, stand="L", zone_scores={i: 0.0 for i in range(10)},
        highlight_cell=4, metric="HIT_RISK", trajectories=None,
    ))


with gr.Blocks(title="DiamondScout AI", css=CUSTOM_CSS, head=SCENE_HEAD) as demo:
    gr.Markdown("# ⚾ DiamondScout AI")
    gr.Markdown("투수 모드 / 타자 모드로 나눠, 다음 구종 예측(LightGBM + GRU 앙상블) + 위험도 + 상대 분석 + Q&A를 한 화면에서 확인하는 전력분석 데모")

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

    # 스트라이크 존 씬. 투수/타자 탭이 같은 캔버스를 함께 쓴다. 씬 엔진이 고정
    # 엘리먼트 ID를 쓰기 때문에 탭마다 한 벌씩 두면 서로를 덮어쓴다.
    # 씬 마크업은 탭마다 한 벌씩 있고(같은 id가 둘), 엔진이 화면에 보이는 쪽을 골라
    # 그린다(ui/static/scene.js의 $ 참고). 여기는 페이로드를 실어 보내는 통로만 둔다.
    with gr.Group(visible=False, elem_classes=["ds-scene-group"]) as scene_group:
        scene_payload = gr.Textbox(
            value=_empty_scene_payload("pitcher"), visible=False, elem_id="scenePayload",
        )
        scene_payload.change(None, scene_payload, None, js=_SCENE_UPDATE_JS)
        demo.load(None, scene_payload, None, js=_SCENE_UPDATE_JS)

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
            # analyze -> next 순서로 배치: '다음' 버튼은 별도 visible= 토글 없이, analyze가 보일 때
            # CSS 형제 선택자(.ds-btn-analyze:not(.hidden) ~ .ds-btn-next)로 숨긴다.
            with gr.Row():
                p_prev_btn = gr.Button("⬅ 이전", elem_classes=["ds-btn-prev"])
                # 초기값은 visible=True로 두고 아래 demo.load()에서 실제 이벤트로 한 번 False로 되돌린다.
                # STEP1~3에서 처음 STEP4로 넘어갈 때 이 버튼의 visible=이 False->True로 바뀌는 첫 전환이
                # 간헐적으로 화면에 반영되지 않는 문제가 있었는데(Gradio 컴포넌트가 Python 쪽 정적 초기값에서
                # 한 번도 실제 업데이트를 거치지 않은 상태로 있다가 처음 값이 바뀔 때 발생), load 시점에
                # 미리 한 번 실제 업데이트를 거치게 하면 이후 전환은 안정적으로 반영된다.
                p_analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn-analyze"], visible=True)
                p_next_btn = gr.Button("다음 ➡", elem_classes=["ds-btn-next"])

            p_reset_btn = gr.Button("다시 분석", elem_classes=["ds-btn-reset"])
            p_status_output = gr.HTML()

            with gr.Group(elem_classes=["ds-board"], visible=False) as p_board_group:
                gr.HTML('<div class="ds-board-title">코칭 보드</div>')
                p_hand_output = gr.Markdown()
                p_top3_output = gr.HTML()

                gr.Markdown("#### 🎯 추천 구종", elem_classes=["ds-board-section-title"])
                p_recommend_card_output = gr.HTML()

                with gr.Row(elem_classes=["ds-quick-row"]):
                    with gr.Column():
                        gr.Markdown("#### 위험도 카드")
                        p_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column():
                        gr.Markdown("#### 상대 타자 약점")
                        p_batter_weakness_output = gr.HTML()

                gr.Markdown("#### STRIKE ZONE BOARD", elem_classes=["ds-board-section-title"])
                gr.HTML(render_scene_canvas())

                with gr.Accordion("상세 리포트 전체 보기 (근거 · 참고 데이터)", open=False, elem_classes=["ds-report-accordion"]):
                    p_report_output = gr.Markdown(elem_classes=["ds-report-md"])
                p_pdf_btn = gr.Button("PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                # 초기값은 visible=True로 두고 demo.load()에서 실제 이벤트로 한 번 False로 되돌린다.
                # (분석 실행 버튼과 동일한 이유 — Gradio 첫 visible= 전환 누락 버그 회피)
                p_pdf_file_output = gr.File(label="다운로드 파일", visible=True, elem_classes=["ds-pdf-file"])

            with gr.Group(elem_classes=["ds-qa-panel"], visible=False) as p_qa_group:
                gr.HTML('<div class="ds-qa-title">Instant Scout Q&A</div>')
                with gr.Row(elem_classes=["ds-qa-chips"]):
                    p_example_btns = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]
                p_chatbot = gr.Chatbot(label="투수 모드 Q&A", show_label=False, height=340, elem_classes=["ds-chatbot"])
                with gr.Row(elem_classes=["ds-qa-input-row"]):
                    p_chat_input = gr.Textbox(label="", placeholder="분석 결과에 대해 질문해보세요", scale=4, container=False)
                    p_chat_send_btn = gr.Button("전송", scale=1, elem_classes=["ds-btn-send"])

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
                    p_batter_weakness_output, scene_payload, p_report_output, p_result_state, p_status_output,
                ],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[p_board_group],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[p_qa_group],
            ).then(None, None, None, js=_SCENE_REFRESH_JS)
            p_pdf_btn.click(
                fn=generate_pdf, inputs=[p_result_state], outputs=[p_pdf_file_output],
            ).then(
                fn=lambda: gr.File(visible=True), outputs=[p_pdf_file_output],
            )

            p_wizard_outputs = [p_wizard_tabs, p_step_state, p_chip1, p_chip2, p_chip3, p_chip4, p_analyze_btn]
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
                b_analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn-analyze"], visible=True)
                b_next_btn = gr.Button("다음 ➡", elem_classes=["ds-btn-next"])

            b_reset_btn = gr.Button("다시 분석", elem_classes=["ds-btn-reset"])
            b_status_output = gr.HTML()

            with gr.Group(elem_classes=["ds-board"], visible=False) as b_board_group:
                gr.HTML('<div class="ds-board-title">코칭 보드</div>')
                b_hand_output = gr.Markdown()
                b_top3_output = gr.HTML()

                gr.Markdown("#### 🎯 노릴 코스 / 대응 전략", elem_classes=["ds-board-section-title"])
                b_recommend_card_output = gr.HTML()

                with gr.Row(elem_classes=["ds-quick-row"]):
                    with gr.Column():
                        gr.Markdown("#### 위험도 카드")
                        b_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column():
                        gr.Markdown("#### 상대 투수 패턴")
                        b_pitcher_pattern_output = gr.HTML()

                gr.Markdown("#### STRIKE ZONE BOARD", elem_classes=["ds-board-section-title"])
                gr.HTML(render_scene_canvas())

                with gr.Accordion("상세 리포트 전체 보기 (근거 · 참고 데이터)", open=False, elem_classes=["ds-report-accordion"]):
                    b_report_output = gr.Markdown(elem_classes=["ds-report-md"])
                b_pdf_btn = gr.Button("PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                b_pdf_file_output = gr.File(label="다운로드 파일", visible=True, elem_classes=["ds-pdf-file"])

            with gr.Group(elem_classes=["ds-qa-panel"], visible=False) as b_qa_group:
                gr.HTML('<div class="ds-qa-title">Instant Scout Q&A</div>')
                with gr.Row(elem_classes=["ds-qa-chips"]):
                    b_example_btns = [gr.Button(q, size="sm") for q in EXAMPLE_QUESTIONS]
                b_chatbot = gr.Chatbot(label="타자 모드 Q&A", show_label=False, height=340, elem_classes=["ds-chatbot"])
                with gr.Row(elem_classes=["ds-qa-input-row"]):
                    b_chat_input = gr.Textbox(label="", placeholder="분석 결과에 대해 질문해보세요", scale=4, container=False)
                    b_chat_send_btn = gr.Button("전송", scale=1, elem_classes=["ds-btn-send"])

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
                    b_pitcher_pattern_output, scene_payload, b_report_output, b_result_state, b_status_output,
                ],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[b_board_group],
            ).then(
                fn=lambda: gr.Group(visible=True), outputs=[b_qa_group],
            ).then(None, None, None, js=_SCENE_REFRESH_JS)
            b_pdf_btn.click(
                fn=generate_pdf, inputs=[b_result_state], outputs=[b_pdf_file_output],
            ).then(
                fn=lambda: gr.File(visible=True), outputs=[b_pdf_file_output],
            )

            b_wizard_outputs = [b_wizard_tabs, b_step_state, b_chip1, b_chip2, b_chip3, b_chip4, b_analyze_btn]
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
        fn=lambda: (gr.Column(visible=False), gr.Tabs(visible=True), gr.Group(visible=True)),
        outputs=[landing_view, main_tabs, scene_group],
    )

    demo.load(
        fn=lambda: (
            gr.Button(visible=False), gr.Button(visible=False),
            gr.File(visible=False), gr.File(visible=False),
        ),
        outputs=[p_analyze_btn, b_analyze_btn, p_pdf_file_output, b_pdf_file_output],
    )


if __name__ == "__main__":
    # 배포 플랫폼(Render 등)은 바인딩할 포트를 PORT 환경변수로 지정하고 자체 공개 URL을
    # 제공한다. 그 환경에서는 Gradio share 터널이 불필요하므로 로컬 실행일 때만 켠다.
    port = os.environ.get("PORT")
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(port) if port else 7862,
        share=port is None,
    )
