"""
NeuroCI — Patch Generator.

LLM Call #2: Generates targeted code patches using chain-of-thought reasoning.
Injects few-shot examples from ChromaDB for context-aware repair.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_factory import get_chat_llm
from src.agent.prompts import (
    ASSERTION_DECISION_PROMPT,
    FEW_SHOT_EXAMPLE,
    FEW_SHOT_TEMPLATE,
    REPAIR_SYSTEM_PROMPT,
    REPAIR_USER_PROMPT,
    RETRY_SYSTEM_PROMPT,
    RETRY_USER_PROMPT,
)
from src.config import get_settings
from src.models import AgentState, FilePatch, PatchResult

logger = structlog.get_logger()


def _build_few_shot_section(state: AgentState) -> str:
    """Build the few-shot examples section from similar past fixes."""
    if not state.similar_fixes:
        return ""

    examples = []
    for i, fix in enumerate(state.similar_fixes[:3], 1):
        example = FEW_SHOT_EXAMPLE.format(
            index=i,
            similarity=fix.similarity_score,
            outcome=fix.outcome,
            failure_log=fix.failure_log[:500],
            fix_diff=fix.fix_diff[:800],
        )
        examples.append(example)

    return FEW_SHOT_TEMPLATE.format(examples="\n".join(examples))


def _parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse LLM JSON response, handling markdown code blocks and conversational wrapper."""
    text = response_text.strip()

    # Regex to find JSON block in markdown
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    else:
        # Fallback: search for first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1].strip()

    return cast(dict[str, Any], json.loads(text))


async def decide_assertion_fix_target(state: AgentState) -> dict[str, Any]:
    """Decide whether to fix the test or the source code for TestAssertion failures."""
    if not state.parsed_error:
        raise ValueError("parsed_error is required")

    llm = get_chat_llm(temperature=0.1, max_tokens=500)

    prompt = f"""\
Analyze the test failure below. Decide whether we should fix the IMPLEMENTATION (source code) or the TEST itself.

**File with failing test:** {state.parsed_error.file_path}
**Error Type:** {state.parsed_error.error_type}
**Error Message:** {state.parsed_error.error_message}

**Traceback/Log:**
```
{state.parsed_error.raw_log[:4000]}
```

**Test File Content:**
```python
{state.file_content}
```
"""
    messages = [
        SystemMessage(content=ASSERTION_DECISION_PROMPT),
        HumanMessage(content=prompt)
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_llm_response(content)
    except Exception as e:
        logger.error("patch_generator.decide_target_error", error=str(e))
        return {"fix_target": "test", "target_file": state.parsed_error.file_path, "reasoning": "Fallback to test file"}


async def validate_pypi_package(package: str, version: str | None = None) -> str | None:
    """Validate package and version on PyPI. Returns the valid version to use, or None."""
    import httpx
    url = f"https://pypi.org/pypi/{package}/json"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=5.0)
            if resp.status_code != 200:
                return None
            data = resp.json()
            releases = data.get("releases", {})
            if version:
                if version in releases:
                    return version
            return cast(str | None, data.get("info", {}).get("version"))
        except Exception:
            return None


async def extract_dependency_info(state: AgentState) -> dict[str, Any]:
    """Extract package name and version from dependency error log."""
    if not state.parsed_error:
        raise ValueError("parsed_error is required")

    llm = get_chat_llm(temperature=0.1, max_tokens=150)
    prompt = f"""\
Analyze the dependency conflict or import error below. Extract the name of the package that needs to be added, updated, or fixed, and a proposed version.

**Error Message:** {state.parsed_error.error_message}
**Traceback/Log:**
```
{state.parsed_error.raw_log[:3000]}
```

Respond with ONLY a JSON object:
{{
  "package_name": "name of python package on PyPI (e.g. boto3, urllib3)",
  "proposed_version": "version number (e.g. 1.28.0), or empty string if not specified"
}}
"""
    messages = [
        SystemMessage(content="You are a package manager helper."),
        HumanMessage(content=prompt)
    ]
    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_llm_response(content)
    except Exception as e:
        logger.error("patch_generator.extract_dependency_error", error=str(e))
        return {}


