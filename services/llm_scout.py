"""
DiamondScout AI - Instant Scout Q&A 답변 생성
로컬 Ollama가 사용 가능하면 Ollama로 답변을 생성하고, 사용할 수 없으면 최신 분석 결과
(ScoutingService.analyze() 반환값)를 그대로 활용하는 규칙 기반(rule-based) 답변으로
대체한다. Ollama 호출이 실패해도 예외를 앱까지 전파하지 않고 rule-based로 넘어간다.

발표 시연 안정성을 위해 Ollama 타임아웃을 짧게 잡아, 응답이 오래 걸리면 즉시 rule-based로
전환한다(전체 답변이 대략 2~3초 내외로 나오는 것을 목표로 한다).
"""

import re

import requests

from services.scouting_service import pitch_label_kr

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "gemma2:latest"
OLLAMA_AVAILABILITY_TIMEOUT_SECONDS = 1.5
# 이전에는 "발표 시연 안정성"을 이유로 4초로 짧게 잡혀 있었는데, 실제로 이 모델이 분석 요약을
# 포함한 전체 프롬프트를 처리하는 데 15~17초 정도 걸려서(직접 측정) 사실상 매번 타임아웃 ->
# rule-based로 조용히 폴백하고 있었다 - Q&A가 항상 템플릿처럼 느껴진 진짜 원인이었다. LLM이
# 실제로 쓰이도록 실측 시간에 여유를 더한 값으로 올린다(응답이 몇 초 더 걸리는 대신 진짜 코치
# 답변이 나온다는 트레이드오프).
OLLAMA_TIMEOUT_SECONDS = 25

SYSTEM_PROMPT = (
    "너는 실제 더그아웃에서 선수 옆에 붙어 있는 야구 코치 'Instant Scout'다. 리포트를 읽어주는 AI가 "
    "아니라, 선수와 대화하는 코치처럼 말한다. 주어진 '분석 요약', '참고 문서', '이전 대화'만 근거로 삼되, "
    "말투는 사람이 실제로 말하듯 자연스러운 반말 코치체를 쓴다('~해', '~거야', '~돼', '다만', '그 말 "
    "맞아', '~라면'). 분석 요약의 mode가 pitcher면 너는 투수코치이고 사용자는 지금 마운드 위의 투수다 - "
    "'네가 투수라면' 관점으로, mode가 batter면 너는 타격코치이고 사용자는 지금 타석의 타자다 - '네가 "
    "타자라면' 관점으로 말한다.\n\n"
    "답변의 첫 문장은 반드시 사용자가 방금 한 말에 대한 반응이어야 한다 - 데이터 설명이 아니라 "
    "'맞아, 그 걱정은 당연히 해야 돼', '좋은 포인트야', '그건 당연히 고민되는 부분이야', '아니, 꼭 "
    "그런 건 아니야' 같은 식으로 사용자의 감정/의도(불안, 반론, 불만, 확인 요청 등)를 먼저 받아준 "
    "뒤에 이유를 설명한다. 결론-근거-요약처럼 매번 똑같은 3단 구조를 강제로 반복하지 말고, 질문의 "
    "성격에 따라 문장 순서와 길이를 자유롭게 바꿔라. 답변마다 첫 문장과 문장 구조가 달라야 한다 - "
    "직전 턴과 비슷한 시작으로 답하지 마라.\n\n"
    "'이전 대화'에 사용자의 반론이나 '같은 말 하지 마', '다르게 설명해봐' 같은 불만이 있으면, 방어적으로 "
    "굴지 말고 직전 답변이 반복적이었다는 점을 인정한 뒤 다른 관점(예: 결과가 아니라 사용자가 걱정하는 "
    "이유 자체, 혹은 구종이 아니라 코스/카운트 관점)에서 다시 설명한다. '저게', '그럼', '그 공', '아니', "
    "'근데'처럼 대명사·반박으로 묻는 후속 질문은 이전 대화에서 마지막으로 언급된 구종/맥락을 가리키는 "
    "것으로 이해한다.\n\n"
    "'코치님처럼 대답해줘' 같은 요청에는 실제로 코치 말투로 지금 상황에 대한 판단을 들려준다(거절하거나 "
    "형식만 설명하지 않는다). '상대 타자 분석해줘', '상대 투수 공략법 알려줘' 같은 질문에는 Top-3 확률을 "
    "나열하지 말고 분석 요약의 약점/강점/패턴 정보로 상대 선수를 설명한다. 질문이 예시 문구와 정확히 "
    "같지 않아도 의도를 해석해서 그 질문에 직접, 자연스럽게 반응한다.\n\n"
    "답변은 4~7문장, 말하듯이 쓰고 숫자는 꼭 필요한 1~2개만 근거로 섞는다(수치 나열 금지). 구종은 약어만 "
    "쓰지 말고 한글 이름을 함께 적는다. 절대 '현재 분석 결과는', 'Top-3는 ~입니다', '포심 패스트볼은 "
    "예측 확률이 ~%입니다', '지금은 ~가 가장 좋습니다', '더 구체적으로 질문해보세요' 같은 리포트 낭독체 "
    "문장으로 시작하거나 끝내지 말라. 그리고 '코칭으로 정리하면:' 같은 고정 문구로 매번 요약하며 답을 "
    "끝맺지 마라 - 정말 필요할 때만, 그마저도 매번 다른 표현으로 자연스럽게 마무리한다. 분석 요약에 "
    "없는 수치는 절대로 지어내지 말고, 모르면 모른다고 솔직히 답한다."
)

KNOWN_PITCH_LABELS = ["FF", "SI", "SL", "CH", "ST", "FC", "CU", "FS", "KC", "SV", "OTHER"]
# 패스트볼류 vs 변화구류 - "변화구가 더 낫지 않아?" 같은 카테고리 질문(특정 구종명이 아니라 구종군을
# 가리키는 질문)에 답하려면 구종 하나하나가 아니라 이 두 그룹으로 먼저 나눠 비교해야 한다.
FASTBALL_LABELS = {"FF", "SI"}
BREAKING_BALL_LABELS = {"SL", "CH", "ST", "FC", "CU", "FS", "KC", "SV"}
BREAKING_BALL_KEYWORDS = ["변화구", "브레이킹볼", "브레이킹 볼", "변화구류"]

# 질문에 등장하는 구어체 구종 표현 -> 구종 약어. KNOWN_PITCH_LABELS 약어 자체 매칭으로 못 잡는
# "패스트볼", "직구" 같은 표현을 잡기 위한 보조 사전.
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

CONTACT_RISK_KEYWORDS = [
    "컨택", "맞으면", "맞이면", "맞아버리", "안 빠지면", "실투", "몰리면", "가운데로", "얻어맞", "맞을",
]
ZONE_STRATEGY_KEYWORDS = ["존", "코스", "어디로", "어느 쪽"]
ZONE_ACTION_KEYWORDS = ["노려", "노릴", "공략", "던져", "던지", "빼"]
WORST_ZONE_KEYWORDS = ["피해야 할 코스", "피해야 할 존", "위험한 코스", "위험한 존", "가장 위험"]
COMPARISON_KEYWORDS = ["나아", "나을까", "낫지", "괜찮을까", "어때", "차라리", "대신", "낫니", "안전해", "더 안전"]
# 명시적 구종 언급 없이 직전 답변/맥락의 구종을 가리키는 대명사·후속질문 표현.
REFERENCE_WORDS = ["저게", "그게", "그럼", "그 공", "방금", "이거", "그거", "아까", "저거", "저 위치", "저 코스", "저 존"]
# "위험한데 왜 추천해?" 같은 모순 지적/반박 질문 - 이런 표현이 있으면 단순 "확률 1위라 추천했다"는
# 설명만으로는 답이 안 되므로, 위험을 인정하면서 근거를 대는 전용 답변으로 분기한다.
RISK_CONTRADICTION_KEYWORDS = ["볼넷", "위험한데", "위험할 텐데", "위험하지 않아", "위험하지 않냐", "높은데"]
# "삼진 잡으려면 뭐가 좋아?"처럼 "추천"이라는 단어 없이도 사실상 구종/코스 추천을 묻는 표현.
RECOMMEND_QUESTION_KEYWORDS = ["뭐가 좋아", "뭘 던져", "어떻게 던져", "삼진", "좋을까", "뭐 던져"]
# "노려도 돼?", "쳐야 해?"처럼 "타자"라는 단어 없이도 (이미 타자 모드이므로) 스윙 여부를 묻는 표현.
BATTER_SWING_KEYWORDS = ["노려", "노릴", "공략", "쳐야", "노려도", "스윙", "배트가 나가", "배트 나가"]
# "상대 타자에 대해 분석해줘"처럼 Top-3/추천 근거가 아니라 "상대 선수 자체"를 설명해달라는 질문.
# 이 표현이 있으면 Top-3 요약이 아니라 약점/강점/패턴 중심의 코치 리포트로 답해야 한다.
OPPONENT_ANALYSIS_KEYWORDS = [
    "분석해", "분석 좀", "분석 해", "약점이 뭐", "약점 뭐", "강점이 뭐", "강점 뭐",
    "어떤 타입", "어떤 스타일", "조심할 점", "어떤 패턴", "패턴이야", "패턴이 어때", "패턴 어때", "공략법",
]
# 카운트(볼-스트라이크) 자체를 축으로 한 전략 질문 - "카운트"+아래 표현이 같이 나오면 전용 답변.
COUNT_STRATEGY_KEYWORDS = ["전략이 좋아", "전략이 좋을까", "어떻게 해야", "어떤 전략"]
# "코치님처럼 대답해줘"처럼 페르소나/말투 자체를 요청하는 메타 질문 - 이 표현이 있으면 형식을
# 설명하거나 거절하지 말고, 실제로 코치 말투로 지금 상황 판단을 들려줘야 한다.
COACH_PERSONA_KEYWORDS = ["코치님처럼", "코치처럼", "코치같이", "코치 말투", "코치님 말투"]
# "그럼 포심은 안 던지는 게 나아?"처럼 특정 구종을 배제해도 되는지 묻는 후속 질문.
NEGATION_KEYWORDS = [
    "안 던지는", "안 던져야", "말아야", "안 하는 게", "쓰지 말", "빼는 게", "던지지 말", "버려", "버려야",
]
# "상대 타자가 커터에 강해서 그래?" - 명시된 구종에 대한 강점/약점 확인·반론 질문.
STRONG_PITCH_KEYWORDS = ["강해서", "강한 거", "강한거", "강하지", "강하잖아"]
WEAK_PITCH_KEYWORDS = ["약한 거", "약한거", "약해서", "약하지", "약하잖아"]
# "우리가 지고 있으면 더 공격적으로 가야 하지 않아?" - 점수 상황 자체를 축으로 한 질문.
SCORE_SITUATION_KEYWORDS = [
    "지고 있으면", "지고있으면", "이기고 있으면", "이기고있으면", "박빙이면", "점수차 나면",
    "리드하면", "지고 있는데", "이기고 있는데", "점수 상황",
]
# "이 공은 어떻게 휘어 들어와?" - 구종 무브먼트/궤적 자체를 묻는 질문.
TRAJECTORY_KEYWORDS = ["어떻게 휘어", "어떻게 꺾여", "어떻게 떨어져", "궤적", "휘어 들어와", "휘어져", "떨어져 들어와"]
# "같은 말을 계속해 왜?" / "아까랑 똑같잖아" - 답변이 반복된다는 사용자 불만. 이 표현이 나오면
# 무엇보다 먼저 처리해야 한다(놓치면 "왜"류 다른 키워드에 걸려 또 같은 일반 설명으로 샐 수 있음).
REPETITION_COMPLAINT_KEYWORDS = [
    "같은 말", "아까랑 똑같", "아까와 똑같", "또 그 말", "똑같이 말해", "왜 같은 말", "반복해", "또 같은",
]
# "구속은 어느 정도로 추천해?" / "전력으로 던져?" - 구속/투구 강도 자체를 묻는 질문.
VELOCITY_KEYWORDS = ["구속", "전력으로", "전력투구", "세게 던져", "최고 구속", "강하게 던져", "풀스윙"]
# "안쪽은 노리다 빠질 가능성이 있는데 위험하지 않아?" - 몸쪽/바깥쪽 코스별 위험을 묻는 질문.
INSIDE_OUTSIDE_KEYWORDS = ["안쪽", "몸쪽", "바깥쪽", "인코스", "아웃코스"]
INSIDE_OUTSIDE_RISK_TRIGGER = ["위험", "빠질", "빠지면", "볼넷", "가능성"]
# "상황 바꿔도 왜 똑같아?" / "선수 바꿔도 왜 똑같아?" - 모델 민감도 자체에 대한 메타 질문.
GAME_SITUATION_SENSITIVITY_KEYWORDS = ["상황"]
PLAYER_SENSITIVITY_KEYWORDS = ["선수", "타자를 바꿔", "투수를 바꿔", "타자가 바뀌", "투수가 바뀌"]
SENSITIVITY_TRIGGER_KEYWORDS = ["바꿔도", "바뀌어도", "똑같아", "똑같은", "안 바뀌", "그대로야", "그대로네"]

