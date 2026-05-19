"""
NeuroCI — Failure Classifier.

LLM Call #1: Classifies CI failures into one of 10 categories.
This is a fast, cheap call that determines the repair strategy.

Non-patchable categories (FlakyTest, AuthError, NetworkTimeout)
are handled differently — no patch is attempted.
"""

from __future__ import annotations

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_factory import get_chat_llm
from src.agent.prompts import CLASSIFICATION_SYSTEM_PROMPT, CLASSIFICATION_USER_PROMPT
from src.config import get_settings
from src.models import AgentState, FailureCategory

logger = structlog.get_logger()


async def classify_failure(state: AgentState) -> AgentState:
    """
    Classify the CI failure into one of 10 canonical categories.

    Uses a fast LLM call with structured output.
    Updates state.category with the classification result.
    """
    get_settings()

    if not state.parsed_error:
        logger.warning("classifier.no_parsed_error", run_id=state.run_id)
        state.category = FailureCategory.UNKNOWN
        return state

    # ── Build the prompt ──
    user_prompt = CLASSIFICATION_USER_PROMPT.format(
        workflow_name=state.workflow_name,
        repo=state.repo_full_name,
        branch=state.head_branch,
        failed_step=state.parsed_error.failed_step,
        log_excerpt=state.parsed_error.raw_log[:4000],  # Use first 4k chars for classification
    )

    # ── LLM Call (uses configured provider: gemini/groq/ollama/openai) ──
    llm = get_chat_llm(temperature=0.0, max_tokens=200)

    messages = [
        SystemMessage(content=CLASSIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        result_text = response.content.strip()

        # ── Parse JSON response ──
        # Handle markdown code blocks if the LLM wraps its response
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        result = json.loads(result_text)
        category_str = result.get("category", "Unknown")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")

        # ── Map to enum ──
        try:
            state.category = FailureCategory(category_str)
        except ValueError:
            logger.warning(
                "classifier.unknown_category",
                raw_category=category_str,
                run_id=state.run_id,
            )
            state.category = FailureCategory.UNKNOWN

        logger.info(
            "classifier.result",
            run_id=state.run_id,
            category=state.category.value,
            confidence=confidence,
            reasoning=reasoning,
            is_patchable=state.category.is_patchable,
            is_high_risk=state.category.is_high_risk,
        )

    except json.JSONDecodeError as e:
        logger.error("classifier.json_parse_error", error=str(e), run_id=state.run_id)
        state.category = FailureCategory.UNKNOWN

    except Exception as e:
        logger.error("classifier.llm_error", error=str(e), run_id=state.run_id)
        state.category = FailureCategory.UNKNOWN

    return state