async def generate_patch(state: AgentState) -> AgentState:
    """
    Generate a code patch using chain-of-thought reasoning.

    The LLM receives:
    - The failure log
    - The erroring file's content
    - Top-3 similar past fixes (few-shot examples from ChromaDB)

    And produces:
    - Step-by-step reasoning
    - A unified diff patch
    - Confidence score
    - PR description
    """
    get_settings()

    parsed_error = state.parsed_error
    if not parsed_error:
        logger.warning("patch_generator.no_error", run_id=state.run_id)
        return state

    # ── Step 2a: For TestAssertion, decide whether to fix source or test ──
    from src.models import FailureCategory
    if state.category == FailureCategory.TEST_ASSERTION:
        target_info = await decide_assertion_fix_target(state)
        target_file = target_info.get("target_file")
        if target_file and target_file != parsed_error.file_path:
            logger.info("patch_generator.assertion_target_changed", original=parsed_error.file_path, new=target_file, reasoning=target_info.get("reasoning"))
            parsed_error.file_path = target_file

            # Fetch the new target file content
            from src.pipeline.github_client import GitHubClient
            github = GitHubClient()
            try:
                state.file_content = await github.get_file_content(
                    state.repo_full_name,
                    target_file,
                    ref=state.head_sha
                ) or ""
                state.file_contents[target_file] = state.file_content
            except Exception as e:
                logger.error("patch_generator.fetch_target_failed", error=str(e), file=target_file)
            finally:
                await github.close()

    # ── Step 2b: For ImportError/DependencyVersionConflict, target requirements.txt ──
    elif state.category in (FailureCategory.IMPORT_ERROR, FailureCategory.DEPENDENCY_VERSION_CONFLICT):
        from src.pipeline.github_client import GitHubClient
        github = GitHubClient()
        try:
            req_content = await github.get_file_content(state.repo_full_name, "requirements.txt", ref=state.head_sha)
            if req_content is not None:
                # Extract dependency info
                dep_info = await extract_dependency_info(state)
                pkg_name = dep_info.get("package_name")
                proposed_ver = dep_info.get("proposed_version")
                if pkg_name:
                    valid_ver = await validate_pypi_package(pkg_name, proposed_ver)
                    if valid_ver:
                        logger.info("patch_generator.dependency_verified", package=pkg_name, version=valid_ver)
                        parsed_error.file_path = "requirements.txt"
                        parsed_error.language = "requirements"
                        state.file_content = req_content
                        state.file_contents["requirements.txt"] = req_content
                        # We also update error message slightly so LLM knows exactly what version is verified
                        parsed_error.error_message = f"Add or update package '{pkg_name}' to version '{valid_ver}' in requirements.txt. PyPI validation successful."
        except Exception as e:
            logger.error("patch_generator.dependency_handling_failed", error=str(e))
        finally:
            await github.close()

    # ── Build few-shot section ──
    few_shot_section = _build_few_shot_section(state)

    # ── Build user prompt ──
    user_prompt = REPAIR_USER_PROMPT.format(
        category=state.category.value,
        file_path=parsed_error.file_path,
        error_type=parsed_error.error_type,
        error_message=parsed_error.error_message,
        log_excerpt=parsed_error.raw_log[:6000],
        language=parsed_error.language,
        file_content=state.file_content[:8000] if state.file_content else "[File content not available]",
        few_shot_section=few_shot_section,
    )

    # ── LLM Call (uses configured provider) ──
    llm = get_chat_llm(temperature=0.1, max_tokens=2000)

    messages = [
        SystemMessage(content=REPAIR_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        result = _parse_llm_response(content)

        patches_list = []
        if "patches" in result:
            for p in result["patches"]:
                patches_list.append(
                    FilePatch(
                        target_file=p.get("target_file", parsed_error.file_path),
                        unified_diff=p.get("unified_diff", ""),
                        lines_changed=int(p.get("lines_changed", 0))
                    )
                )
        else:
            patches_list.append(
                FilePatch(
                    target_file=result.get("target_file", parsed_error.file_path),
                    unified_diff=result.get("unified_diff", ""),
                    lines_changed=int(result.get("lines_changed", 0))
                )
            )

        state.patch = PatchResult(
            confidence=float(result.get("confidence", 0.0)),
            reasoning=result.get("reasoning", ""),
            pr_description=result.get("pr_description", ""),
            patches=patches_list,
            unified_diff=result.get("unified_diff", "") or (patches_list[0].unified_diff if patches_list else ""),
            target_file=result.get("target_file", "") or (patches_list[0].target_file if patches_list else ""),
            lines_changed=int(result.get("lines_changed", 0)) or sum(p.lines_changed for p in patches_list),
        )

        logger.info(
            "patch_generator.generated",
            run_id=state.run_id,
            confidence=state.patch.confidence,
            patches_count=len(state.patch.patches),
        )

    except json.JSONDecodeError as e:
        logger.error("patch_generator.json_error", error=str(e), run_id=state.run_id)
    except Exception as e:
        logger.error("patch_generator.llm_error", error=str(e), run_id=state.run_id)

    return state


async def retry_patch(
    state: AgentState,
    validation_error: str,
    previous_diff: str,
) -> AgentState:
    """
    Retry patch generation with the validation error fed back as context.
    This is called when the first patch fails syntax validation.
    """
    get_settings()

    parsed_error = state.parsed_error
    if not parsed_error:
        return state

    user_prompt = RETRY_USER_PROMPT.format(
        file_path=parsed_error.file_path,
        validation_error=validation_error,
        previous_diff=previous_diff,
        language=parsed_error.language,
        file_content=state.file_content[:8000] if state.file_content else "",
    )

    llm = get_chat_llm(temperature=0.1, max_tokens=2000)

    messages = [
        SystemMessage(content=RETRY_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        result = _parse_llm_response(content)

        patches_list = []
        if "patches" in result:
            for p in result["patches"]:
                patches_list.append(
                    FilePatch(
                        target_file=p.get("target_file", parsed_error.file_path),
                        unified_diff=p.get("unified_diff", ""),
                        lines_changed=int(p.get("lines_changed", 0))
                    )
                )
        else:
            patches_list.append(
                FilePatch(
                    target_file=result.get("target_file", parsed_error.file_path),
                    unified_diff=result.get("unified_diff", ""),
                    lines_changed=int(result.get("lines_changed", 0))
                )
            )

        state.patch = PatchResult(
            confidence=float(result.get("confidence", 0.0)),
            reasoning=result.get("reasoning", ""),
            pr_description=result.get("pr_description", ""),
            patches=patches_list,
            unified_diff=result.get("unified_diff", "") or (patches_list[0].unified_diff if patches_list else ""),
            target_file=result.get("target_file", "") or (patches_list[0].target_file if patches_list else ""),
            lines_changed=int(result.get("lines_changed", 0)) or sum(p.lines_changed for p in patches_list),
        )

        logger.info(
            "patch_generator.retry_generated",
            run_id=state.run_id,
            confidence=state.patch.confidence,
        )

    except Exception as e:
        logger.error("patch_generator.retry_error", error=str(e), run_id=state.run_id)

    return state
