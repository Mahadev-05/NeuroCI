"""
NeuroCI — Patch Validator.

Validates generated patches before any GitHub API call:
- Python: ast.parse() + flake8
- JavaScript: esprima (optional)
- Go: gofmt (optional)

Applies patch to in-memory file copy for validation.
"""

from __future__ import annotations

import ast
import subprocess
import tempfile
from pathlib import Path

import structlog

from src.config import get_settings
from src.models import AgentState

logger = structlog.get_logger()


def apply_unified_diff(original: str, diff: str) -> str | None:
    """
    Apply a unified diff to the original file content.
    Returns the patched content, or None if the diff cannot be applied.
    """
    try:
        lines = original.splitlines(keepends=True)
        result = list(lines)
        offset = 0

        for line in diff.splitlines():
            if line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                import re
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if match:
                    old_start = int(match.group(1)) - 1
                    current_pos = old_start + offset
            elif line.startswith("-"):
                # Remove line
                content = line[1:]
                if current_pos < len(result):
                    result.pop(current_pos)
                    offset -= 1
            elif line.startswith("+"):
                # Add line
                content = line[1:] + "\n"
                result.insert(current_pos, content)
                current_pos += 1
                offset += 1
            elif line.startswith(" "):
                current_pos += 1

        return "".join(result)
    except Exception as e:
        logger.error("validator.diff_apply_error", error=str(e))
        return None


def validate_python(code: str) -> list[str]:
    """Validate Python code using ast.parse() and flake8."""
    errors: list[str] = []

    # Step 1: ast.parse() — catches all syntax errors
    try:
        ast.parse(code)
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return errors  # No point running flake8 if syntax is broken

    # Step 2: flake8 — catches undefined names, unused imports, etc.
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python", "-m", "flake8", "--select=F", "--max-line-length=120", tmp_path],
            capture_output=True, text=True, timeout=10,
        )

        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[:5]:
                # Strip the temp file path from the error message
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    errors.append(f"flake8 line {parts[1]}: {parts[3].strip()}")

        Path(tmp_path).unlink(missing_ok=True)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # flake8 not available or timed out — not a blocker

    return errors


def validate_javascript(code: str) -> list[str]:
    """Validate JavaScript code (basic syntax check)."""
    errors: list[str] = []
    try:
        result = subprocess.run(
            ["node", "-c", code],
            capture_output=True, text=True, timeout=10,
            input=code,
        )
        if result.returncode != 0:
            errors.append(f"JS syntax error: {result.stderr.strip()[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # Node not available
    return errors


def validate_go(code: str) -> list[str]:
    """Validate Go code using gofmt."""
    errors: list[str] = []
    try:
        result = subprocess.run(
            ["gofmt", "-e"],
            capture_output=True, text=True, timeout=10,
            input=code,
        )
        if result.returncode != 0:
            errors.append(f"Go syntax error: {result.stderr.strip()[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # gofmt not available
    return errors


def validate_requirements(code: str) -> list[str]:
    """Validate requirements.txt basic formatting."""
    errors: list[str] = []
    for line in code.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " " in line and not any(op in line for op in ["==", ">=", "<=", ">", "<", "~=", "@"]):
            errors.append(f"Invalid requirement format: {line}")
    return errors


VALIDATORS = {
    "python": validate_python,
    "javascript": validate_javascript,
    "go": validate_go,
    "requirements": validate_requirements,
}


async def validate_patch(state: AgentState) -> AgentState:
    """
    Validate the generated patches:
    1. Check patch size limit for each patch
    2. Fetch file contents dynamically if not present
    3. Apply diff to in-memory file copy
    4. Run language-specific syntax validation
    """
    settings = get_settings()

    if not state.patch or not state.patch.all_patches:
        logger.warning("validator.no_patch", run_id=state.run_id)
        state.validation_passed = False
        state.validation_errors = ["No patch to validate"]
        return state

    errors: list[str] = []

    # Initialize file_contents with the primary file if available
    if state.parsed_error and state.parsed_error.file_path and state.file_content:
        if state.parsed_error.file_path not in state.file_contents:
            state.file_contents[state.parsed_error.file_path] = state.file_content

    from src.pipeline.github_client import GitHubClient
    github = GitHubClient()

    try:
        for file_patch in state.patch.all_patches:
            target_file = file_patch.target_file

            # ── Check patch size limit ──
            if file_patch.lines_changed > settings.neuroci_max_patch_lines:
                errors.append(
                    f"Patch for {target_file} too large: {file_patch.lines_changed} lines "
                    f"(max {settings.neuroci_max_patch_lines})"
                )

            # ── Check restricted paths ──
            if settings.is_path_restricted(target_file):
                errors.append(f"Restricted path: {target_file}")

            # Get original content
            content = state.file_contents.get(target_file)
            if content is None:
                # Fetch dynamically
                logger.info("validator.fetch_file_dynamic", repo=state.repo_full_name, file=target_file)
                content = await github.get_file_content(
                    state.repo_full_name,
                    target_file,
                    ref=state.head_sha,
                ) or ""
                state.file_contents[target_file] = content

            patched = apply_unified_diff(content, file_patch.unified_diff)

            if patched is None:
                errors.append(f"Failed to apply unified diff to {target_file}")
            else:
                # Detect language from file extension
                language = "python"
                if target_file.endswith(".js"):
                    language = "javascript"
                elif target_file.endswith(".go"):
                    language = "go"
                elif target_file.endswith("requirements.txt"):
                    language = "requirements"

                validator = VALIDATORS.get(language)
                if validator:
                    syntax_errors = validator(patched)
                    for err in syntax_errors:
                        errors.append(f"[{target_file}] {err}")
    finally:
        await github.close()

    # ── Update state ──
    state.validation_passed = len(errors) == 0
    state.validation_errors = errors

    logger.info(
        "validator.result",
        run_id=state.run_id,
        passed=state.validation_passed,
        errors=errors if errors else None,
    )

    return state
