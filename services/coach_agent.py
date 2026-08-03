"""
DiamondScout AI - CoachAgent: 대화형 Q&A 코치 에이전트

기존 services/llm_scout.py는 "이 질문 문구 -> 이 고정 문장" 식의 intent 분기가 30개 넘게
쌓이면서, 목록에 없는 질문 조합에는 초점이 어긋난 템플릿이 나가고 같은 결론(포심 추천 요약)
이 반복되는 한계에 부딪혔다. CoachAgent는 반대로 설계한다 - intent/focus는 "이번 답변에서
어떤 근거를 볼지"만 정하고, 답변 문장 자체는 매번 (질문 원문 + focus + evidence + 직전 대화)를
조합해 새로 만든다. Ollama가 있으면 LLM이 이 조합으로 자연어를 생성하고, 없을 때도 focus별
고정 한 문장이 아니라 evidence 값을 꽂아 넣는 동적 조합(+최소 2개 문장 프레임)으로 답한다.
"""

import json
import re

import requests

from services.scouting_service import pitch_label_kr

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "gemma2:latest"
OLLAMA_AVAILABILITY_TIMEOUT_SECONDS = 1.5
# 분석 요약 + 근거 JSON을 포함한 실제 프롬프트 기준 실측 15~20초 - 4초 같은 값은 매번
# 타임아웃으로 이어져 LLM이 사실상 한 번도 안 쓰이는 결과를 낳는다(직접 측정으로 확인).
OLLAMA_TIMEOUT_SECONDS = 25

KNOWN_PITCH_LABELS = ["FF", "SI", "SL", "CH", "ST", "FC", "CU", "FS", "KC", "SV", "OTHER"]
BREAKING_BALL_LABELS = {"SL", "CH", "ST", "FC", "CU", "FS", "KC", "SV"}
PITCH_KR_ALIASES = {
    "패스트볼": "FF", "직구": "FF", "포심": "FF",
    "싱커": "SI", "투심": "SI",
    "슬라이더": "SL",
    "체인지업": "CH", "체인지": "CH",
    "스위퍼": "ST",
    "커터": "FC",
    "커브": "CU", "커브볼": "CU",
    "스플리터": "FS", "포크볼": "FS",
    "너클커브": "KC",
    "슬러브": "SV",
}
# 대명사·후속질문으로 직전 맥락의 구종을 가리키는 표현.
REFERENCE_WORDS = ["저게", "그게", "그럼", "그 공", "방금", "이거", "그거", "아까", "저거"]

# focus_type을 정하는 키워드 - 여기서 정하는 건 "어떤 근거를 볼지"까지다. 실제 문장은
# _generate_fallback_answer/LLM 프롬프트가 evidence와 조합해 매번 새로 만든다.
REPETITION_COMPLAINT_KEYWORDS = ["같은 말", "아까랑 똑같", "아까와 똑같", "또 그 말", "똑같이 말해", "왜 같은 말", "반복해", "또 같은", "다르게 설명"]
COACH_PERSONA_KEYWORDS = ["코치님처럼", "코치처럼", "코치같이", "코치 말투", "코치님 말투"]
SCORE_SITUATION_KEYWORDS = [
    "지고 있으면", "지고있으면", "이기고 있으면", "이기고있으면", "박빙이면", "점수차 나면",
    "리드하면", "지고 있는데", "이기고 있는데", "점수 상황",
]
STRONG_PITCH_KEYWORDS = ["강해서", "강한 거", "강한거", "강하지", "강하잖아"]
WEAK_PITCH_KEYWORDS = ["약한 거", "약한거", "약해서", "약하지", "약하잖아"]
NEGATION_KEYWORDS = [
    "안 던지는", "안 던져야", "말아야", "안 하는 게", "쓰지 말", "빼는 게", "던지지 말", "버려", "버려야",
]
INSIDE_OUTSIDE_KEYWORDS = ["안쪽", "몸쪽", "바깥쪽", "인코스", "아웃코스", "높은 쪽", "낮은 쪽"]
EXTRA_BASE_RISK_KEYWORDS = [
    "컨택", "맞으면", "맞이면", "맞아버리", "안 빠지면", "실투", "몰리면", "가운데로", "얻어맞", "맞을",
    "장타", "홈런",
]
VELOCITY_KEYWORDS = ["구속", "전력으로", "전력투구", "세게 던져", "최고 구속", "강하게 던져", "풀스윙"]
OPPONENT_PATTERN_KEYWORDS = [
    "던질까", "던질 거야", "던질 것 같아", "패턴", "계속 던지", "또 던지", "분석해", "약점이 뭐", "약점 뭐",
    "강점이 뭐", "강점 뭐", "어떤 타입", "어떤 스타일", "공략법",
]
BATTER_SWING_KEYWORDS = ["노려", "노릴", "공략", "쳐야", "노려도", "스윙", "배트가 나가", "배트 나가"]
TARGET_ZONE_ASK_KEYWORDS = ["뭘 노릴", "무엇을 노릴", "노릴지", "노릴 코스", "뭘 노려"]

