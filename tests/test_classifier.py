"""
NeuroCI — Classifier Tests.

Tests for LLM failure classification with mocked LLM responses.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import AgentState, FailureCategory, ParsedError


class TestClassifier:
    """Test failure classification logic."""

    def _make_state(self, raw_log: str = "ModuleNotFoundError: No module named 'foo'") -> AgentState:
        return AgentState(
            run_id=100,
            repo_full_name="owner/repo",
            head_branch="main",
            head_sha="abc123",
            workflow_name="CI",
            parsed_error=ParsedError(
                raw_log=raw_log,
                error_type="ModuleNotFoundError",
                error_message="No module named 'foo'",
                file_path="src/main.py",
                failed_step="Run tests",
            ),
        )

    @pytest.mark.asyncio
    async def test_classify_import_error(self):
        """LLM returns ImportError classification."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "category": "ImportError",
            "confidence": 0.95,
            "reasoning": "Missing module import"
        })

        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state()
            result = await classify_failure(state)

            assert result.category == FailureCategory.IMPORT_ERROR

    @pytest.mark.asyncio
    async def test_classify_syntax_error(self):
        """LLM returns SyntaxError classification."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "category": "SyntaxError",
            "confidence": 0.90,
            "reasoning": "Invalid Python syntax"
        })

        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state("SyntaxError: unexpected EOF while parsing")
            result = await classify_failure(state)

            assert result.category == FailureCategory.SYNTAX_ERROR

    @pytest.mark.asyncio
    async def test_classify_handles_markdown_wrapped_json(self):
        """LLM returns JSON wrapped in markdown code blocks."""
        mock_response = MagicMock()
        mock_response.content = '```json\n{"category": "TestAssertion", "confidence": 0.88, "reasoning": "test"}\n```'

        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state()
            result = await classify_failure(state)

            assert result.category == FailureCategory.TEST_ASSERTION

    @pytest.mark.asyncio
    async def test_classify_handles_invalid_json(self):
        """Invalid JSON from LLM should fall back to UNKNOWN."""
        mock_response = MagicMock()
        mock_response.content = "this is not json"

        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state()
            result = await classify_failure(state)

            assert result.category == FailureCategory.UNKNOWN

    @pytest.mark.asyncio
    async def test_classify_handles_unknown_category(self):
        """Unknown category string should map to UNKNOWN enum."""
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "category": "NonExistentCategory",
            "confidence": 0.5,
            "reasoning": "test"
        })

        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state()
            result = await classify_failure(state)

            assert result.category == FailureCategory.UNKNOWN

    @pytest.mark.asyncio
    async def test_classify_no_parsed_error(self):
        """No parsed error should return UNKNOWN."""
        from src.agent.classifier import classify_failure

        state = AgentState(
            run_id=100,
            repo_full_name="owner/repo",
            head_branch="main",
            head_sha="abc123",
        )
        result = await classify_failure(state)
        assert result.category == FailureCategory.UNKNOWN

    @pytest.mark.asyncio
    async def test_classify_handles_llm_exception(self):
        """LLM exception should fall back to UNKNOWN."""
        with patch("src.agent.classifier.get_chat_llm") as mock_llm:
            llm_instance = MagicMock()
            llm_instance.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))
            mock_llm.return_value = llm_instance

            from src.agent.classifier import classify_failure
            state = self._make_state()
            result = await classify_failure(state)

            assert result.category == FailureCategory.UNKNOWN