PITCH_MOVEMENT_DESCRIPTIONS = {
    "FF": "거의 일직선으로 빠르게 들어와", "SI": "살짝 가라앉으면서 들어와",
    "SL": "옆으로 크게 휘면서 들어와", "ST": "슬라이더보다 더 크게 옆으로 휘어져",
    "CH": "패스트볼처럼 오다가 속도가 죽으면서 아래로 떨어져", "FS": "체인지업보다 더 급격하게 떨어져",
    "CU": "크게 낙차를 그리며 떨어져", "KC": "커브처럼 크게 떨어지되 조금 더 날카롭게 꺾여",
    "SV": "슬라이더와 커브 중간처럼 휘면서 떨어져", "FC": "패스트볼처럼 오다가 막판에 살짝 꺾여",
    "OTHER": "구종 특성이 뚜렷하게 분류되지 않아",
}


def _josa(word: str, with_final: str, without_final: str) -> str:
    """한글 받침 유무에 따라 조사를 고른다(예: '포심 패스트볼' -> 받침 있음 -> '이'/'은').
    대화체 답변에서 '포심 패스트볼가/는'처럼 어색한 조사가 나오지 않게 하기 위한 헬퍼."""
    if not word:
        return without_final
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return with_final if (code - 0xAC00) % 28 != 0 else without_final
    return without_final


def _eun(word: str) -> str:
    return word + _josa(word, "은", "는")


def _i(word: str) -> str:
    return word + _josa(word, "이", "가")


def _eul(word: str) -> str:
    return word + _josa(word, "을", "를")


def _extract_text_content(content) -> str:
    """Gradio 6 Chatbot(messages 포맷)은 컴포넌트를 왕복(postprocess->preprocess)하고 나면
    각 메시지의 content를 문자열이 아니라 [{"text": "...", "type": "text"}, ...] 같은 파츠
    리스트로 바꿔서 넘긴다. 이걸 그대로 .split()/.upper() 하면 AttributeError가 나서 Q&A
    후속 질문이 전부 깨졌다 - 문자열/파츠 리스트/객체(TextMessage 등)/None을 모두 안전하게
    문자열로 변환한다."""
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


_COACHING_RECAP_RE = re.compile(r"\s*코칭으로 정리하면\s*:\s*")


def _soften_answer(answer: str) -> str:
    """"코칭으로 정리하면:" 태그를 떼어낸다. rule-based의 수십 개 답변 문자열 하나하나를
    고쳐 쓰는 대신(그러면 또 다른 고정 문구로 대체될 뿐 근본적으로 안 달라짐), 이 태그
    뒤에 오는 문장은 이미 그 자체로 요약 역할을 하므로 태그만 제거해도 자연스러운 마지막
    문장으로 남는다. Ollama 답변에도 방어적으로 적용해 시스템 프롬프트를 어기고 이 문구를
    습관적으로 쓰는 경우까지 함께 잡는다."""
    return _COACHING_RECAP_RE.sub(" ", answer).strip()


def _normalize_history(history) -> list[dict]:
    """history를 항상 [{"role": "user"/"assistant", "content": "문자열"}, ...] 형태로
    정규화한다. Gradio 6 messages 포맷(dict, content가 파츠 리스트), 과거 Gradio "tuples"
    포맷((user_msg, bot_msg) 튜플/리스트), 이미 정규화된 dict, None을 모두 받아들이고,
    알 수 없는 형태는 앱이 죽는 것보다 나으므로 조용히 건너뛴다."""
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


