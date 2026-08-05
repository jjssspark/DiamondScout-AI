"""CoachAgent의 LLM 백엔드 전환(ollama/groq/규칙 기반 폴백) 로직 테스트.

실제 Ollama 서버나 Groq API 키 없이도 항상 돌아가도록 requests 호출을 mock으로 격리한다.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import coach_agent as coach_agent_module
from services.coach_agent import CoachAgent

FOCUS = {"focus_type": "recommendation", "user_concern": "전반적인 추천 근거"}
EVIDENCE = {"mode": "pitcher", "recommended_pitch_kr": "포심"}
CONV_STATE = {"mode": "pitcher", "last_user_question": None, "last_assistant_answer": None}


class TestIsLlmAvailable:
    def test_groq_backend_unavailable_without_api_key(self):
        agent = CoachAgent(llm_backend="groq")
        with patch.object(coach_agent_module, "GROQ_API_KEY", ""):
            assert agent._is_llm_available() is False

    def test_groq_backend_available_with_api_key(self):
        agent = CoachAgent(llm_backend="groq")
        with patch.object(coach_agent_module, "GROQ_API_KEY", "fake-key"):
            assert agent._is_llm_available() is True

    def test_ollama_backend_checks_ollama_server(self):
        agent = CoachAgent(llm_backend="ollama")
        with patch.object(agent, "_is_ollama_available", return_value=True) as mock_check:
            assert agent._is_llm_available() is True
            mock_check.assert_called_once()


class TestGenerateCoachResponse:
    def test_groq_backend_falls_back_to_rule_based_without_api_key(self):
        agent = CoachAgent(llm_backend="groq")
        with patch.object(coach_agent_module, "GROQ_API_KEY", ""):
            answer, source = agent._generate_coach_response("질문", FOCUS, EVIDENCE, CONV_STATE)

        assert source == "rule_based"
        assert answer

    def test_groq_backend_uses_groq_response_when_available(self):
        agent = CoachAgent(llm_backend="groq")
        with patch.object(coach_agent_module, "GROQ_API_KEY", "fake-key"), \
             patch.object(agent, "_call_groq", return_value="포심으로 가는 게 맞아") as mock_call:
            answer, source = agent._generate_coach_response("질문", FOCUS, EVIDENCE, CONV_STATE)

        mock_call.assert_called_once()
        assert source == "groq"
        assert answer == "포심으로 가는 게 맞아"

    def test_groq_failure_falls_back_to_rule_based(self):
        agent = CoachAgent(llm_backend="groq")
        with patch.object(coach_agent_module, "GROQ_API_KEY", "fake-key"), \
             patch.object(agent, "_call_groq", side_effect=ValueError("Groq 응답이 비어 있음")):
            answer, source = agent._generate_coach_response("질문", FOCUS, EVIDENCE, CONV_STATE)

        assert source == "rule_based"
        assert answer


class TestCallGroq:
    def test_call_groq_parses_openai_style_response(self):
        agent = CoachAgent(llm_backend="groq")
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "  답변 내용  "}}]}
        mock_response.raise_for_status.return_value = None

        with patch.object(coach_agent_module.requests, "post", return_value=mock_response) as mock_post:
            result = agent._call_groq("프롬프트")

        assert result == "답변 내용"
        called_url = mock_post.call_args[0][0]
        assert called_url == "https://api.groq.com/openai/v1/chat/completions"

    def test_call_groq_raises_on_empty_content(self):
        agent = CoachAgent(llm_backend="groq")
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "   "}}]}
        mock_response.raise_for_status.return_value = None

        with patch.object(coach_agent_module.requests, "post", return_value=mock_response):
            with pytest.raises(ValueError, match="Groq 응답이 비어 있음"):
                agent._call_groq("프롬프트")
