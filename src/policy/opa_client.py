"""
NeuroCI — OPA Policy Client.

Evaluates Rego policies before any PR is created.
Enforces: confidence thresholds, file path restrictions, branch protection.
"""

from __future__ import annotations

import httpx
import structlog

from src.config import Settings, get_settings
from src.models import AgentState, PolicyInput

logger = structlog.get_logger()


async def evaluate_policy(state: AgentState) -> AgentState:
    """
    Evaluate OPA policy to determine if the patch is allowed.
    Sends the PolicyInput document to OPA and reads the allow decision.
    Falls back to local evaluation if OPA is unavailable.
    """
    settings = get_settings()

    if not state.patch:
        state.policy_allowed = False
        state.policy_reason = "No patch to evaluate"
        return state

    policy_input = PolicyInput(
        repo=state.repo_full_name,
        branch=state.head_branch,
        target_file=state.patch.target_file,
        confidence=state.patch.confidence,
        category=state.category.value,
        lines_changed=state.patch.lines_changed,
        restricted_paths=settings.restricted_paths_list,
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.opa_url}/{settings.opa_policy_path}",
                json={"input": policy_input.model_dump()},
            )
            response.raise_for_status()
            result = response.json()

            allowed = result.get("result", False)
            state.policy_allowed = allowed
            state.policy_reason = "" if allowed else "OPA policy denied"

            logger.info("policy.evaluated", allowed=allowed, run_id=state.run_id)

    except Exception as e:
        logger.warning("policy.opa_unavailable", error=str(e), run_id=state.run_id)
        # Fallback: local policy evaluation
        state = _local_policy_check(state, settings)

    return state


def _local_policy_check(state: AgentState, settings: Settings) -> AgentState:
    """Fallback local policy when OPA is unavailable."""
    reasons = []

    # Rule 1: restricted paths
    if state.patch and settings.is_path_restricted(state.patch.target_file):
        reasons.append(f"Restricted path: {state.patch.target_file}")

    # Rule 2: main branch requires high confidence
    if state.head_branch == "main" and state.patch and state.patch.confidence < 0.92:
        reasons.append(f"Main branch requires ≥0.92 confidence (got {state.patch.confidence})")

    # Rule 3: patch size limit
    if state.patch and state.patch.lines_changed > settings.neuroci_max_patch_lines:
        reasons.append(f"Patch too large: {state.patch.lines_changed} lines")

    state.policy_allowed = len(reasons) == 0
    state.policy_reason = "; ".join(reasons) if reasons else ""

    logger.info("policy.local_fallback", allowed=state.policy_allowed, reasons=reasons)
    return state