class LLMScout:
    def __init__(self, ollama_host: str = OLLAMA_HOST, ollama_model: str = OLLAMA_MODEL):
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model

    def answer(
        self, question: str, context_chunks: list[str], analysis_result: dict,
        history: list[dict] | None = None,
    ) -> dict:
        """질문 + RAG 컨텍스트 + 분석 결과 + 이전 대화(history)로 답변을 만든다. Ollama가
        없거나 호출에 실패하면 rule-based 답변으로 자동 전환한다 (앱을 죽이지 않기 위한 필수
        fallback). history는 "저게", "그럼" 같은 후속질문에서 직전 언급 구종을 되짚는 데 쓴다.
        Gradio 6 Chatbot이 넘기는 history는 content가 문자열이 아닌 파츠 리스트일 수 있어
        여기서 한 번 정규화한 뒤 아래 두 경로 모두에 그 결과만 넘긴다."""
        normalized_history = _normalize_history(history)
        if self._is_ollama_available():
            try:
                return self._answer_with_ollama(question, context_chunks, analysis_result, normalized_history)
            except (requests.RequestException, ValueError, KeyError):
                pass
        return self._answer_rule_based(question, analysis_result, normalized_history)

    def _is_ollama_available(self) -> bool:
        try:
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=OLLAMA_AVAILABILITY_TIMEOUT_SECONDS)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _answer_with_ollama(
        self, question: str, context_chunks: list[str], analysis_result: dict, history: list[dict] | None,
    ) -> dict:
        summary_text = self._build_analysis_summary(analysis_result)
        context_text = "\n".join(f"- {chunk}" for chunk in context_chunks) if context_chunks else "(참고 문서 없음)"
        # 프롬프트가 너무 길어지지 않도록 최근 2턴(질문+답변 2쌍)만 포함한다.
        recent_history = (history or [])[-4:]
        if recent_history:
            history_text = "\n".join(
                f"{'사용자' if turn.get('role') == 'user' else 'Instant Scout'}: {turn.get('content', '')}"
                for turn in recent_history
            )
        else:
            history_text = "(없음)"
        prompt = (
            f"{SYSTEM_PROMPT}\n\n[분석 요약]\n{summary_text}\n\n[참고 문서]\n{context_text}\n\n"
            f"[이전 대화]\n{history_text}\n\n[질문]\n{question}\n\n[답변]"
        )

        resp = requests.post(
            f"{self.ollama_host}/api/generate",
            json={"model": self.ollama_model, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer_text = resp.json().get("response", "").strip()
        if not answer_text:
            raise ValueError("Ollama 응답이 비어 있음")
        answer_text = _soften_answer(answer_text)
        return {"answer": answer_text, "source": "ollama", "used_context": context_chunks}

    def _build_analysis_summary(self, analysis_result: dict) -> str:
        """RAG 검색 결과(context_chunks)는 자유 텍스트라 핵심 수치를 놓칠 수 있어, Ollama 프롬프트에
        analysis_result의 핵심 값을 직접 요약해 넣는다. rule-based 답변에 쓰는 값과 동일한 소스라
        Ollama/rule-based 두 경로가 서로 다른 숫자를 말하는 일이 없다."""
        pitcher_result = analysis_result.get("pitcher_mode_result")
        batter_result = analysis_result.get("batter_mode_result")
        mode = analysis_result.get("mode") or ("pitcher" if pitcher_result else "batter")
        risk_summary = analysis_result.get("risk_summary") or {}
        context = analysis_result.get("game_context") or {}
        top3 = analysis_result.get("predicted_top3_pitches") or []

        lines = [f"mode: {'투수(pitcher)' if mode == 'pitcher' else '타자(batter)'}"]
        if context:
            runners = ", ".join(
                label for label, on in [("1루", context.get("on_1b")), ("2루", context.get("on_2b")), ("3루", context.get("on_3b"))] if on
            ) or "없음"
            lines.append(
                f"카운트: {context.get('balls')}B-{context.get('strikes')}S, {context.get('outs_when_up')}아웃, "
                f"주자: {runners}, 점수차: {context.get('score_diff')}"
            )
        if analysis_result.get("score_situation_label"):
            lines.append(
                f"점수 상황(우리팀 기준): {analysis_result['score_situation_label']} "
                f"(우리팀 {analysis_result.get('our_score')} : 상대팀 {analysis_result.get('opponent_score')})"
            )
        if top3:
            lines.append("Top-3: " + ", ".join(f"{pitch_label_kr(i['pitch_label'])}({i['pitch_label']}) {i['probability']:.1%}" for i in top3))
        if pitcher_result:
            lines.append(f"추천 구종: {pitch_label_kr(pitcher_result['recommended_pitch'])}({pitcher_result['recommended_pitch']})")
            if pitcher_result.get("avoid_pitch"):
                lines.append(f"피해야 할 구종: {pitch_label_kr(pitcher_result['avoid_pitch'])}({pitcher_result['avoid_pitch']})")
            lines.append(f"추천 존(zone_cell): {pitcher_result.get('best_zone_cell')}")
            weakness = pitcher_result.get("batter_weakness") or {}
            if weakness.get("summary"):
                lines.append(f"상대 타자 약점/강점: {weakness['summary']}")
        if batter_result:
            lines.append(f"노릴 코스: {batter_result.get('target_zone')} (zone_cell {batter_result.get('target_zone_cell')})")
            pattern = batter_result.get("pitcher_pattern") or {}
            if pattern.get("summary"):
                lines.append(f"상대 투수 패턴: {pattern['summary']}")
            lines.append(f"대응 전략: {batter_result.get('counter_strategy')}")
        risk_parts = [f"{k}={v:.1%}" for k, v in risk_summary.items() if isinstance(v, (int, float))]
        if risk_parts:
            lines.append("위험도: " + ", ".join(risk_parts))
        return "\n".join(lines)

    def _mentioned_pitches(self, text: str) -> list[str]:
        """텍스트에 명시적으로 등장하는 모든 구종(약어+한글 구어체 별칭)을 등장 순서대로 반환."""
        found: list[str] = []
        upper = text.upper()
        for label in KNOWN_PITCH_LABELS:
            if label in upper and label not in found:
                found.append(label)
        for kr, label in PITCH_KR_ALIASES.items():
            if kr in text and label not in found:
                found.append(label)
        return found

    def _resolve_reference_pitch(
        self, text: str, history: list[dict] | None, analysis_result: dict,
    ) -> str | None:
        """"저게", "그럼", "방금 추천한 구종" 같은 대명사/후속질문 표현이 나오면, 직전 대화에서
        마지막으로 언급된 구종을 찾아 되짚는다. 대화 기록에 구종 언급이 없으면 이번 분석의
        추천 구종(투수 모드) 또는 예상 1순위 구종(타자 모드)으로 대체한다."""
        if not any(k in text for k in REFERENCE_WORDS):
            return None
        for turn in reversed(history or []):
            content = turn.get("content", "") if isinstance(turn, dict) else ""
            found = self._mentioned_pitches(content)
            if found:
                return found[-1]
        pitcher_result = analysis_result.get("pitcher_mode_result")
        if pitcher_result and pitcher_result.get("recommended_pitch"):
            return pitcher_result["recommended_pitch"]
        batter_result = analysis_result.get("batter_mode_result")
        if batter_result and batter_result.get("expected_top3_pitches"):
            return batter_result["expected_top3_pitches"][0]["pitch_label"]
        return None

    def _answer_rule_based(
        self, question: str, analysis_result: dict, history: list[dict] | None = None,
    ) -> dict:
        """rule-based 답변의 공개 진입점. 실제 의도 분기 로직(_dispatch_rule_based_answer)에서
        예상치 못한 예외(예: 신규 intent 핸들러의 버그, analysis_result의 예상 밖 구조)가 나도
        "답변을 생성하는 중 문제가 발생했습니다" 같은 죽은 메시지 대신, 지금 가진 정보로 만들
        수 있는 최소한의 fallback 답변을 항상 반환한다."""
        history = _normalize_history(history)
        top3 = analysis_result.get("predicted_top3_pitches") or []
        pitcher_result = analysis_result.get("pitcher_mode_result")
        batter_result = analysis_result.get("batter_mode_result")
        try:
            answer = self._dispatch_rule_based_answer(question, analysis_result, history)
        except Exception as exc:  # noqa: BLE001
            print(f"[경고] rule-based Q&A 처리 중 예외 발생, 안전 답변으로 대체: {exc}")
            answer = self._answer_general_fallback(question or "", top3, pitcher_result, batter_result)
        answer = _soften_answer(answer)
        return {"answer": answer, "source": "rule_based", "used_context": []}

    def _dispatch_rule_based_answer(
        self, question: str, analysis_result: dict, history: list[dict],
    ) -> str:
        text = question or ""
        top3 = analysis_result.get("predicted_top3_pitches") or []
        risk_summary = analysis_result.get("risk_summary") or {}
        interpretation = analysis_result.get("user_comment_interpretation") or {}
        pitcher_result = analysis_result.get("pitcher_mode_result")
        batter_result = analysis_result.get("batter_mode_result")
        pitch_risk_details = analysis_result.get("pitch_risk_details") or {}
        all_pitch_scores = analysis_result.get("all_pitch_scores") or {}

        game_context = analysis_result.get("game_context")
        explicit_mentions = self._mentioned_pitches(text)
        mentioned_pitch = explicit_mentions[0] if explicit_mentions else None
        reference_pitch = self._resolve_reference_pitch(text, history, analysis_result)
        # 명시적으로 언급되지 않았어도(예: "컨택되면 위험하지 않아?") 방금 추천/1순위 구종을 묻는
        # 것으로 보고, 대명사 대상 -> 추천 구종/타자 1순위 순으로 대체 구종을 찾는다.
        fallback_pitch = (
            mentioned_pitch or reference_pitch
            or (pitcher_result.get("recommended_pitch") if pitcher_result else None)
            or (top3[0]["pitch_label"] if top3 else None)
        )

        score_breakdown = analysis_result.get("score_breakdown") or {}
        is_repetition_branch = False

        # "같은 말을 계속해 왜?" 같은 반복 불만은 무엇보다 먼저 처리해야 한다 - 안 그러면 "왜"류
        # 다른 키워드(예: 추천 이유를 묻는 질문)에 걸려 또 같은 일반 설명으로 새 버린다.
        if any(k in text for k in REPETITION_COMPLAINT_KEYWORDS):
            answer = self._explain_repetition_complaint(pitcher_result, batter_result, score_breakdown, explicit_complaint=True)
            is_repetition_branch = True
        # "코치님처럼 대답해줘"처럼 말투/페르소나 자체를 요청하는 메타 질문이 최우선이다 - 이걸
        # 놓치면 "코치처럼"이라는 말이 다른 키워드에 안 걸려 그냥 일반 Top-3 안내로 새 버린다.
        elif any(k in text for k in COACH_PERSONA_KEYWORDS):
            answer = self._explain_as_coach_persona(pitcher_result, batter_result, top3)
        # "그럼 포심은 안 던지는 게 나아?"처럼 특정 구종을 빼도 되는지 묻는 후속 질문.
        elif fallback_pitch and any(k in text for k in NEGATION_KEYWORDS):
            answer = self._explain_pitch_negation(fallback_pitch, pitcher_result, batter_result, pitch_risk_details, game_context)
        # "상대 타자가 커터에 강해서 그래?" / "이 타자 슬라이더 약한 거야?" - 명시된 구종의 강점/
        # 약점 여부를 확인하거나 반론하는 질문. mentioned_pitch(명시 언급)가 있을 때만 처리한다.
        elif mentioned_pitch and any(k in text for k in STRONG_PITCH_KEYWORDS):
            answer = self._explain_strong_pitch_question(mentioned_pitch, pitcher_result)
        elif mentioned_pitch and any(k in text for k in WEAK_PITCH_KEYWORDS):
            answer = self._explain_weak_pitch_question(mentioned_pitch, pitcher_result)
        # "우리가 지고 있으면 더 공격적으로 가야 하지 않아?" - 점수 상황 자체를 축으로 한 질문.
        elif any(k in text for k in SCORE_SITUATION_KEYWORDS):
            answer = self._explain_score_situation(analysis_result, pitcher_result, batter_result)
        # "이 공은 어떻게 휘어 들어와?" - 구종 무브먼트/궤적 자체를 묻는 질문.
        elif any(k in text for k in TRAJECTORY_KEYWORDS):
            answer = self._explain_trajectory_question(fallback_pitch, pitcher_result)
        # "구속은 어느 정도로 추천해?" / "전력으로 던져?" - 구속/투구 강도 자체를 묻는 질문.
        elif any(k in text for k in VELOCITY_KEYWORDS):
            answer = self._explain_velocity_question(pitcher_result)
        # "안쪽은 노리다 빠질 가능성이 있는데 위험하지 않아?" - 몸쪽/바깥쪽 코스별 위험 질문.
        elif any(k in text for k in INSIDE_OUTSIDE_KEYWORDS) and any(k in text for k in INSIDE_OUTSIDE_RISK_TRIGGER):
            answer = self._explain_inside_outside_risk(text, pitcher_result, risk_summary)
        # "상황 바꿔도 왜 똑같아?" / "선수 바꿔도 왜 똑같아?" - 모델 민감도 자체를 묻는 메타 질문.
        # "선수"가 "상황"보다 더 구체적인 표현이므로 먼저 검사한다.
        elif any(k in text for k in PLAYER_SENSITIVITY_KEYWORDS) and any(k in text for k in SENSITIVITY_TRIGGER_KEYWORDS):
            answer = self._explain_player_sensitivity(analysis_result)
        elif any(k in text for k in GAME_SITUATION_SENSITIVITY_KEYWORDS) and any(k in text for k in SENSITIVITY_TRIGGER_KEYWORDS):
            answer = self._explain_game_situation_sensitivity(analysis_result)
        # "상대 타자에 대해 분석해줘"처럼 Top-3/추천 근거가 아니라 "상대 선수 자체"를 묻는 질문은
        # 무엇보다 먼저 걸러야 한다 - 그렇지 않으면 아래의 다른 키워드(예: RECOMMEND_QUESTION의
        # "삼진"이 "타자 삼진 잘 잡아?" 등과 겹침) 매칭에 밀려 Top-3 설명으로 새 버릴 수 있다.
        elif pitcher_result and any(k in text for k in OPPONENT_ANALYSIS_KEYWORDS):
            answer = self._explain_opponent_batter_analysis(pitcher_result)
        elif batter_result and any(k in text for k in OPPONENT_ANALYSIS_KEYWORDS):
            answer = self._explain_opponent_pitcher_analysis(batter_result)
        elif "카운트" in text and any(k in text for k in COUNT_STRATEGY_KEYWORDS):
            answer = self._explain_count_strategy(pitcher_result, batter_result, game_context)
        # "볼넷 위험 있는데 왜 추천해?"처럼 위험을 지적하며 이유를 묻는 질문은 단순 확률 설명으로는
        # 답이 안 되므로, 위험을 인정 -> 근거 -> 대안까지 담은 전용 답변으로 최우선 분기한다.
        elif (
            pitcher_result and any(k in text for k in RISK_CONTRADICTION_KEYWORDS)
            and any(k in text for k in ["왜", "이유", "안 돼", "괜찮"])
        ):
            answer = self._explain_recommendation_with_risk(pitcher_result, risk_summary, game_context)
        # "변화구가 더 낫지 않아?"처럼 특정 구종명이 아니라 구종 카테고리(변화구/패스트볼)를 묻는 질문.
        # 투수 모드에서만 의미가 있으므로(사용자=투수) pitcher_result가 있을 때만 처리한다.
        elif pitcher_result and any(k in text for k in BREAKING_BALL_KEYWORDS):
            answer = self._explain_breaking_ball_preference(pitcher_result, top3, all_pitch_scores, pitch_risk_details, game_context)
        # 대명사 없이도 서로 다른 구종 두 개가 명시적으로 함께 언급되면("슬라이더랑 포심 중에 뭐가
        # 더 안전해?") 바로 비교 질문으로 판단한다.
        elif len(explicit_mentions) >= 2:
            answer = self._explain_pitch_comparison(
                explicit_mentions[0], explicit_mentions[1], pitcher_result, batter_result, pitch_risk_details, all_pitch_scores,
            )
        # "그럼 저게 우려되면 슬라이더가 나아?" 처럼 대명사(저게=이전 맥락 구종)와 새 구종(슬라이더)이
        # 함께 나오면 "비교" 질문으로 판단해 두 구종을 직접 비교한다.
        elif (
            mentioned_pitch and reference_pitch and mentioned_pitch != reference_pitch
            and any(k in text for k in COMPARISON_KEYWORDS)
        ):
            answer = self._explain_pitch_comparison(
                reference_pitch, mentioned_pitch, pitcher_result, batter_result, pitch_risk_details, all_pitch_scores,
            )
        elif any(k in text for k in WORST_ZONE_KEYWORDS):
            answer = self._explain_worst_zone(pitcher_result, batter_result)
        elif any(k in text for k in CONTACT_RISK_KEYWORDS) and fallback_pitch:
            answer = self._explain_pitch_contact_risk(fallback_pitch, pitch_risk_details, risk_summary, pitcher_result)
        elif pitcher_result and (
            (any(k in text for k in ["왜", "이유"]) and "추천" in text)
            or any(k in text for k in RECOMMEND_QUESTION_KEYWORDS)
        ):
            answer = self._explain_recommendation(text, top3, pitcher_result)
        elif any(k in text for k in ZONE_STRATEGY_KEYWORDS) and any(k in text for k in ZONE_ACTION_KEYWORDS):
            answer = self._explain_zone_strategy(pitcher_result, batter_result)
        elif "약점" in text or "패턴" in text:
            if pitcher_result:
                answer = self._explain_opponent_batter_analysis(pitcher_result)
            elif batter_result:
                answer = self._explain_opponent_pitcher_analysis(batter_result)
            else:
                answer = self._explain_weakness(pitcher_result, batter_result)
        elif any(k in text for k in ["장타", "홈런"]):
            extra_base_risk = risk_summary.get("extra_base_hit_risk")
            home_run_risk = risk_summary.get("home_run_risk")
            if extra_base_risk is None or home_run_risk is None:
                answer = "장타 쪽 데이터가 아직 부족해서 확실하게는 말 못 해줘. 일단 지금 추천 구종 기준으로는 큰 이상 신호는 안 보여."
            else:
                feel = "그렇게 위험한 수준은 아니야" if extra_base_risk < 0.05 else "조금은 신경 써야 하는 수준이야"
                answer = (
                    f"장타 위험은 {extra_base_risk:.1%}, 홈런까지 가는 위험은 {home_run_risk:.1%} 정도야. {feel}. "
                    f"다만 존 가운데로 몰리는 순간 이 수치는 확 뛰니까, 코스 관리가 핵심이야. "
                    "코칭으로 정리하면: 위험도 자체보다 어디로 몰리느냐를 더 신경 써."
                )
        elif "볼넷" in text:
            walk_risk = risk_summary.get("walk_risk")
            if walk_risk is None:
                answer = "볼넷 위험은 지금 데이터로는 계산이 안 돼. 카운트 흐름 보면서 감으로 조절하는 수밖에 없어."
            elif "반영" in text:
                answer = f"네가 입력한 코멘트는 이렇게 반영됐어: {interpretation.get('summary', '특별히 반영된 내용은 없어.')} 코칭으로 정리하면: 의도는 살렸으니 카운트만 보면서 조절해."
            elif "감수" in text or "괜찮" in text:
                if walk_risk < 0.35:
                    answer = f"지금 볼넷 위험은 {walk_risk:.1%}로 낮은 편이라 걱정 안 해도 돼. 지금 배합 그대로 밀고 가도 괜찮아. 코칭으로 정리하면: 지금 페이스 유지해."
                else:
                    answer = f"볼넷 위험이 {walk_risk:.1%}로 좀 높은 편이긴 해. 그래도 무조건 존 안으로 몰기보다는, 스트라이크 비중만 살짝 올리는 정도로 조절하는 게 나아. 코칭으로 정리하면: 존 경계 위주로 스트라이크 비중만 올려."
            else:
                answer = f"지금 볼넷 위험은 {walk_risk:.1%}야. 코칭으로 정리하면: 이 수치 하나로 판단하지 말고 카운트랑 같이 봐."
        elif any(k in text for k in BATTER_SWING_KEYWORDS) and (batter_result or "타자" in text):
            if batter_result:
                expected = batter_result.get("expected_top3_pitches") or []
                prob_note = f" 확률로도 {expected[0]['probability']:.0%} 정도로 제일 유력해." if expected else ""
                answer = (
                    f"네가 타석에 있다고 생각하면, {batter_result['target_zone']} 쪽으로 오는 공은 노려도 좋아.{prob_note} "
                    "다만 그 코스가 아니면 억지로 따라가지 마 - 존을 벗어나는 유인구에 배트 나가는 게 제일 손해야. "
                    "코칭으로 정리하면: 그 코스로 올 때만 확실하게 스윙하고, 아니면 지켜봐."
                )
            else:
                answer = "지금은 타자 모드 데이터가 없어서 정확히는 못 짚어줘. 타자 모드로 분석 한 번 돌리면 바로 노릴 코스 알려줄게."
        elif "코멘트" in text and "반영" in text:
            answer = f"네가 입력한 코멘트는 이렇게 반영됐어: {interpretation.get('summary', '특별히 반영된 내용은 없어.')} 코칭으로 정리하면: 의도는 이미 전략에 녹아 있어."
        else:
            # 질문 의도를 특정하지 못했을 때도 "Top-3만 반환"하지 않고, 현재 모드의 핵심 결론(추천
            # 구종/근거 또는 예상 구종/대응 전략)을 먼저 설명한 뒤 추가로 물어볼 만한 질문을 안내한다.
            answer = self._answer_general_fallback(text, top3, pitcher_result, batter_result)

        # 서로 다른 질문인데도 직전 답변과 사실상 같은 결론이 나오면("포심으로 승부하고 커터는
        # 아껴둬" 반복 등) 사용자가 반복을 지적하지 않았어도 자동으로 다른 각도로 재작성한다.
        # repetition_complaint 분기 자체는 다시 재작성하지 않는다(무한 자기 참조 방지).
        if not is_repetition_branch:
            last_answer = self._last_assistant_answer(history)
            if self._is_repetitive(answer, last_answer):
                answer = self._explain_repetition_complaint(
                    pitcher_result, batter_result, score_breakdown, explicit_complaint=False,
                )

        return answer

    def _explain_as_coach_persona(
        self, pitcher_result: dict | None, batter_result: dict | None, top3: list[dict],
    ) -> str:
        """"코치님처럼 대답해줘" 같은 페르소나 요청 전용 답변. 형식을 설명하거나 되묻지 않고,
        실제로 코치 말투로 지금 상황에 대한 판단을 바로 들려준다."""
        if pitcher_result:
            recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
            avoid = pitcher_result.get("avoid_pitch")
            avoid_kr = pitch_label_kr(avoid) if avoid else None
            parts = [
                "오케이, 코치처럼 말하면 지금은 무리해서 보여주는 공보다 타자가 못 건드리는 코스를 먼저 봐야 해.",
                "네가 투수라면 첫 번째 목표는 장타를 피하면서 카운트를 유리하게 가져가는 거야.",
                f"데이터상으로는 {_i(recommended_kr)} 1순위로 잡히지만, 그게 무조건 정면승부하라는 뜻은 아니야.",
                "낮은 존에 붙이거나, 한 번 보여준 뒤 다른 구종으로 빼는 식으로 써야 해.",
            ]
            if avoid_kr:
                parts.append(f"반대로 {_eun(avoid_kr)} 지금은 자신 있게 던질 만한 공이 아니니까 굳이 승부구로 쓰지 마.")
            parts.append(f"코칭으로 정리하면: {recommended_kr}로 시선을 묶고, 상대가 익숙해지기 전에 코스를 바꿔.")
            return " ".join(parts)
        if batter_result:
            target = batter_result.get("target_zone")
            parts = [
                "오케이, 코치처럼 말하면 지금은 아무 공에나 배트 내밀 타이밍이 아니야.",
                "네가 타석에 있다면 목표는 하나야 - 확실한 공만 강하게 받아치는 것.",
                f"지금 데이터로는 {target} 쪽으로 올 가능성이 높으니까, 그 존에 타이밍을 맞춰놔.",
                "다만 그 코스가 아니면 억지로 손 내밀지 마, 존 벗어나는 공 따라가는 게 제일 손해야.",
                f"코칭으로 정리하면: {target}만 노리고, 그 외에는 침착하게 지켜봐.",
            ]
            return " ".join(parts)
        if top3:
            top_kr = pitch_label_kr(top3[0]["pitch_label"])
            return (
                f"오케이, 코치처럼 말하면 지금은 {top_kr} 위주로 흐름을 보고 있어. "
                "다만 아직 투수/타자 모드로 제대로 분석을 안 돌린 상태라 세부적으로 짚어주긴 어려워. "
                "코칭으로 정리하면: 먼저 분석 한 번 돌리고 다시 물어봐, 그럼 제대로 짚어줄게."
            )
        return "분석을 먼저 실행해줘야 코치답게 짚어줄 수 있어. 코칭으로 정리하면: 분석부터 돌리고 다시 물어봐."

    def _explain_pitch_negation(
        self, pitch_label: str, pitcher_result: dict | None, batter_result: dict | None,
        pitch_risk_details: dict, game_context: dict | None,
    ) -> str:
        """"그럼 포심은 안 던지는 게 나아?"처럼 특정 구종을 배제해도 되는지 묻는 후속 질문 전용
        답변. 완전히 배제해야 하는지, 비중만 줄이면 되는지를 결론부터 말해준다."""
        kr = pitch_label_kr(pitch_label)
        detail = pitch_risk_details.get(pitch_label)
        strikes = (game_context or {}).get("strikes")

        if pitcher_result:
            recommended = pitcher_result["recommended_pitch"]
            if pitch_label == recommended:
                risk_line = f"장타 위험도 {detail['extra_base_hit_risk']:.1%} 정도라 특별히 위험한 수준도 아니야." if detail else ""
                return (
                    f"아니, 완전히 뺄 필요는 없어. {_eun(kr)} 지금 데이터에서도 여전히 1순위로 잡히는 공이야. {risk_line} "
                    "다만 이 공만 계속 던지면 타이밍이 읽히니까, 결정구 하나만 다른 구종으로 바꿔주는 정도면 충분해. "
                    f"코칭으로 정리하면: {_eun(kr)} 계속 쓰되, 결정구만 바꿔서 변화를 줘."
                )
            avoid = pitcher_result.get("avoid_pitch")
            if pitch_label == avoid:
                return (
                    f"그 말 맞아, {_eun(kr)} 지금 상황에서는 굳이 승부구로 안 쓰는 게 나아. "
                    "구사 비율도 낮고 지금 데이터로는 자신 있게 던질 만한 공이 아니야. "
                    f"코칭으로 정리하면: {_eun(kr)} 오늘은 접어두고 다른 구종으로 승부해."
                )
            strikes_note = " 2스트라이크 이후라면 유인구로 살짝 섞어도 되고." if strikes is not None and strikes >= 2 else ""
            return (
                f"완전히 배제할 정도는 아니야. {_i(kr)} 최우선 선택은 아니지만, 상황 봐가면서 섞을 여지는 있어.{strikes_note} "
                f"코칭으로 정리하면: {_eun(kr)} 메인으로 쓰지 말고 변화 주는 용도로만 아껴둬."
            )
        if batter_result:
            target = batter_result.get("target_zone")
            return (
                f"타자 입장에서는 {kr} 하나만 보고 판단하기보다, 지금 노려야 할 건 {target}야. "
                f"{_i(kr)} 오더라도 그 코스가 아니면 무리하게 반응할 필요 없어. "
                f"코칭으로 정리하면: 구종보다 코스 기준으로 스윙 여부를 정해."
            )
        return f"{kr}에 대해 판단하려면 먼저 분석을 한 번 돌려줘야 해. 코칭으로 정리하면: 분석부터 돌리고 다시 물어봐."

    def _answer_general_fallback(
        self, text: str, top3: list[dict], pitcher_result: dict | None, batter_result: dict | None,
    ) -> str:
        if pitcher_result:
            return self._explain_recommendation(text, top3, pitcher_result)
        if batter_result and batter_result.get("expected_top3_pitches"):
            top_expected = batter_result["expected_top3_pitches"][0]
            top_kr = pitch_label_kr(top_expected["pitch_label"])
            return (
                f"네가 타석에 있다면, 상대가 {top_kr} 계열을 던질 가능성이 가장 높아 - 확률로 {top_expected['probability']:.0%} 정도야. "
                f"코칭으로 정리하면: {top_kr} 타이밍에 맞춰놓고, 아니면 침착하게 지켜봐."
            )
        if top3:
            top_kr = pitch_label_kr(top3[0]["pitch_label"])
            return (
                f"지금 데이터로는 {top_kr} 쪽 흐름이 가장 뚜렷해. "
                "구체적으로 뭐가 궁금한지 - 상대 약점, 노릴 코스, 위험한 구종 이런 식으로 물어봐주면 더 자세히 짚어줄게. "
                f"코칭으로 정리하면: {top_kr} 위주로 보되, 구체적인 걸 물어보면 더 파고들어줄게."
            )
        return "아직 분석을 안 돌렸네. 먼저 분석 버튼 눌러주면 그때부터 제대로 짚어줄게."

    def _explain_recommendation(self, text: str, top3: list[dict], pitcher_result: dict) -> str:
        recommended = pitcher_result["recommended_pitch"]
        recommended_kr = pitch_label_kr(recommended)
        mentions = self._mentioned_pitches(text)
        mentioned = mentions[0] if mentions else None

        if mentioned and mentioned != recommended:
            prob = next((item["probability"] for item in top3 if item["pitch_label"] == mentioned), None)
            mentioned_kr = pitch_label_kr(mentioned)
            if prob is not None:
                return (
                    f"{mentioned_kr}도 나쁘지 않아 - 예측 확률이 {prob:.1%}로 top3 안에는 들거든. "
                    f"다만 지금은 {_i(recommended_kr)} 그것보다 한 끗 더 유리해서 그쪽을 먼저 권한 거야. "
                    f"코칭으로 정리하면: {_eun(mentioned_kr)} 대안으로 챙겨두고, 메인은 {recommended_kr}로 가."
                )
            return f"{mentioned_kr}은 지금 흐름에서는 우선순위가 낮아. 코칭으로 정리하면: {recommended_kr} 먼저 쓰고 {mentioned_kr}은 상황 봐서 섞어."

        avoid = pitcher_result.get("avoid_pitch")
        avoid_kr = pitch_label_kr(avoid) if avoid else None
        parts = [
            f"네가 투수라면 지금은 {recommended_kr} 위주로 가는 게 맞아.",
            "예측 확률뿐 아니라 실제 구사 비율, 상대 타자 약점, 위험도까지 다 같이 본 결과라 근거는 꽤 탄탄해.",
        ]
        if avoid_kr:
            parts.append(f"반대로 {_eun(avoid_kr)} 지금은 자신 있게 던질 공이 아니라서 승부구로는 피하는 게 좋아.")
        parts.append(f"코칭으로 정리하면: {recommended_kr}로 승부하고, {avoid_kr or '위험한 공'}은 오늘은 아껴둬.")
        return " ".join(parts)

    def _explain_breaking_ball_preference(
        self, pitcher_result: dict, top3: list[dict], all_pitch_scores: dict, pitch_risk_details: dict, game_context: dict | None,
    ) -> str:
        """"변화구가 더 낫지 않아?"처럼 특정 구종명이 아니라 구종 카테고리(변화구 vs 패스트볼)를
        묻는 질문 전용 답변. 코치가 반론을 받아준 뒤 이유를 설명하는 대화체로 구성한다."""
        recommended = pitcher_result["recommended_pitch"]
        recommended_kr = pitch_label_kr(recommended)
        breaking_candidates = {label: score for label, score in all_pitch_scores.items() if label in BREAKING_BALL_LABELS}
        best_breaking = max(breaking_candidates, key=breaking_candidates.get) if breaking_candidates else None

        if recommended in BREAKING_BALL_LABELS:
            return (
                f"그 말 맞아. 사실 지금 추천도 이미 변화구인 {recommended_kr}야. "
                "투수 입장에서 타자를 잡는 공만 보면 변화구가 매력적인 선택인 게 맞고, 지금 데이터도 그걸 가리키고 있어. "
                f"코칭으로 정리하면: {recommended_kr} 믿고 가되, 존 경계선까지만 정확히 붙여."
            )

        parts = ["그 말 맞아. 투수 입장에서 '타자를 잡는 공'만 보면 변화구가 더 매력적인 선택일 수 있어."]
        if best_breaking:
            best_kr = pitch_label_kr(best_breaking)
            parts.append(
                f"다만 지금 {_i(recommended_kr)} 높게 나온 건, 타자가 그 공을 예상할 가능성이랑 실제 구사 비율, "
                "카운트 안정성까지 같이 본 결과야."
            )
            detail = pitch_risk_details.get(best_breaking)
            if detail:
                parts.append(f"{_eun(best_kr)} 결정구로는 좋지만 제구가 흔들리면 장타 위험이 {detail['extra_base_hit_risk']:.1%}까지 올라가.")
            balls, strikes = (game_context or {}).get("balls"), (game_context or {}).get("strikes")
            if strikes is not None and strikes >= 2:
                parts.append(f"근데 지금 {balls}B-{strikes}S면 여유가 있으니까, {best_kr} 비중을 올려도 괜찮아.")
                parts.append(f"코칭으로 정리하면: {best_kr}로 결정구 가져가도 좋아.")
            else:
                parts.append(f"그래서 바로 {best_kr}만 가기보다는, {recommended_kr}로 시선을 묶고 결정구로 {_eul(best_kr)} 쓰는 쪽이 더 안전해.")
                parts.append(f"코칭으로 정리하면: {_eun(recommended_kr)} 보여주는 공, {_eun(best_kr)} 잡는 공으로 써.")
        else:
            parts.append(f"다만 지금 데이터로는 {_i(recommended_kr)} 여전히 더 안전한 선택이야.")
            parts.append(f"코칭으로 정리하면: 지금은 {recommended_kr} 믿고 가.")
        return " ".join(parts)

    def _explain_recommendation_with_risk(
        self, pitcher_result: dict, risk_summary: dict, game_context: dict | None,
    ) -> str:
        """"볼넷 위험이 있는데 왜 추천해?" 같은 모순 지적 질문 전용 답변. 위험을 먼저 인정하고
        받아준 뒤, 이유와 카운트 기반 대안을 코치 말투로 설명한다."""
        recommended = pitcher_result["recommended_pitch"]
        recommended_kr = pitch_label_kr(recommended)
        best_cell = pitcher_result.get("best_zone_cell")
        walk_risk = risk_summary.get("walk_risk")
        balls = (game_context or {}).get("balls")
        strikes = (game_context or {}).get("strikes")

        parts = [f"그 말 맞아, {_eul(recommended_kr)} 존 경계 쪽으로 붙이면 볼넷 위험이 같이 올라가는 건 사실이야."]
        if walk_risk is not None:
            parts.append(f"근데 지금 볼넷 위험이 {walk_risk:.1%}인 거에 비해, 이 코스가 장타·하드히트는 확실히 줄여주거든.")
        parts.append("그러니까 이건 '무조건 스트라이크 잡는 공'이 아니라, 맞아도 크게 안 아픈 쪽을 고른 거라고 보면 돼.")
        if balls is not None and strikes is not None:
            if balls >= 3:
                parts.append(f"다만 지금은 {balls}B-{strikes}S라 볼넷이 진짜 부담되니까, 같은 방향에서 존 쪽으로 살짝만 더 붙여.")
            elif strikes >= 2:
                parts.append(f"지금은 {balls}B-{strikes}S로 여유가 있어서, 이 유인구로 헛스윙 유도하기 딱 좋은 타이밍이야.")
            else:
                parts.append(f"지금 카운트({balls}B-{strikes}S)면 무리하게 존 안으로 몰 필요 없이 이대로 가도 돼.")
        parts.append(f"코칭으로 정리하면: 볼넷 걱정되면 같은 코스에서 존 쪽으로 반 개만 더 붙여.")
        return " ".join(parts)

    def _explain_pitch_contact_risk(
        self, pitch_label: str, pitch_risk_details: dict, risk_summary: dict, pitcher_result: dict | None = None,
    ) -> str:
        kr = pitch_label_kr(pitch_label)
        detail = pitch_risk_details.get(pitch_label)
        if detail is None:
            extra_base_risk = risk_summary.get("extra_base_hit_risk")
            home_run_risk = risk_summary.get("home_run_risk")
            if extra_base_risk is None or home_run_risk is None:
                return f"{kr} 단독 데이터는 아직 부족해서 정확히는 말 못 해줘. 코칭으로 정리하면: 일단 top3 기준으로 보수적으로 접근해."
            return (
                f"{kr} 단독 데이터는 부족한데, 지금 top3 기준으로는 장타 위험 {extra_base_risk:.1%}, 홈런 위험 {home_run_risk:.1%} 정도야. "
                "코칭으로 정리하면: 큰 이상 신호는 없으니 코스만 잘 관리해."
            )
        extra_base_risk = detail["extra_base_hit_risk"]
        hard_hit_risk = detail["hard_hit_risk"]
        feel = "그렇게 위험한 수준은 아니야" if extra_base_risk < 0.08 else "솔직히 좀 위험한 수준이야"
        parts = [
            f"컨택되면 좀 아플 수는 있어 - {_i(kr)} 존 안으로 몰리면 장타로 이어질 확률이 {extra_base_risk:.1%}, "
            f"하드히트까지 가는 확률이 {hard_hit_risk:.1%} 정도야. {feel}.",
            "그러니까 존 바깥쪽으로 카운트 잡고, 결정구는 경계선을 정확히 노리는 게 좋아.",
        ]
        recommended = pitcher_result.get("recommended_pitch") if pitcher_result else None
        if recommended and recommended != pitch_label:
            recommended_kr = pitch_label_kr(recommended)
            parts.append(f"지금 상황이면 차라리 {recommended_kr} 위주로 승부하는 게 더 안전해.")
            parts.append(f"코칭으로 정리하면: {_eun(kr)} 존 경계선까지만, 승부구는 {recommended_kr}로 가.")
        else:
            parts.append(f"코칭으로 정리하면: {_eun(kr)} 존 가운데 말고 경계선을 정확히 노려.")
        return " ".join(parts)

    def _explain_zone_strategy(self, pitcher_result: dict | None, batter_result: dict | None) -> str:
        if pitcher_result:
            best_cell = pitcher_result.get("best_zone_cell")
            danger = pitcher_result.get("zone_danger_scores", {})
            recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
            answer = (
                f"zone_cell {best_cell}번 쪽으로 가. 위험 점수가 제일 낮은 존이라 스트라이크 잡으면서도 "
                f"장타·볼넷 위험이 같이 낮아. {recommended_kr} 위주로 이 존에 붙이면 돼."
            )
            in_zone = {c: v for c, v in danger.items() if c != 0}
            if in_zone:
                worst_cell = max(in_zone, key=in_zone.get)
                if worst_cell != best_cell:
                    answer += f" 반대로 zone_cell {worst_cell}번은 위험한 코스니까 거긴 피해."
            answer += f" 코칭으로 정리하면: zone_cell {best_cell}번에 {recommended_kr} 위주로 붙여."
            return answer
        if batter_result:
            target_cell = batter_result.get("target_zone_cell")
            prob = batter_result.get("zone_probability_scores", {})
            return (
                f"다음 공이 zone_cell {target_cell}번({batter_result['target_zone']}) 쪽으로 올 확률이 "
                f"{prob.get(target_cell, 0):.1%}로 제일 높아. "
                f"코칭으로 정리하면: {batter_result['target_zone']}에 타이밍 맞춰놔."
            )
        return "분석부터 먼저 돌려줘야 추천 존을 짚어줄 수 있어."

    def _explain_worst_zone(self, pitcher_result: dict | None, batter_result: dict | None) -> str:
        if pitcher_result:
            danger = pitcher_result.get("zone_danger_scores") or {}
            in_zone = {c: v for c, v in danger.items() if c != 0}
            if not in_zone:
                return "존별 위험 데이터가 아직 부족해서 콕 짚어주기는 어려워."
            worst_cell = max(in_zone, key=in_zone.get)
            best_cell = pitcher_result.get("best_zone_cell")
            return (
                f"제일 위험한 코스는 zone_cell {worst_cell}번이야. 여기로 몰리면 장타·하드히트 확률이 확 올라가니까 "
                f"무조건 피해. 대신 zone_cell {best_cell}번 위주로 승부해. "
                f"코칭으로 정리하면: {worst_cell}번은 절대 몰지 마."
            )
        if batter_result:
            prob = batter_result.get("zone_probability_scores") or {}
            in_zone = {c: v for c, v in prob.items() if c != 0}
            if not in_zone:
                return "존별 확률 데이터가 아직 부족해서 콕 짚어주기는 어려워."
            lowest_cell = min(in_zone, key=in_zone.get)
            target_cell = batter_result.get("target_zone_cell")
            return (
                f"반대로 zone_cell {lowest_cell}번은 공이 올 가능성이 제일 낮은 코스야 - 무리하게 노리면 손해야. "
                f"zone_cell {target_cell}번 위주로 노려. "
                f"코칭으로 정리하면: {lowest_cell}번은 버리고 {target_cell}번에 집중해."
            )
        return "분석부터 먼저 돌려줘야 코스 정보를 짚어줄 수 있어."

    def _explain_pitch_comparison(
        self, baseline: str, alt: str, pitcher_result: dict | None, batter_result: dict | None,
        pitch_risk_details: dict, all_pitch_scores: dict,
    ) -> str:
        """대명사로 가리킨 구종(baseline)과 새로 언급된 구종(alt)을 직접 비교한다."""
        baseline_kr, alt_kr = pitch_label_kr(baseline), pitch_label_kr(alt)
        parts = []
        baseline_detail, alt_detail = pitch_risk_details.get(baseline), pitch_risk_details.get(alt)
        if baseline_detail and alt_detail:
            parts.append(
                f"{_eun(baseline_kr)} 장타 위험 {baseline_detail['extra_base_hit_risk']:.1%}, {_eun(alt_kr)} "
                f"{alt_detail['extra_base_hit_risk']:.1%} 정도야."
            )
        baseline_score, alt_score = all_pitch_scores.get(baseline), all_pitch_scores.get(alt)
        if pitcher_result is not None:
            if baseline_score is not None and alt_score is not None:
                better = alt if alt_score > baseline_score else baseline
                better_kr = pitch_label_kr(better)
                conclusion_kr = better_kr
                parts.append(f"종합적으로는 {better_kr} 쪽이 지금 상황에서 더 유리해.")
            else:
                conclusion_kr = alt_kr
            parts.append(f"우려되면 {conclusion_kr} 쪽으로 승부하는 게 더 안전해. 다만 카운트 흐름은 계속 봐야 돼.")
            parts.append(f"코칭으로 정리하면: {_i(conclusion_kr)} 지금은 더 나은 선택이야.")
        else:
            if baseline_score is not None and alt_score is not None:
                more_likely = alt if alt_score > baseline_score else baseline
                more_likely_kr = pitch_label_kr(more_likely)
                parts.append(f"실제로 올 가능성은 {more_likely_kr} 쪽이 더 커.")
                parts.append(f"코칭으로 정리하면: {more_likely_kr} 타이밍에 맞춰놓고, 아니면 배트 멈출 준비를 해둬.")
            else:
                parts.append("코칭으로 정리하면: 확률 높은 쪽에 타이밍 맞추고 나머지는 지켜봐.")
        return " ".join(parts)

    def _explain_weakness(self, pitcher_result: dict | None, batter_result: dict | None) -> str:
        if pitcher_result and pitcher_result.get("batter_weakness"):
            return pitcher_result["batter_weakness"]["summary"]
        if batter_result and batter_result.get("pitcher_pattern"):
            return batter_result["pitcher_pattern"]["summary"]
        return "약점/패턴을 짚어주려면 먼저 분석을 돌려줘야 해."

    def _explain_opponent_batter_analysis(self, pitcher_result: dict) -> str:
        """"상대 타자에 대해 분석해줘"류 질문 전용 답변. Top-3 확률을 나열하는 대신, 투수 코치처럼
        상대 타자의 약점/강점/조심할 점과 공략 전략을 대화체로 설명한다."""
        weakness = pitcher_result.get("batter_weakness") or {}
        weak_pitch, strong_pitch = weakness.get("weak_pitch"), weakness.get("strong_pitch")
        recommended = pitcher_result.get("recommended_pitch")

        if not weak_pitch:
            return (
                "이 타자는 아직 표본이 부족해서 확실하게 약점을 짚어주긴 어려워. "
                "일단은 모델 예측이랑 기본 구사 성향 위주로 승부하면 돼. "
                "코칭으로 정리하면: 데이터 쌓이기 전까진 기본 패턴대로 가."
            )

        weak_kr = pitch_label_kr(weak_pitch)
        whiff_rate = weakness.get("summary", "")
        parts = [
            f"이 타자는 완전히 힘으로 누르는 타입이라기보다, 특정 구종에 반응 차이가 있는 타자야.",
            f"{weak_kr} 계열에는 헛스윙을 만들 여지가 있어.",
        ]
        if strong_pitch and strong_pitch != weak_pitch:
            strong_kr = pitch_label_kr(strong_pitch)
            parts.append(f"반대로 {strong_kr}처럼 애매하게 몰리는 공은 장타 위험이 있어서 조심해야 해.")
        if recommended:
            recommended_kr = pitch_label_kr(recommended)
            parts.append(f"네가 투수라면 초반엔 {recommended_kr}로 눈높이를 만들고, 승부구는 {weak_kr} 계열로 가져가는 게 좋아.")
        parts.append("핵심은 존 가운데로 '좋은 공'을 던지는 게 아니라, 이 타자가 치기 애매한 공을 던지는 거야.")
        parts.append(f"코칭으로 정리하면: {recommended_kr if recommended else '기본 구종'}로 시선 묶고, 결정구는 {weak_kr}로 가.")
        return " ".join(parts)

    def _explain_opponent_pitcher_analysis(self, batter_result: dict) -> str:
        """"상대 투수 공략법 알려줘"류 질문 전용 답변. 타격 코치처럼 상대 투수의 구종 패턴과
        노릴 구종/버릴 구종, 카운트별 대응을 대화체로 설명한다."""
        pattern = batter_result.get("pitcher_pattern") or {}
        top_pitches = pattern.get("top_pitches") or []
        target_zone = batter_result.get("target_zone")

        if not top_pitches:
            return (
                "상대 투수 데이터가 아직 부족해서 패턴을 콕 짚어주긴 어려워. "
                "일단은 모델이 뽑은 Top-3 위주로 타이밍 잡으면 돼. "
                "코칭으로 정리하면: 데이터 쌓이기 전까진 기본 확률대로 타이밍 잡아."
            )

        main = top_pitches[0]
        main_kr = pitch_label_kr(main["pitch_label"])
        parts = [f"이 투수는 {main_kr} 비중이 {main['ratio']:.0%}로 높은, 그 구종 위주로 승부 거는 타입이야."]
        parts.append(f"네가 타자라면 {target_zone} 쪽으로 타이밍을 맞춰놓는 게 좋아.")
        if len(top_pitches) >= 2:
            second = top_pitches[1]
            second_kr = pitch_label_kr(second["pitch_label"])
            parts.append(f"다만 카운트가 불리해지면 {second_kr} 계열로 유인할 수 있으니, 2스트라이크 이후엔 존 벗어나는 공은 버려.")
        parts.append(f"코칭으로 정리하면: {main_kr} 타이밍에 맞춰놓고, 2스트라이크부터는 존 안으로 오는 공에만 반응해.")
        return " ".join(parts)

    def _explain_count_strategy(
        self, pitcher_result: dict | None, batter_result: dict | None, game_context: dict | None,
    ) -> str:
        """"지금 카운트에서는 어떤 전략이 좋아?"류 질문 전용 답변. 현재 balls/strikes를 직접
        인용해 카운트 자체를 근거로 한 전략을 설명한다."""
        balls, strikes = (game_context or {}).get("balls"), (game_context or {}).get("strikes")
        count_kr = f"{balls}B-{strikes}S" if balls is not None else "현재 카운트"

        if pitcher_result:
            recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
            if strikes is not None and strikes >= 2:
                tip = "여유가 있으니까 존 경계를 살짝 벗어나는 유인구로 헛스윙 유도해봐도 돼."
            elif balls is not None and balls >= 3:
                tip = "볼넷 부담이 커지는 카운트라 존 안쪽 승부 비중을 높이는 게 안전해."
            else:
                tip = "특별히 유불리 없는 카운트라 기본 성향대로 가도 괜찮아."
            return f"지금 {count_kr}면 {recommended_kr} 위주로 가면 돼. {tip} 코칭으로 정리하면: {recommended_kr} 믿고 이 카운트는 그대로 가."

        if batter_result:
            if strikes is not None and strikes >= 2:
                tip = "2스트라이크부터는 존 벗어나는 유인구는 무조건 버리고, 존 안으로 오는 공에만 반응해."
            elif balls is not None and balls >= 3:
                tip = "투수가 스트라이크를 던져야 하는 상황이라 존 안으로 오는 공이 많아질 거야. 적극적으로 노려도 돼."
            else:
                tip = f"{batter_result['target_zone']}를 기본으로 노리면 돼."
            return f"지금 {count_kr}면, {tip} 코칭으로 정리하면: 이 카운트에서는 침착하게 존만 보고 반응해."

        return "분석을 먼저 실행하면 지금 카운트에 맞는 전략을 알려드릴 수 있습니다."

    def _explain_strong_pitch_question(self, mentioned_pitch: str, pitcher_result: dict | None) -> str:
        """"상대 타자가 커터에 강해서 그래?"류 질문. 사용자 반론의 사실 여부를 먼저 확인하고
        받아준 뒤(맞으면 인정, 틀리면 정정) 이유와 전략을 이어간다."""
        kr = pitch_label_kr(mentioned_pitch)
        if not pitcher_result:
            return f"{kr}에 대한 상대 타자 데이터는 투수 모드에서 분석을 돌려야 확인할 수 있어."
        weakness = pitcher_result.get("batter_weakness") or {}
        if weakness.get("strong_pitch") == mentioned_pitch:
            return (
                f"맞아, 그 포인트를 잘 봤어. 이 타자는 {kr}가 애매하게 존 안으로 들어오면 장타로 연결할 위험이 있어. "
                f"그래서 {kr}를 완전히 못 쓰는 건 아니지만, 지금 카운트에서 승부구로 쓰기엔 우선순위가 낮아. "
                f"네가 투수라면 {kr}는 보여주는 공 정도로만 쓰고, 결정구는 낮은 슬라이더나 포심으로 시선을 묶은 뒤 "
                "바깥쪽으로 빼는 쪽이 더 좋아. "
                f"코칭으로 정리하면: {kr}는 유인구로만 쓰고 승부는 다른 구종으로 가."
            )
        if weakness.get("weak_pitch") == mentioned_pitch:
            return (
                f"그렇게 볼 수도 있는데, 지금 데이터상으로는 반대야 - 이 타자는 오히려 {kr}에 헛스윙이 많아. "
                f"강점이 아니라 약점 쪽에 가까운 구종이야. "
                f"코칭으로 정리하면: {kr}는 자신 있게 결정구로 써도 괜찮아."
            )
        return (
            f"그 부분은 지금 데이터로는 뚜렷하게 안 보여 - {kr}에 대한 이 타자 표본이 두드러지진 않아. "
            "대신 이 타자가 진짜 강한 구종은 따로 있으니 그쪽을 조심하는 게 나아. "
            f"코칭으로 정리하면: {kr}보다 상대 약점/강점 요약에 나온 구종부터 챙겨."
        )

    def _explain_weak_pitch_question(self, mentioned_pitch: str, pitcher_result: dict | None) -> str:
        """"이 타자 슬라이더 약한 거야?"류 질문. strong_pitch_question과 대칭되는 확인/정정 답변."""
        kr = pitch_label_kr(mentioned_pitch)
        if not pitcher_result:
            return f"{kr}에 대한 상대 타자 데이터는 투수 모드에서 분석을 돌려야 확인할 수 있어."
        weakness = pitcher_result.get("batter_weakness") or {}
        if weakness.get("weak_pitch") == mentioned_pitch:
            return (
                f"맞아, {kr}에는 이 타자가 확실히 약해 - 헛스윙이 많이 나오는 구종이야. "
                f"그래서 승부구로 {kr}를 가져가는 건 좋은 선택이야, 특히 2스트라이크 이후에. "
                "다만 존 가운데로 몰리면 얘기가 달라지니까 존 경계선까지만 정확히 던져야 해. "
                f"코칭으로 정리하면: {kr}를 결정구로 믿고 가되, 존 안으로 몰리지 않게 조심해."
            )
        if weakness.get("strong_pitch") == mentioned_pitch:
            return (
                f"아니, 오히려 반대야 - 데이터상 이 타자는 {kr}에 강한 편이라 장타 위험이 있어. "
                f"그러니까 {kr}로 승부하는 건 조심스럽게 접근해야 해. "
                f"코칭으로 정리하면: {kr}는 승부구보다 유인구로만 아껴둬."
            )
        return (
            f"{kr} 단독으로는 이 타자 표본이 뚜렷하지 않아서 확실하게 약점이라고 말하긴 어려워. "
            "코칭으로 정리하면: 지금은 상대 약점 요약에 나온 확실한 구종 위주로 승부해."
        )

    def _explain_score_situation(
        self, analysis_result: dict, pitcher_result: dict | None, batter_result: dict | None,
    ) -> str:
        """"우리가 지고 있으면 더 공격적으로 가야 하지 않아?"류 질문. app.py에서 계산해 result에
        저장해둔 score_situation_label/user_score_diff를 근거로 삼는다."""
        label = analysis_result.get("score_situation_label")
        user_diff = analysis_result.get("user_score_diff")
        if label is None:
            return "지금은 점수 상황 데이터가 없어서 정확히는 답하기 어려워. 코칭으로 정리하면: 스코어를 입력하고 다시 물어봐."

        losing = user_diff is not None and user_diff < 0
        if pitcher_result:
            if losing:
                return (
                    f"지금 {label} 상황이긴 한데, 투수 입장에서는 오히려 더 침착하게 가야 해. "
                    "쫓기는 마음에 무리하게 존 안으로 몰면 장타 한 방에 더 크게 밀릴 수 있어. "
                    "코칭으로 정리하면: 위험한 코스는 피하고 기본 존 관리부터 다시 잡아."
                )
            if label == "리드":
                return (
                    "지금 리드하고 있으니까 무리할 필요 없어. 안전한 코스 위주로 카운트를 착실히 가져가는 게 맞아. "
                    "코칭으로 정리하면: 리드 지키는 데 집중하고, 위험한 승부는 아껴둬."
                )
            return (
                f"지금은 {label} 상황이야. 이런 카운트에서는 극단적으로 몰아붙이기보다 기본 위험 관리에 집중하는 게 나아. "
                "코칭으로 정리하면: 지금 추천 그대로 가되 위험한 코스만 피해."
            )
        if batter_result:
            if losing:
                return (
                    f"맞아, 지금 {label} 상황이면 좀 더 적극적으로 나가야 해 - 출루보다 한 방이 아쉬운 상황이야. "
                    "노릴 코스에 확신이 있으면 초구부터 과감하게 스윙해도 좋아. "
                    "코칭으로 정리하면: 확실한 코스면 초구부터 적극적으로 노려."
                )
            if label == "리드":
                return (
                    "지금 리드 중이니까 무리하게 스윙할 필요 없어. 확실한 공만 골라 치는 게 안전해. "
                    "코칭으로 정리하면: 무리하지 말고 확실한 코스만 노려."
                )
            return (
                f"지금은 {label} 상황이라 극단적으로 갈 필요는 없어. 노릴 코스 기본대로 가도 충분해. "
                "코칭으로 정리하면: 지금 노릴 코스 그대로 유지해."
            )
        return "분석을 먼저 실행하면 점수 상황에 맞는 전략을 짚어줄 수 있어."

    def _explain_trajectory_question(
        self, fallback_pitch: str | None, pitcher_result: dict | None,
    ) -> str:
        """"이 공은 어떻게 휘어 들어와?"류 질문. 구종별 무브먼트 특성을 말로 설명한다."""
        if not fallback_pitch:
            return "어떤 구종인지 먼저 말해주면 궤적을 설명해줄게. 코칭으로 정리하면: 구종을 콕 집어서 다시 물어봐."
        kr = pitch_label_kr(fallback_pitch)
        desc = PITCH_MOVEMENT_DESCRIPTIONS.get(fallback_pitch, PITCH_MOVEMENT_DESCRIPTIONS["OTHER"])
        parts = [f"{_eun(kr)} {desc}."]
        if pitcher_result and fallback_pitch == pitcher_result.get("recommended_pitch"):
            parts.append("그래서 지금처럼 추천 구종으로 쓰기 좋은 거야.")
        parts.append(f"코칭으로 정리하면: {kr}의 이 움직임을 이용해서 타이밍을 뺏어.")
        return " ".join(parts)

    def _explain_velocity_question(self, pitcher_result: dict | None) -> str:
        """"구속은 어느 정도로 추천해?" / "전력으로 던져?"류 질문. 최고 구속보다 제구를
        우선해야 하는 이유를 코치 말투로 설명한다."""
        if not pitcher_result:
            return "구속 얘기는 투수 모드에서 분석을 돌려야 구체적으로 짚어줄 수 있어."
        recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
        return (
            "전력으로만 던질 필요는 없어. "
            f"{_i(recommended_kr)}라도 지금 목적이 헛스윙보다 약한 타구 유도라면 최고 구속보다 제구가 먼저야. "
            f"이 투수의 {recommended_kr} 평소 구속을 기준으로 95~98% 정도 강도로 가져가고, 존 경계에 정확히 붙이는 게 더 좋아. "
            "코칭으로 정리하면: 전력투구보다 제구 유지 가능한 강한 공을 던져."
        )

    def _explain_inside_outside_risk(
        self, text: str, pitcher_result: dict | None, risk_summary: dict,
    ) -> str:
        """"안쪽은 노리다 빠질 가능성이 있는데 위험하지 않아?" / "바깥쪽으로 빠지면 볼넷
        아냐?"류 질문. 몸쪽/바깥쪽 실투가 각각 어떤 위험으로 이어지는지 구분해서 답한다."""
        if not pitcher_result:
            return "코스별 위험은 투수 모드 분석 결과가 있어야 구체적으로 짚어줄 수 있어."
        recommended_kr = pitch_label_kr(pitcher_result["recommended_pitch"])
        best_cell = pitcher_result.get("best_zone_cell")
        is_inside = any(k in text for k in ["안쪽", "몸쪽", "인코스"])
        if is_inside:
            return (
                "그 말 맞아, 안쪽/몸쪽을 노리다 빠지면 몸에 맞는 공이나 볼넷으로 이어질 위험이 있어. "
                "다만 그보다 더 조심해야 할 건 반대로 안쪽이 실투로 몰릴 때야 - 그 코스는 장타로 직결되는 코스거든. "
                f"지금 추천 존은 zone_cell {best_cell}번 쪽이니까, 거기서 반 개 정도만 안쪽으로 조절하고 완전히 몸쪽 깊숙이 넣지는 마. "
                f"코칭으로 정리하면: 안쪽은 존 경계까지만, 승부는 {recommended_kr}로 가되 완전히 몸쪽 깊게 넣진 마."
            )
        walk_risk = risk_summary.get("walk_risk")
        walk_note = f"지금 볼넷 위험은 {walk_risk:.1%} 정도야." if walk_risk is not None else "볼넷 위험 수치는 아직 표본이 부족해."
        return (
            "맞아, 바깥쪽으로 완전히 빠지면 볼넷 위험이 커지는 건 사실이야. "
            f"{walk_note} 그래도 바깥쪽은 안쪽보다 맞아도 장타로 이어질 확률이 낮은 코스라 존 경계 정도까지는 써도 괜찮아. "
            "코칭으로 정리하면: 바깥쪽은 존 경계선까지 붙이고, 완전히 존 밖으로 빼는 유인구는 스트라이크를 하나 잡은 다음에만 써."
        )

    def _explain_game_situation_sensitivity(self, analysis_result: dict) -> str:
        """"상황 바꿔도 왜 똑같아?"류 메타 질문. 분석 결과에 저장된 sensitivity_debug 수치를
        근거로 실제로 얼마나/어떻게 반영되고 있는지 정직하게 설명한다."""
        debug = analysis_result.get("sensitivity_debug") or {}
        changed = debug.get("changed_by_context")
        top_factors = debug.get("top_factors") or []
        top_label = top_factors[0]["factor"] if top_factors else None
        factor_kr = {
            "model_score": "모델 예측 확률", "pitcher_mix_score": "투수 구사 비율",
            "count_tendency_score": "카운트 성향", "batter_weakness_score": "상대 타자 약점",
            "zone_safety_score": "구종 위험도",
        }.get(top_label, top_label)
        if changed is None:
            return "지금 데이터로는 상황 변화 폭을 수치로 보여줄 수 없어. 코칭으로 정리하면: 카운트/주자/점수차를 눈으로 비교해가며 판단해."
        direction = "낮아지는" if changed < 0 else "높아지는"
        return (
            f"완전히 안 바뀐 건 아니야 - 지금 상황 보정으로 이 구종 점수가 {abs(changed):.0%}만큼 {direction} 방향으로 반영됐어. "
            "다만 그 폭이 top3 순위를 뒤집을 정도로 크지 않을 때가 많아서 추천 구종 자체는 그대로인 것처럼 보일 수 있어. "
            f"지금은 {factor_kr} 쪽이 제일 크게 작용하고 있어서, 카운트나 주자보다 그 요인이 더 우선시된 거야. "
            "코칭으로 정리하면: 추천 구종이 그대로여도, 존 위치나 위험 감수 수준은 상황에 따라 달라진다고 보면 돼."
        )

    def _explain_player_sensitivity(self, analysis_result: dict) -> str:
        """"선수 바꿔도 왜 똑같아?"류 메타 질문. sensitivity_debug의 changed_by_player 수치로
        상대 타자 약점이 실제로 얼마나 반영되는지 설명한다."""
        debug = analysis_result.get("sensitivity_debug") or {}
        changed = debug.get("changed_by_player")
        pitcher_result = analysis_result.get("pitcher_mode_result")
        if changed is None:
            return "지금은 타자 모드라 상대 선수(투수) 약점 대신 카운트별 패턴으로 예상 구종을 잡고 있어. 코칭으로 정리하면: 투수를 바꾸면 카운트별 패턴부터 달라져."
        weakness = (pitcher_result or {}).get("batter_weakness") or {}
        weak_pitch_kr = pitch_label_kr(weakness["weak_pitch"]) if weakness.get("weak_pitch") else None
        note = f" 지금 이 타자는 {weak_pitch_kr}에 약점이 잡혀서 그 점수가 올라간 거야." if weak_pitch_kr else ""
        return (
            f"완전히 똑같지는 않아 - 상대 타자 약점 점수가 지금 추천 구종 점수에 {changed:.2f}만큼 반영되고 있어.{note} "
            "다만 이 투수 레퍼토리 자체가 특정 구종 쏠림이 강하면, 타자 약점 하나로 순위 전체가 뒤집히진 않아. "
            "코칭으로 정리하면: 추천 구종이 같아 보여도 Top-3 확률이나 강점/약점 요약은 선수마다 달라지니 그쪽을 같이 봐."
        )

    def _explain_repetition_complaint(
        self, pitcher_result: dict | None, batter_result: dict | None,
        score_breakdown: dict, explicit_complaint: bool = True,
    ) -> str:
        """"같은 말을 계속해 왜?"류 불만, 그리고 명시적 불만이 없어도 직전 답변과 사실상 같은
        내용이 감지됐을 때(_is_repetitive) 재사용하는 "관점 전환" 답변. 추천 구종의 실제
        score_breakdown 수치를 근거로 왜 결론이 반복되는지 설명하고, 다른 각도의 코칭 포인트로
        넘어간다."""
        opener = (
            "맞아, 방금 답변이 너무 같은 결론으로 반복됐어. 다시 정리할게."
            if explicit_complaint else
            "이건 아까랑 비슷한 답이 될 뻔했는데, 각도를 바꿔서 설명할게."
        )
        if pitcher_result:
            recommended = pitcher_result["recommended_pitch"]
            recommended_kr = pitch_label_kr(recommended)
            detail = (score_breakdown or {}).get(recommended, {})
            mix_score = detail.get("pitcher_mix_score")
            context_adj = detail.get("context_adjustment")
            parts = [
                opener,
                "네가 지금 물은 건 '추천 구종'이 아니라 '왜 이 상황에서 선택이 달라지지 않느냐'에 가까워.",
            ]
            if mix_score is not None and mix_score > 0.08:
                parts.append(
                    f"현재 모델은 {_i(recommended_kr)} 구사 비율이 큰 투수일수록 {_eun(recommended_kr)} 쪽으로 끌리는 경향이 있어서, "
                    "상황 변화가 충분히 크게 보이지 않을 수 있어."
                )
            else:
                parts.append(f"지금은 {_i(recommended_kr)} 여러 지표를 종합했을 때 계속 앞서고 있어서 답이 비슷하게 나온 거야.")
            if context_adj is not None:
                pct = (context_adj - 1.0) * 100
                parts.append(f"실제로 지금 상황 보정값은 {pct:+.0f}% 정도로만 반영되고 있어서 체감이 크지 않을 수 있어.")
            parts.append("그래서 실제 코칭 관점에서는 카운트·주자·점수차를 더 강하게 반영해서 위험 구종을 낮추는 식으로 보정해야 해.")
            parts.append(f"코칭으로 정리하면: 지금 상황에서는 {recommended_kr} 비중은 유지하되, 위험 구종 감점 폭을 넓혀서 대안을 더 자주 섞어야 해.")
            return " ".join(parts)
        if batter_result:
            target = batter_result.get("target_zone")
            pattern = batter_result.get("pitcher_pattern") or {}
            return " ".join([
                opener,
                f"네가 물은 건 결국 '왜 상황이 바뀌어도 노릴 코스가 그대로냐'에 가까워.",
                f"지금 상대 투수 패턴이 {pattern.get('summary', '뚜렷한 쏠림')} 쪽으로 고정돼 있어서, 노릴 코스({target})가 잘 안 바뀌는 거야.",
                "코칭으로 정리하면: 노릴 코스는 유지하되, 카운트가 바뀌면 스윙 타이밍만 더 적극적으로 조절해.",
            ])
        return "맞아, 답변이 반복됐네. 아직 분석 데이터가 부족해서 다른 각도로 설명하기 어려워 - 분석을 다시 돌려보면 더 짚어줄 수 있어."

    def _last_assistant_answer(self, history: list[dict] | None) -> str | None:
        for turn in reversed(history or []):
            if isinstance(turn, dict) and turn.get("role") == "assistant":
                return turn.get("content", "")
        return None

    def _is_repetitive(self, new_answer: str, last_answer: str | None) -> bool:
        """직전 답변과 새 답변의 단어 집합 유사도(Jaccard)가 높으면 사실상 같은 내용을
        반복한 것으로 본다 - "포심으로 승부하고 커터는 아껴둬" 같은 문장이 서로 다른 질문에도
        계속 나오는 문제를 잡기 위한 안전망이다."""
        if not last_answer:
            return False
        a, b = set(new_answer.split()), set(last_answer.split())
        if not a or not b:
            return False
        overlap = len(a & b) / len(a | b)
        return overlap >= 0.55