FOCUS_LABEL_KR = {
    "repetition_complaint": "답변 반복 지적", "coach_persona": "코치 페르소나 요청",
    "score_situation": "점수 상황 전략", "matchup_strength": "특정 구종 강약 확인",
    "pitch_exclusion": "구종 배제 여부", "zone_adjustment": "코스(안쪽/바깥쪽) 전략",
    "extra_base_risk": "장타/컨택 위험", "velocity": "구속/투구 강도",
    "opponent_pattern": "상대 선수 패턴/약점", "batter_swing_decision": "스윙 여부 판단",
    "recommendation": "전반적인 추천 근거",
}

_COACHING_RECAP_RE = re.compile(r"\s*코칭으로 정리하면\s*:?\s*")


def _soften_answer(answer: str) -> str:
    """"코칭으로 정리하면:" 같은 고정 리캡 문구를 제거한다. 뒤따르는 문장이 이미 요약
    역할을 하므로 태그만 떼도 자연스러운 마지막 문장으로 남는다."""
    return _COACHING_RECAP_RE.sub(" ", answer).strip()


def _extract_text_content(content) -> str:
    """Gradio 6 Chatbot(messages 포맷)은 컴포넌트 왕복 후 각 메시지 content를 문자열이 아닌
    [{"text": ..., "type": "text"}] 파츠 리스트로 바꾼다 - 이걸 그대로 문자열로 다루면
    후속 질문에서 죽으므로, 문자열/파츠 리스트/객체/None을 모두 안전하게 문자열로 변환한다."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    parts.append(text_val)
            else:
                text_attr = getattr(part, "text", None)
                if isinstance(text_attr, str):
                    parts.append(text_attr)
        return " ".join(parts)
    if isinstance(content, dict):
        text_val = content.get("text")
        return text_val if isinstance(text_val, str) else ""
    text_attr = getattr(content, "text", None)
    return text_attr if isinstance(text_attr, str) else str(content)


def _normalize_history(history) -> list[dict]:
    """history를 항상 [{"role": "user"/"assistant", "content": "문자열"}, ...]로 정규화한다.
    Gradio 6 messages 포맷, 과거 "tuples" 포맷((user, bot) 튜플), None을 모두 받아들인다."""
    normalized: list[dict] = []
    if not history:
        return normalized
    for turn in history:
        if isinstance(turn, dict):
            role = turn.get("role") or "user"
            normalized.append({"role": role, "content": _extract_text_content(turn.get("content"))})
        elif isinstance(turn, (list, tuple)) and len(turn) == 2:
            user_msg, bot_msg = turn
            if user_msg:
                normalized.append({"role": "user", "content": _extract_text_content(user_msg)})
            if bot_msg:
                normalized.append({"role": "assistant", "content": _extract_text_content(bot_msg)})
    return normalized


class CoachAgent:
    def __init__(self, ollama_host: str = OLLAMA_HOST, ollama_model: str = OLLAMA_MODEL):
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model

    # ------------------------------------------------------------------
    # 공개 진입점
    # ------------------------------------------------------------------
    def answer(self, message: str, history: list | None, analysis_result: dict | None) -> dict:
        analysis_result = analysis_result or {}
        norm_history = _normalize_history(history)
        conv_state = self._build_conversation_state(message, norm_history, analysis_result)
        intent = self._classify_user_intent(message or "")
        focus = self._extract_question_focus(message or "", norm_history, analysis_result)
        evidence = self._build_evidence_pack(analysis_result)

        answer_text, source = self._generate_coach_response(message or "", focus, evidence, conv_state)
        answer_text, was_repetitive = self._anti_repetition_check(
            answer_text, conv_state, focus, evidence, message or "", source,
        )
        answer_text = _soften_answer(answer_text)

        return {
            "answer": answer_text,
            "source": source,
            "intent": intent,
            "focus": {
                "focus_type": focus["focus_type"],
                "mentioned_pitch": focus.get("mentioned_pitch"),
                "mentioned_zone": focus.get("mentioned_zone"),
                "user_concern": focus.get("user_concern"),
                "anti_repetition_triggered": was_repetitive,
            },
            "used_context": [],
        }

    # ------------------------------------------------------------------
    # 1. history 정규화는 모듈 함수(_normalize_history)로 answer() 진입 시 처리한다.
    # 2. 대화 상태
    # ------------------------------------------------------------------
    def _build_conversation_state(self, message: str, history: list[dict], analysis_result: dict) -> dict:
        pitcher_result = analysis_result.get("pitcher_mode_result")
        batter_result = analysis_result.get("batter_mode_result")
        mode = analysis_result.get("mode") or ("pitcher" if pitcher_result else "batter" if batter_result else None)
        last_user_question, last_assistant_answer = None, None
        for turn in reversed(history):
            if last_assistant_answer is None and turn.get("role") == "assistant":
                last_assistant_answer = turn.get("content") or None
            elif last_user_question is None and turn.get("role") == "user":
                last_user_question = turn.get("content") or None
            if last_user_question and last_assistant_answer:
                break
        return {
            "mode": mode,
            "last_user_question": last_user_question,
            "last_assistant_answer": last_assistant_answer,
            "turn_count": len(history) // 2,
        }

    # ------------------------------------------------------------------
    # 3. 대화 의도 분류 (거친 카테고리 - focus_type을 정하는 데만 참고)
    # ------------------------------------------------------------------
    def _classify_user_intent(self, message: str) -> str:
        if any(k in message for k in REPETITION_COMPLAINT_KEYWORDS):
            return "complaint"
        if any(k in message for k in COACH_PERSONA_KEYWORDS):
            return "persona"
        return "question"

    # ------------------------------------------------------------------
    # 4. 질문 초점 추출 - 여기서 뽑은 focus에 답변이 반드시 직접 대응해야 한다.
    # ------------------------------------------------------------------
    def _mentioned_pitches(self, text: str) -> list[str]:
        found: list[str] = []
        upper = text.upper()
        for label in KNOWN_PITCH_LABELS:
            if label in upper and label not in found:
                found.append(label)
        for kr, label in PITCH_KR_ALIASES.items():
            if kr in text and label not in found:
                found.append(label)
        return found

    def _resolve_reference_pitch(self, text: str, history: list[dict]) -> str | None:
        if not any(k in text for k in REFERENCE_WORDS):
            return None
        for turn in reversed(history):
            found = self._mentioned_pitches(turn.get("content", ""))
            if found:
                return found[-1]
        return None

    def _mentioned_zone(self, text: str) -> str | None:
        if any(k in text for k in ["안쪽", "몸쪽", "인코스"]):
            return "inside"
        if any(k in text for k in ["바깥쪽", "아웃코스"]):
            return "outside"
        if "높은" in text:
            return "high"
        if "낮은" in text:
            return "low"
        return None

    def _extract_question_focus(self, text: str, history: list[dict], analysis_result: dict) -> dict:
        pitcher_result = analysis_result.get("pitcher_mode_result")
        explicit_mentions = self._mentioned_pitches(text)
        mentioned_pitch = explicit_mentions[0] if explicit_mentions else None
        reference_pitch = self._resolve_reference_pitch(text, history)
        mentioned_zone = self._mentioned_zone(text)

        # 우선순위: 명시적 불만/페르소나 -> 점수 상황 -> 구종 강약 확인 -> 배제 여부
        # -> 코스 전략 -> 장타 위험 -> 구속 -> 상대 패턴 -> 스윙 여부 -> 일반.
        if any(k in text for k in REPETITION_COMPLAINT_KEYWORDS):
            focus_type = "repetition_complaint"
        elif any(k in text for k in COACH_PERSONA_KEYWORDS):
            focus_type = "coach_persona"
        elif any(k in text for k in SCORE_SITUATION_KEYWORDS):
            focus_type = "score_situation"
        elif mentioned_pitch and any(k in text for k in STRONG_PITCH_KEYWORDS + WEAK_PITCH_KEYWORDS):
            focus_type = "matchup_strength"
        elif any(k in text for k in NEGATION_KEYWORDS):
            focus_type = "pitch_exclusion"
        elif mentioned_zone and any(k in text for k in INSIDE_OUTSIDE_KEYWORDS):
            focus_type = "zone_adjustment"
        elif any(k in text for k in EXTRA_BASE_RISK_KEYWORDS):
            focus_type = "extra_base_risk"
        elif any(k in text for k in VELOCITY_KEYWORDS):
            focus_type = "velocity"
        elif any(k in text for k in OPPONENT_PATTERN_KEYWORDS):
            focus_type = "opponent_pattern"
        elif any(k in text for k in BATTER_SWING_KEYWORDS):
            focus_type = "batter_swing_decision"
        else:
            focus_type = "recommendation"

        fallback_pitch = (
            mentioned_pitch or reference_pitch
            or (pitcher_result.get("recommended_pitch") if pitcher_result else None)
        )
        explicit_ask = "target_zone" if any(k in text for k in TARGET_ZONE_ASK_KEYWORDS) else None
        user_concern = FOCUS_LABEL_KR.get(focus_type, focus_type)
        if mentioned_pitch:
            user_concern = f"{pitch_label_kr(mentioned_pitch)} 관련 {user_concern}"

        return {
            "focus_type": focus_type,
            "mentioned_pitch": mentioned_pitch,
            "reference_pitch": reference_pitch,
            "fallback_pitch": fallback_pitch,
            "mentioned_zone": mentioned_zone,
            "explicit_ask": explicit_ask,
            "user_concern": user_concern,
            "has_variety_word": "변화구" in text,
        }

    # ------------------------------------------------------------------
    # 5. evidence pack - analysis_result에서 근거만 추출
    # ------------------------------------------------------------------
    def _build_evidence_pack(self, analysis_result: dict) -> dict:
        pitcher_result = analysis_result.get("pitcher_mode_result")
        batter_result = analysis_result.get("batter_mode_result")
        mode = analysis_result.get("mode") or ("pitcher" if pitcher_result else "batter" if batter_result else None)
        context = analysis_result.get("game_context") or {}
        top3 = analysis_result.get("predicted_top3_pitches") or []
        risk_summary = analysis_result.get("risk_summary") or {}

        pack: dict = {"mode": mode}
        if context:
            pack["count"] = f"{context.get('balls')}B-{context.get('strikes')}S"
            pack["runners"] = [
                label for label, on in
                [("1루", context.get("on_1b")), ("2루", context.get("on_2b")), ("3루", context.get("on_3b"))] if on
            ] or "없음"
            pack["score_diff"] = context.get("score_diff")
        if analysis_result.get("score_situation_label"):
            pack["score_situation"] = analysis_result["score_situation_label"]
        if top3:
            pack["top3"] = [
                {"pitch": i["pitch_label"], "pitch_kr": pitch_label_kr(i["pitch_label"]), "probability": round(i["probability"], 3)}
                for i in top3
            ]
        if risk_summary:
            pack["risk_summary"] = {k: round(v, 3) for k, v in risk_summary.items() if isinstance(v, (int, float))}
        if pitcher_result:
            recommended = pitcher_result.get("recommended_pitch")
            avoid = pitcher_result.get("avoid_pitch")
            pack["recommended_pitch"] = recommended
            pack["recommended_pitch_kr"] = pitch_label_kr(recommended) if recommended else None
            pack["avoid_pitch"] = avoid
            pack["avoid_pitch_kr"] = pitch_label_kr(avoid) if avoid else None
            pack["best_zone_cell"] = pitcher_result.get("best_zone_cell")
            pack["batter_weakness"] = pitcher_result.get("batter_weakness")
            pack["pitch_risk_details"] = analysis_result.get("pitch_risk_details") or {}
        if batter_result:
            pack["target_zone"] = batter_result.get("target_zone")
            pack["target_zone_cell"] = batter_result.get("target_zone_cell")
            pack["pitcher_pattern"] = batter_result.get("pitcher_pattern")
            pack["counter_strategy"] = batter_result.get("counter_strategy")
            pack["expected_top3_pitches"] = batter_result.get("expected_top3_pitches")
        return pack

    # ------------------------------------------------------------------
    # 6. 코치 답변 생성 - Ollama 우선, 실패 시 evidence 기반 동적 fallback
    # ------------------------------------------------------------------
    def _is_ollama_available(self) -> bool:
        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=OLLAMA_AVAILABILITY_TIMEOUT_SECONDS)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _build_prompt(self, message: str, focus: dict, evidence: dict, conv_state: dict, extra_instruction: str = "") -> str:
        mode = conv_state.get("mode")
        perspective = "네가 마운드 위에 있다면" if mode == "pitcher" else "네가 타석에 있다면" if mode == "batter" else "지금 상황이라면"
        state_lines = [
            f"- mode: {mode}",
            f"- last_user_question: {conv_state.get('last_user_question') or '(없음)'}",
            f"- last_assistant_answer: {conv_state.get('last_assistant_answer') or '(없음)'}",
            f"- repeated_topic: {'예' if focus['focus_type'] == 'repetition_complaint' else '아니오'}",
            f"- current_focus: {focus['focus_type']} ({focus.get('user_concern')})",
        ]
        evidence_json = json.dumps(evidence, ensure_ascii=False)
        prompt = (
            "[역할]\n너는 야구 전력분석 코치다. 리포트를 읽어주는 사람이 아니라, 선수와 실시간으로 "
            "대화하는 코치다.\n\n"
            "[대화 원칙]\n"
            "- 사용자의 질문에 먼저 답한다.\n"
            "- 같은 답변을 반복하지 않는다.\n"
            "- 사용자가 불만을 말하면 인정하고 다른 각도로 설명한다.\n"
            "- 답변은 3~6문장.\n"
            "- 자연스러운 말투.\n"
            "- 수치는 필요한 경우 1~2개만.\n"
            "- \"Top-3는\", \"현재 분석 결과는\", \"코칭으로 정리하면\" 같은 고정 문구 금지.\n"
            "- 사용자가 물은 주제와 다른 추천구종 요약 금지.\n"
            f"- {perspective} 관점으로 말한다.\n\n"
            "[현재 대화 상태]\n" + "\n".join(state_lines) + "\n\n"
            f"[근거]\n{evidence_json}\n\n"
            f"[사용자 질문]\n{message}\n\n"
        )
        if extra_instruction:
            prompt += f"[추가 지시]\n{extra_instruction}\n\n"
        prompt += "[답변]\n자연스러운 코치 말투로 답변:"
        return prompt

    def _call_ollama(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.ollama_host}/api/generate",
            json={"model": self.ollama_model, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer_text = resp.json().get("response", "").strip()
        if not answer_text:
            raise ValueError("Ollama 응답이 비어 있음")
        return answer_text

    def _generate_coach_response(self, message: str, focus: dict, evidence: dict, conv_state: dict) -> tuple[str, str]:
        if self._is_ollama_available():
            try:
                prompt = self._build_prompt(message, focus, evidence, conv_state)
                return self._call_ollama(prompt), "ollama"
            except (requests.RequestException, ValueError, KeyError) as exc:
                print(f"[경고] Ollama 답변 생성 실패, evidence 기반 fallback으로 대체: {exc}")
        return self._generate_fallback_answer(message, focus, evidence, conv_state, variant=0), "rule_based"

    # ------------------------------------------------------------------
    # evidence 기반 동적 fallback - focus_type별로 최소 2개 문장 프레임을 두고,
    # 실제 문장은 항상 evidence 값을 꽂아 넣어 매번 새로 조립한다(고정 문장 아님).
    # ------------------------------------------------------------------
    def _generate_fallback_answer(self, message: str, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        focus_type = focus["focus_type"]
        handler = getattr(self, f"_frame_{focus_type}", None)
        if handler is None:
            handler = self._frame_recommendation
        return handler(focus, evidence, conv_state, variant % 2)

    def _frame_velocity(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        pitch_kr = evidence.get("recommended_pitch_kr") or (evidence.get("top3") or [{}])[0].get("pitch_kr")
        if not pitch_kr:
            return "구속 얘기는 투수 모드 분석 결과가 있어야 구체적으로 짚어줄 수 있어."
        if variant == 0:
            return (
                f"전력으로만 갈 필요는 없어. 지금 질문은 구종보다 강도 조절에 가까워. {pitch_kr}라면 "
                "평소 구속 근처에서 95~98% 강도로 던지고, 존 경계 제구를 우선하는 게 좋아. 힘으로 이기려다 "
                "가운데 몰리는 게 더 위험해."
            )
        return (
            f"구속이면 -- 최고 구속을 뽑아내는 것보다 일관된 릴리스가 더 중요해. {pitch_kr} 기준으로 "
            "강하게 던지되 8~90% 수준에서 제구에 집중하는 편이 낫고, 전력투구는 결정구 하나 정도로만 아껴둬."
        )

    def _frame_matchup_strength(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        pitch = focus.get("mentioned_pitch")
        weakness = evidence.get("batter_weakness") or {}
        if not pitch or not weakness:
            return "그 구종에 대한 상대 타자 데이터가 아직 부족해서 확실하게는 말 못 해줘."
        kr = pitch_label_kr(pitch)
        if weakness.get("strong_pitch") == pitch:
            if variant == 0:
                return (
                    f"맞아, 그 포인트를 잘 봤어. 이 타자는 {kr}가 존 안으로 애매하게 들어오면 장타로 "
                    f"연결할 위험이 있어. {kr}를 완전히 못 쓰는 건 아니지만, 지금은 보여주는 공 정도로만 "
                    "쓰고 승부구는 다른 구종으로 가는 게 안전해."
                )
            return f"그렇게 볼 수 있어 - {kr}는 이 타자한테 강점 쪽에 가까운 구종이라, 승부구보다는 유인구로 아껴두는 게 나아."
        if weakness.get("weak_pitch") == pitch:
            if variant == 0:
                return f"아니, 오히려 반대야 - 데이터상 이 타자는 {kr}에 헛스윙이 많아. 승부구로 {kr}를 가져가도 괜찮아."
            return f"그건 아니야, {kr}는 이 타자한테 약점 쪽이라 자신 있게 결정구로 써도 돼."
        return f"{kr} 단독으로는 이 타자 표본이 뚜렷하지 않아서 확실하게 말하긴 어려워, 다른 강점/약점 구종부터 챙기는 게 나아."

    def _frame_pitch_exclusion(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        pitch = focus.get("mentioned_pitch") or focus.get("reference_pitch")
        recommended = evidence.get("recommended_pitch")
        avoid = evidence.get("avoid_pitch")
        if pitch:
            kr = pitch_label_kr(pitch)
            if pitch == recommended:
                return (
                    f"아니, 완전히 뺄 필요는 없어. {kr}는 지금 데이터에서도 여전히 1순위야. 다만 계속 "
                    "같은 공만 쓰면 읽히니까, 결정구 하나만 다른 구종으로 바꿔주는 정도면 충분해."
                )
            if pitch == avoid:
                return f"그 말 맞아, {kr}는 지금 상황에서는 굳이 승부구로 안 쓰는 게 나아. 오늘은 접어두고 다른 구종으로 승부해."
            if variant == 0:
                return f"완전히 배제할 정도는 아니야. {kr}가 최우선 선택은 아니지만, 상황 봐가면서 섞을 여지는 있어."
            return f"{kr} 하나만 보고 판단하기보다는, 지금 노려야/써야 할 건 따로 있어서 그쪽을 먼저 봐야 해."
        if focus.get("has_variety_word") or "변화구" in (conv_state.get("last_user_question") or ""):
            target = evidence.get("target_zone")
            if target:
                return f"변화구를 아예 버릴 필요는 없어. 지금 노려야 할 건 {target} 쪽이니까, 변화구가 그 코스로 안 오면 흘려보내고 거기만 집중해."
            return "변화구를 완전히 버릴 필요는 없어. 다만 낮게 완전히 빠지는 공까지 따라가는 건 손해니까, 존 안으로 오는 것만 반응해."
        return "구체적으로 어떤 구종을 말하는지 확실치 않아서, 콕 집어서 다시 물어봐주면 정확히 짚어줄게."

    def _frame_zone_adjustment(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        zone = focus.get("mentioned_zone")
        best_cell = evidence.get("best_zone_cell")
        walk_risk = (evidence.get("risk_summary") or {}).get("walk_risk")
        if zone == "inside":
            if variant == 0:
                return (
                    "그 말 맞아, 안쪽을 노리다 빠지면 몸에 맞는 공이나 볼넷으로 이어질 위험이 있어. "
                    f"다만 지금 추천 존은 zone_cell {best_cell}번 쪽이니까, 거기서 반 개 정도만 안쪽으로 "
                    "조절하고 완전히 몸쪽 깊숙이 넣지는 마."
                )
            return "맞아, 안쪽 승부는 리스크가 있어 - 대신 완전히 존을 벗어나는 것보다 경계선까지만 붙이는 정도로 타협해."
        if zone == "outside":
            walk_note = f"지금 볼넷 위험은 {walk_risk:.1%} 정도야." if walk_risk is not None else ""
            return f"맞아, 바깥쪽으로 완전히 빠지면 볼넷 위험이 커지는 건 사실이야. {walk_note} 그래도 안쪽보다 장타로 이어질 확률은 낮은 코스라 존 경계 정도까지는 써도 괜찮아."
        return f"코스 얘기면, 지금 추천 존은 zone_cell {best_cell}번 근처야. 거기서 크게 벗어나지 않는 선에서 조절하면 돼."

    def _frame_extra_base_risk(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        risk = evidence.get("risk_summary") or {}
        extra_base = risk.get("extra_base_hit_risk")
        pitch = focus.get("fallback_pitch")
        pitch_kr = pitch_label_kr(pitch) if pitch else None
        detail = (evidence.get("pitch_risk_details") or {}).get(pitch) if pitch else None
        if detail:
            eb = detail.get("extra_base_hit_risk")
            if variant == 0:
                return (
                    f"장타 걱정은 맞아. 지금 봐야 할 건 구종 이름보다 몰리는 위치야. {pitch_kr}가 추천됐어도 "
                    f"가운데로 들어가면 장타 위험이 {eb:.1%}까지 올라가고, 존 경계 쪽으로 붙이면 리스크가 줄어. "
                    "세게 던지는 것보다 코스가 먼저야."
                )
            return f"그 걱정 맞아 - {pitch_kr}는 존 가운데로 몰리는 순간 장타 위험이 {eb:.1%}로 뛰니까, 존 안으로 자신 있게 넣기보다 경계선을 정확히 노리는 게 우선이야."
        if extra_base is not None:
            return f"장타 위험은 지금 {extra_base:.1%} 정도야. 수치 자체보다 어디로 몰리느냐가 더 크게 작용하니까, 코스 관리에 집중하는 게 맞아."
        return "장타 쪽 데이터가 아직 부족해서 확실하게는 말 못 해줘. 다만 존 가운데로 몰리는 것만 피해도 위험은 크게 줄어."

    def _frame_score_situation(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        label = evidence.get("score_situation")
        mode = conv_state.get("mode")
        if not label:
            return "점수 상황 데이터가 없어서 정확히는 답하기 어려워. 스코어를 입력하고 다시 물어봐줘."
        walk_risk = (evidence.get("risk_summary") or {}).get("walk_risk")
        walk_note = f" 볼넷 위험은 지금 {walk_risk:.1%} 정도라 아주 위험한 수준은 아니야." if walk_risk is not None and walk_risk < 0.35 else ""
        if mode == "pitcher":
            if label in ("열세", "큰 점수차") and variant == 0:
                return f"지금 {label} 상황이긴 한데, 오히려 더 침착하게 가야 해. 쫓기는 마음에 무리하게 존 안으로 몰면 장타 한 방에 더 크게 밀릴 수 있어.{walk_note} 볼넷 하나보다 장타 한 방이 더 아프니까 위험한 코스부터 피해."
            return f"지금은 {label} 상황이야. 극단적으로 몰아붙이기보다 위험한 코스만 피하면서 기본대로 가는 게 안전해.{walk_note}"
        if label in ("열세", "큰 점수차"):
            return f"맞아, 지금 {label} 상황이면 좀 더 적극적으로 나가야 해 - 출루보다 한 방이 아쉬운 상황이야. 노릴 코스에 확신 있으면 초구부터 과감하게 스윙해도 좋아."
        return f"지금은 {label} 상황이라 극단적으로 갈 필요는 없어. 노릴 코스 기본대로 가도 충분해."

    def _frame_opponent_pattern(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        mode = conv_state.get("mode")
        if mode == "batter":
            pattern = evidence.get("pitcher_pattern") or {}
            top_pitches = pattern.get("top_pitches") or []
            if not top_pitches:
                return "상대 투수 데이터가 아직 부족해서 패턴을 콕 짚어주긴 어려워. 일단 Top-3 확률 위주로 타이밍 잡으면 돼."
            main = top_pitches[0]
            main_kr = pitch_label_kr(main["pitch_label"])
            if variant == 0:
                return f"지금 데이터로는 이 투수가 {main_kr} 비중이 {main['ratio']:.0%}로 높아서 계속 그 구종 위주로 갈 가능성이 커. 네가 타석에 있다면 {main_kr} 타이밍에 먼저 맞춰놓는 게 좋아."
            return f"완전히 확신할 순 없지만, {main_kr} 쪽 구사 비율이 {main['ratio']:.0%}로 제일 높으니까 그쪽에 기본 타이밍을 맞춰두는 게 안전해."
        weakness = evidence.get("batter_weakness") or {}
        if not weakness.get("weak_pitch"):
            return "이 타자는 아직 표본이 부족해서 확실한 약점을 짚어주긴 어려워."
        weak_kr = pitch_label_kr(weakness["weak_pitch"])
        return f"이 타자는 {weak_kr} 계열에 헛스윙이 많은 편이야. 네가 투수라면 그 구종을 결정구로 가져가는 게 좋아."

    def _frame_batter_swing_decision(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        target = evidence.get("target_zone")
        expected = evidence.get("expected_top3_pitches") or []
        if not target:
            return "지금은 타자 모드 데이터가 없어서 정확히는 못 짚어줘. 타자 모드로 분석을 돌리면 바로 짚어줄게."
        prob_note = f" 확률로도 {expected[0]['probability']:.0%} 정도로 제일 유력해." if expected else ""
        if variant == 0:
            return f"{target} 쪽으로 오는 공이면 노려도 좋아.{prob_note} 그 코스가 아니면 억지로 따라가지 마 - 존을 벗어나는 유인구에 배트 나가는 게 제일 손해야."
        return f"무조건 쳐야 하는 공은 아니야. {target} 쪽으로 확실히 들어올 때만 강하게 반응하고, 애매하면 침착하게 지켜보는 게 나아."

    def _frame_coach_persona(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        mode = conv_state.get("mode")
        if mode == "pitcher":
            recommended = evidence.get("recommended_pitch_kr")
            avoid = evidence.get("avoid_pitch_kr")
            avoid_line = f" 반대로 {avoid}는 지금은 자신 있게 던질 공이 아니니까 승부구로 쓰지 마." if avoid else ""
            return f"오케이, 코치처럼 말하면 지금은 무리해서 보여주는 공보다 타자가 못 건드리는 코스를 먼저 봐야 해. 데이터상으로는 {recommended}가 1순위지만, 그게 무조건 정면승부하란 뜻은 아니야.{avoid_line}"
        target = evidence.get("target_zone")
        if target:
            return f"오케이, 코치처럼 말하면 지금은 아무 공에나 배트 내밀 타이밍이 아니야. {target} 쪽으로 올 가능성이 높으니까 거기에 타이밍을 맞춰놓고, 그 외에는 침착하게 지켜봐."
        return "분석을 먼저 실행해줘야 코치답게 짚어줄 수 있어."

    def _frame_repetition_complaint(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        if focus.get("explicit_ask") == "target_zone":
            target = evidence.get("target_zone")
            if target:
                return f"맞아, 방금은 같은 결론만 반복했네. 이번엔 구종 얘기 말고 노릴 곳만 짚을게 - {target} 쪽이야."
            recommended = evidence.get("recommended_pitch_kr")
            if recommended:
                return f"맞아, 같은 말이 반복됐네. 이번엔 딱 하나만 - 지금 노릴 건 {recommended} 계열이야."
        mode = conv_state.get("mode")
        if mode == "pitcher":
            avoid = evidence.get("avoid_pitch_kr")
            return f"맞아, 방금은 너무 같은 결론으로 반복됐어. 추천 구종 말고 다른 관점으로 볼게 - 지금은 위험 구종({avoid or '몰리는 코스'})을 피하는 쪽에 더 신경 써야 해."
        pattern = evidence.get("pitcher_pattern") or {}
        return f"맞아, 답변이 반복됐네. 구종 말고 상대 투수 패턴 쪽으로 다시 볼게 - {pattern.get('summary', '뚜렷한 쏠림이 있는 편이야')}."

    def _frame_recommendation(self, focus: dict, evidence: dict, conv_state: dict, variant: int) -> str:
        mode = conv_state.get("mode")
        if mode == "pitcher":
            recommended = evidence.get("recommended_pitch_kr")
            avoid = evidence.get("avoid_pitch_kr")
            if not recommended:
                return "아직 분석을 안 돌렸네. 먼저 분석 버튼을 눌러주면 그때부터 제대로 짚어줄게."
            if variant == 0:
                return f"지금은 {recommended} 위주로 가는 게 맞아. 예측 확률뿐 아니라 구사 비율, 상대 타자 약점, 위험도까지 같이 본 결과라 근거는 탄탄해." + (f" 반대로 {avoid}는 오늘은 승부구로 피하는 게 좋아." if avoid else "")
            return f"결론부터 말하면 {recommended}가 지금 가장 안전한 선택이야." + (f" {avoid}는 아직 자신 있게 던질 공이 아니라서 아껴둬." if avoid else "")
        target = evidence.get("target_zone")
        expected = evidence.get("expected_top3_pitches") or []
        if not target:
            return "아직 분석을 안 돌렸네. 먼저 분석 버튼을 눌러주면 그때부터 제대로 짚어줄게."
        top_note = f" {pitch_label_kr(expected[0]['pitch_label'])} 계열이 확률로도 제일 유력해." if expected else ""
        return f"네가 타석에 있다면, 지금은 {target} 쪽을 노려야 해.{top_note}"

    # ------------------------------------------------------------------
    # 7. 반복 검사 - Jaccard 유사도 + 같은 시작 문장을 본다. 반복이면 rule_based는
    # 다른 관점(pivot) 프레임으로, ollama는 한 번 더 "반복하지 마라"는 지시를
    # 덧붙여 재생성한다.
    # ------------------------------------------------------------------
    def _is_repetitive(self, new_answer: str, last_answer: str | None) -> bool:
        if not last_answer:
            return False
        a, b = set(new_answer.split()), set(last_answer.split())
        if not a or not b:
            return False
        overlap = len(a & b) / len(a | b)
        if overlap >= 0.55:
            return True
        return new_answer.strip()[:12] == last_answer.strip()[:12]

    def _anti_repetition_check(
        self, answer_text: str, conv_state: dict, focus: dict, evidence: dict, message: str, source: str,
    ) -> tuple[str, bool]:
        last_answer = conv_state.get("last_assistant_answer")
        if not self._is_repetitive(answer_text, last_answer):
            return answer_text, False

        if source == "ollama":
            try:
                retry_prompt = self._build_prompt(
                    message, focus, evidence, conv_state,
                    extra_instruction=(
                        "방금 생성한 답이 직전 답변과 거의 똑같았다. 절대 같은 문장/결론을 반복하지 말고, "
                        f"이번 질문의 초점인 '{focus.get('user_concern')}'에만 집중해서 완전히 다른 각도로 다시 답해라. "
                        "추천 구종 요약으로 돌아가지 마라."
                    ),
                )
                retried = self._call_ollama(retry_prompt)
                if not self._is_repetitive(retried, last_answer):
                    return retried, True
            except (requests.RequestException, ValueError, KeyError) as exc:
                print(f"[경고] 반복 감지 후 Ollama 재생성 실패, 동적 fallback으로 대체: {exc}")

        pivot = self._frame_repetition_complaint(focus, evidence, conv_state, variant=1)
        return pivot, True
