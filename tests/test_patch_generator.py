"""
NeuroCI — Patch Generator Tests.

Tests for CoT patch generation and retry logic with mocked LLM.
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.models import AgentState, ParsedError, FailureCategory, SimilarFix


def _make_state() -> AgentState:
    return AgentState(
        run_id=100, repo_full_name="o/r", head_branch="main", head_sha="abc",
        category=FailureCategory.IMPORT_ERROR,
        parsed_error=ParsedError(
            raw_log="ModuleNotFoundError: No module named 'foo'",
            error_type="ModuleNotFoundError",
            error_message="No module named 'foo'",
            file_path="src/main.py",
            language="python",
        ),
        file_content="import os\nimport sys\n\ndef main():\n    from foo import bar\n",
    )


class TestPatchGenerator:
    @pytest.mark.asyncio
    async def test_generate_patch_success(self):
        resp = MagicMock()
        resp.content = json.dumps({
            "reasoning": "Step 1: fix import",
            "unified_diff": "@@ -1,2 +1,3 @@\n import os\n+import foo\n",
            "confidence": 0.92, "pr_description": "Fix import",
            "target_file": "src/main.py", "lines_changed": 1,
        })
        with patch("src.agent.patch_generator.get_chat_llm") as m:
            inst = MagicMock(); inst.ainvoke = AsyncMock(return_value=resp)
            m.return_value = inst
            from src.agent.patch_generator import generate_patch
            result = await generate_patch(_make_state())
            assert result.patch is not None
            assert result.patch.confidence == 0.92

    @pytest.mark.asyncio
    async def test_generate_patch_llm_failure(self):
        with patch("src.agent.patch_generator.get_chat_llm") as m:
            inst = MagicMock()
            inst.ainvoke = AsyncMock(side_effect=Exception("timeout"))
            m.return_value = inst
            from src.agent.patch_generator import generate_patch
            result = await generate_patch(_make_state())
            assert result.patch is None

    @pytest.mark.asyncio
    async def test_retry_patch(self):
        resp = MagicMock()
        resp.content = json.dumps({
            "unified_diff": "@@ fixed @@", "confidence": 0.88,
            "reasoning": "fixed", "target_file": "src/main.py",
            "lines_changed": 1, "pr_description": "retry fix",
        })
        with patch("src.agent.patch_generator.get_chat_llm") as m:
            inst = MagicMock(); inst.ainvoke = AsyncMock(return_value=resp)
            m.return_value = inst
            from src.agent.patch_generator import retry_patch
            state = _make_state()
            result = await retry_patch(state, "SyntaxError", "old diff")
            assert result.patch is not None
            assert result.patch.confidence == 0.88


class TestFewShotBuilder:
    def test_build_few_shot_empty(self):
        from src.agent.patch_generator import _build_few_shot_section
        state = _make_state()
        assert _build_few_shot_section(state) == ""

    def test_build_few_shot_with_fixes(self):
        from src.agent.patch_generator import _build_few_shot_section
        state = _make_state()
        state.similar_fixes = [
            SimilarFix(failure_log="err", fix_diff="diff",
                       category="ImportError", outcome="success",
                       similarity_score=0.85),
        ]
        result = _build_few_shot_section(state)
        assert "Past Fix #1" in result
        assert "0.85" in result
