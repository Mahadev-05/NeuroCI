from __future__ import annotations

import json
from typing import Any, cast

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_factory import get_chat_llm
from src.agent.prompts import (
    DEBATE_AGENT_SYSTEM_PROMPT,
    DEBATE_JUDGE_SYSTEM_PROMPT,
    DEBATE_JUDGE_USER_PROMPT,
    REPAIR_USER_PROMPT,
)
from src.config import get_settings
from src.models import AgentState, PatchResult

logger = structlog.get_logger()


async def _gen_agent_patch(state: AgentState, agent_id: int, temp: float) -> dict[str, Any]:
    """Generate a patch from one debate agent."""
    get_settings()
    pe = state.parsed_error
    user_prompt = REPAIR_USER_PROMPT.format(
        category=state.category.value,
        file_path=pe.file_path if pe else "",
        error_type=pe.error_type if pe else "",
        error_message=pe.error_message if pe else "",
        log_excerpt=pe.raw_log[:4000] if pe else "",
        language=pe.language if pe else "python",
        file_content=state.file_content[:6000] if state.file_content else "",
        few_shot_section="",
    )
    llm = get_chat_llm(temperature=temp, max_tokens=1500)
    msgs = [SystemMessage(content=DEBATE_AGENT_SYSTEM_PROMPT.format(agent_id=agent_id)),
            HumanMessage(content=user_prompt)]
    try:
        resp = await llm.ainvoke(msgs)
        resp_content = resp.content if isinstance(resp.content, str) else str(resp.content)
        text = resp_content.strip()
        if text.startswith("```"):
            lines = [line for line in text.split("\n") if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return cast(dict[str, Any], json.loads(text))
    except Exception as e:
        logger.error(f"debate.agent_{agent_id}_error", error=str(e))
        return {}


async def debate_and_select(state: AgentState) -> AgentState:
    """Two agents compete, judge picks safer patch."""
    get_settings()
    logger.info("debate.starting", run_id=state.run_id)

    p1 = await _gen_agent_patch(state, 1, 0.1)
    p2 = await _gen_agent_patch(state, 2, 0.3)

    if not p1 and not p2:
        logger.error("debate.both_failed", run_id=state.run_id)
        return state
    if not p1:
        p1 = p2
    if not p2:
        p2 = p1

    pe = state.parsed_error
    judge_prompt = DEBATE_JUDGE_USER_PROMPT.format(
        category=state.category.value,
        error_message=pe.error_message if pe else "",
        file_path=pe.file_path if pe else "",
        patch_1=p1.get("unified_diff", ""), reasoning_1=p1.get("reasoning", ""),
        confidence_1=p1.get("confidence", 0.0), risk_1=p1.get("risk_assessment", "Unknown"),
        patch_2=p2.get("unified_diff", ""), reasoning_2=p2.get("reasoning", ""),
        confidence_2=p2.get("confidence", 0.0), risk_2=p2.get("risk_assessment", "Unknown"),
    )

    judge = get_chat_llm(temperature=0.0, max_tokens=500)
    try:
        jr = await judge.ainvoke([SystemMessage(content=DEBATE_JUDGE_SYSTEM_PROMPT),
                                  HumanMessage(content=judge_prompt)])
        jr_content = jr.content if isinstance(jr.content, str) else str(jr.content)
        text = jr_content.strip()
        if text.startswith("```"):
            lines = [line for line in text.split("\n") if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        verdict = json.loads(text)
        chosen = p1 if verdict.get("chosen_agent") == 1 else p2
        state.patch = PatchResult(
            unified_diff=chosen.get("unified_diff", ""),
            confidence=float(verdict.get("final_confidence", chosen.get("confidence", 0.0))),
            reasoning=f"[DEBATE] {verdict.get('reasoning', '')}",
            pr_description=chosen.get("pr_description", ""),
            target_file=chosen.get("target_file", pe.file_path if pe else ""),
            lines_changed=int(chosen.get("lines_changed", 0)),
        )
        logger.info("debate.verdict", chosen=verdict.get("chosen_agent"),
                     confidence=state.patch.confidence)
    except Exception as e:
        logger.error("debate.judge_error", error=str(e))
        state.patch = PatchResult(
            unified_diff=p1.get("unified_diff", ""),
            confidence=float(p1.get("confidence", 0.0)),
            reasoning=f"[FALLBACK] {p1.get('reasoning', '')}",
            target_file=p1.get("target_file", ""),
            lines_changed=int(p1.get("lines_changed", 0)),
        )
    return state
