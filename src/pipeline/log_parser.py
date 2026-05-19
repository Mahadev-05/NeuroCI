"""
NeuroCI — CI Log Parser.

Extracts, cleans, and structures CI failure logs:
- Downloads and extracts only the failed step's log
- Strips ANSI escape codes
- Trims to ≤8,000 tokens
- Parses structured error fields: file path, line number, error type, stack trace
"""

from __future__ import annotations

import re

import structlog

from src.config import get_settings
from src.models import AgentState, ParsedError
from src.pipeline.github_client import GitHubClient

logger = structlog.get_logger()

# ── ANSI escape code pattern ──
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")

# ── Common error patterns (Python-focused, extensible) ──
ERROR_PATTERNS = {
    "python": [
        # Traceback with file/line
        re.compile(
            r'File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+)',
            re.MULTILINE,
        ),
        # ImportError / ModuleNotFoundError
        re.compile(
            r"(?P<error_type>(?:ModuleNotFoundError|ImportError)):\s+(?P<message>.+)",
            re.MULTILINE,
        ),
        # Generic Python exception
        re.compile(
            r"(?P<error_type>\w+Error):\s+(?P<message>.+)",
            re.MULTILINE,
        ),
        # pytest assertion
        re.compile(
            r"(?P<error_type>AssertionError):\s*(?P<message>.*)",
            re.MULTILINE,
        ),
        # SyntaxError
        re.compile(
            r"(?P<error_type>SyntaxError):\s+(?P<message>.+)",
            re.MULTILINE,
        ),
    ],
    "javascript": [
        re.compile(
            r"(?P<file>[^\s]+):(?P<line>\d+):\d+\s*[-–]\s*(?P<error_type>\w+):\s+(?P<message>.+)",
            re.MULTILINE,
        ),
        re.compile(
            r"(?P<error_type>TypeError|ReferenceError|SyntaxError):\s+(?P<message>.+)",
            re.MULTILINE,
        ),
    ],
    "go": [
        re.compile(
            r"(?P<file>[^\s]+\.go):(?P<line>\d+):\d+:\s+(?P<message>.+)",
            re.MULTILINE,
        ),
    ],
}

# ── Language detection from file extension ──
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".go": "go",
    ".java": "java",
}


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from log output."""
    return ANSI_PATTERN.sub("", text)


def trim_to_tokens(text: str, max_tokens: int) -> str:
    """
    Trim text to approximately max_tokens.
    Uses a simple heuristic: 1 token ≈ 4 characters.
    Keeps the last N characters (end of log is most relevant for errors).
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return "... [log trimmed — showing last {max_tokens} tokens] ...\n" + text[-max_chars:]


def detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if file_path.endswith(ext):
            return lang
    return "python"  # default


def find_failed_step(logs: dict[str, str]) -> tuple[str, str]:
    """
    Identify the failed step from the log dict.
    Heuristic: the step with error-indicative keywords near the end.
    Returns (step_name, log_content).
    """
    error_keywords = [
        "error", "Error", "ERROR",
        "FAILED", "failed", "Traceback",
        "Exception", "exit code", "AssertionError",
    ]

    # Score each step by error keyword density in the last 2000 chars
    best_step = ""
    best_score = -1
    best_log = ""

    for step_name, log_content in logs.items():
        tail = log_content[-2000:]
        score = sum(tail.count(kw) for kw in error_keywords)
        if score > best_score:
            best_score = score
            best_step = step_name
            best_log = log_content

    return best_step, best_log


def extract_stack_trace(log: str) -> str:
    """Extract Python traceback from log content."""
    # Find the last traceback in the log
    tb_pattern = re.compile(
        r"(Traceback \(most recent call last\):.*?(?:\n[ \t].*)*\n\S.*?)(?=\n\S|\Z)",
        re.DOTALL,
    )
    matches = list(tb_pattern.finditer(log))
    if matches:
        return matches[-1].group(1).strip()
    return ""


def parse_error_fields(log: str, language: str = "python") -> ParsedError:
    """
    Parse structured error fields from a CI log.
    Extracts: file path, line number, error type, error message, stack trace.
    """
    parsed = ParsedError(raw_log=log, language=language)

    # Get patterns for this language
    patterns = ERROR_PATTERNS.get(language, ERROR_PATTERNS["python"])

    for pattern in patterns:
        match = pattern.search(log)
        if match:
            groups = match.groupdict()
            if "file" in groups and not parsed.file_path:
                parsed.file_path = groups["file"]
            if "line" in groups and parsed.line_number is None:
                try:
                    parsed.line_number = int(groups["line"])
                except ValueError:
                    pass
            if "error_type" in groups and not parsed.error_type:
                parsed.error_type = groups["error_type"]
            if "message" in groups and not parsed.error_message:
                parsed.error_message = groups["message"]

    # Extract stack trace
    parsed.stack_trace = extract_stack_trace(log)

    # Detect language from file path if we found one
    if parsed.file_path:
        parsed.language = detect_language(parsed.file_path)

    return parsed


async def extract_and_parse_logs(state: AgentState) -> AgentState:
    """
    Full log extraction pipeline:
    1. Download logs from GitHub
    2. Find the failed step
    3. Strip ANSI codes
    4. Trim to token limit
    5. Parse structured error fields
    6. Update agent state
    """
    settings = get_settings()
    client = GitHubClient()

    try:
        # Step 1: Download logs
        logs = await client.download_run_logs(state.repo_full_name, state.run_id)

        if not logs:
            logger.warning("log_parser.no_logs", run_id=state.run_id)
            state.parsed_error = ParsedError(
                error_message="No logs available for this run",
                raw_log="",
            )
            return state

        # Step 2: Find the failed step
        step_name, raw_log = find_failed_step(logs)

        # Step 3: Strip ANSI
        clean_log = strip_ansi(raw_log)

        # Step 4: Trim
        trimmed_log = trim_to_tokens(clean_log, settings.neuroci_max_log_tokens)

        # Step 5: Parse
        parsed = parse_error_fields(trimmed_log)
        parsed.failed_step = step_name
        parsed.raw_log = trimmed_log

        # Step 6: Update state
        state.parsed_error = parsed

        logger.info(
            "log_parser.complete",
            run_id=state.run_id,
            failed_step=step_name,
            error_type=parsed.error_type,
            file_path=parsed.file_path,
            line_number=parsed.line_number,
            language=parsed.language,
        )

    finally:
        await client.close()

    return state
