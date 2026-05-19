"""
Tests for the CI log parser module.

Tests cover:
- ANSI escape code stripping
- Token trimming
- Language detection
- Failed step identification
- Stack trace extraction
- Error field parsing (Python, JavaScript, Go)
- Fixture files validation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.log_parser import (
    strip_ansi,
    trim_to_tokens,
    detect_language,
    find_failed_step,
    extract_stack_trace,
    parse_error_fields,
)


# ═══════════════════════════════════════════════════════════
# strip_ansi tests
# ═══════════════════════════════════════════════════════════
class TestStripAnsi:
    def test_removes_color_codes(self):
        colored = "\x1b[31mError\x1b[0m: something failed"
        assert strip_ansi(colored) == "Error: something failed"

    def test_removes_bold_underline(self):
        text = "\x1b[1m\x1b[4mBold Underline\x1b[0m normal"
        assert strip_ansi(text) == "Bold Underline normal"

    def test_preserves_plain_text(self):
        plain = "No ANSI codes here"
        assert strip_ansi(plain) == plain

    def test_removes_cursor_movement(self):
        text = "\x1b[2K\x1b[1G  Running tests..."
        result = strip_ansi(text)
        assert "Running tests..." in result
        assert "\x1b" not in result

    def test_handles_empty_string(self):
        assert strip_ansi("") == ""

    def test_handles_multiline(self):
        text = "\x1b[32m✓\x1b[0m Test 1 passed\n\x1b[31m✗\x1b[0m Test 2 failed"
        result = strip_ansi(text)
        assert result == "✓ Test 1 passed\n✗ Test 2 failed"


# ═══════════════════════════════════════════════════════════
# trim_to_tokens tests
# ═══════════════════════════════════════════════════════════
class TestTrimToTokens:
    def test_short_text_unchanged(self):
        text = "short text"
        assert trim_to_tokens(text, 1000) == text

    def test_long_text_trimmed(self):
        # 1 token ≈ 4 chars, so 10 tokens ≈ 40 chars
        text = "a" * 100
        result = trim_to_tokens(text, 10)
        assert len(result) < 100
        # Should keep the LAST 40 chars (end of log is most relevant)
        assert result.endswith("a" * 40)

    def test_trimmed_text_has_marker(self):
        text = "a" * 100
        result = trim_to_tokens(text, 10)
        assert "trimmed" in result.lower() or "..." in result

    def test_exact_boundary(self):
        text = "a" * 40  # exactly 10 tokens
        result = trim_to_tokens(text, 10)
        assert result == text


# ═══════════════════════════════════════════════════════════
# detect_language tests
# ═══════════════════════════════════════════════════════════
class TestDetectLanguage:
    def test_python(self):
        assert detect_language("src/utils/parser.py") == "python"

    def test_javascript(self):
        assert detect_language("src/App.js") == "javascript"

    def test_typescript(self):
        assert detect_language("src/App.tsx") == "javascript"

    def test_go(self):
        assert detect_language("main.go") == "go"

    def test_unknown_defaults_python(self):
        assert detect_language("README.md") == "python"

    def test_nested_path(self):
        assert detect_language("a/b/c/deep/file.py") == "python"


# ═══════════════════════════════════════════════════════════
# find_failed_step tests
# ═══════════════════════════════════════════════════════════
class TestFindFailedStep:
    def test_identifies_step_with_errors(self):
        logs = {
            "Setup": "Installing dependencies... done",
            "Test": "Running tests...\nFAILED test_one\nError: assertion failed",
            "Build": "Building... done",
        }
        step_name, log_content = find_failed_step(logs)
        assert step_name == "Test"
        assert "FAILED" in log_content

    def test_picks_highest_error_density(self):
        logs = {
            "Lint": "src/a.py:1: error\nsrc/b.py:2: error\nsrc/c.py:3: error",
            "Test": "FAILED: one error",
        }
        step_name, _ = find_failed_step(logs)
        assert step_name == "Lint"  # more error keywords

    def test_handles_empty_logs(self):
        step_name, log_content = find_failed_step({})
        assert step_name == ""
        assert log_content == ""

    def test_single_step(self):
        logs = {"Build": "Error: compilation failed"}
        step_name, _ = find_failed_step(logs)
        assert step_name == "Build"


# ═══════════════════════════════════════════════════════════
# extract_stack_trace tests
# ═══════════════════════════════════════════════════════════
class TestExtractStackTrace:
    def test_extracts_python_traceback(self):
        log = (
            "Some output\n"
            "Traceback (most recent call last):\n"
            '  File "test.py", line 5, in test\n'
            "    x = 1 / 0\n"
            "ZeroDivisionError: division by zero\n"
            "More output"
        )
        trace = extract_stack_trace(log)
        assert "Traceback" in trace
        assert "ZeroDivisionError" in trace

    def test_extracts_last_traceback(self):
        log = (
            "Traceback (most recent call last):\n"
            "  first error\n"
            "Error1: first\n"
            "\n"
            "Traceback (most recent call last):\n"
            "  second error\n"
            "Error2: second\n"
        )
        trace = extract_stack_trace(log)
        assert "second error" in trace

    def test_no_traceback(self):
        log = "npm ERR! some js error"
        assert extract_stack_trace(log) == ""


# ═══════════════════════════════════════════════════════════
# parse_error_fields tests
# ═══════════════════════════════════════════════════════════
class TestParseErrorFields:
    def test_python_import_error(self):
        log = (
            'Traceback (most recent call last):\n'
            '  File "src/utils/parser.py", line 3, in <module>\n'
            "    from dateutil.parser import parse as parse_date\n"
            "ModuleNotFoundError: No module named 'dateutil'\n"
        )
        parsed = parse_error_fields(log, language="python")
        assert parsed.file_path == "src/utils/parser.py"
        assert parsed.line_number == 3
        assert "ModuleNotFoundError" in parsed.error_type
        assert "dateutil" in parsed.error_message

    def test_python_syntax_error(self):
        log = (
            '  File "src/models/user.py", line 23\n'
            "    def get_name(self)\n"
            "                     ^\n"
            "SyntaxError: expected ':'\n"
        )
        parsed = parse_error_fields(log, language="python")
        assert parsed.file_path == "src/models/user.py"
        assert parsed.line_number == 23
        assert parsed.error_type == "SyntaxError"

    def test_python_assertion_error(self):
        log = (
            "> assert result == 0\n"
            "E AssertionError: assert inf == 0\n"
        )
        parsed = parse_error_fields(log, language="python")
        assert parsed.error_type == "AssertionError"

    def test_javascript_error(self):
        log = (
            "src/App.js:15:5 - TypeError: Cannot read property 'map' of undefined\n"
        )
        parsed = parse_error_fields(log, language="javascript")
        assert parsed.error_type == "TypeError"

    def test_go_error(self):
        log = "./main.go:15:2: undefined: fmt.Prinltn\n"
        parsed = parse_error_fields(log, language="go")
        assert parsed.file_path == "main.go" or "main.go" in parsed.file_path
        assert parsed.line_number == 15

    def test_no_error_returns_empty_fields(self):
        log = "Everything is fine, all tests passed"
        parsed = parse_error_fields(log, language="python")
        assert parsed.error_type == ""
        assert parsed.file_path == ""

    def test_language_detection_from_file(self):
        log = (
            'File "src/app.py", line 10\n'
            "ImportError: No module named 'flask'\n"
        )
        parsed = parse_error_fields(log, language="python")
        assert parsed.language == "python"

    def test_stack_trace_extracted(self):
        log = (
            "Traceback (most recent call last):\n"
            '  File "test.py", line 1\n'
            "    import foo\n"
            "ModuleNotFoundError: No module named 'foo'\n"
        )
        parsed = parse_error_fields(log, language="python")
        assert "Traceback" in parsed.stack_trace


# ═══════════════════════════════════════════════════════════
# Fixture file validation tests
# ═══════════════════════════════════════════════════════════
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestFixtureFiles:
    """Validate that all fixture files exist and are parseable."""

    def test_sample_logs_exist(self):
        logs_dir = FIXTURES_DIR / "sample_logs"
        if not logs_dir.exists():
            pytest.skip("Fixtures directory not found")
        log_files = list(logs_dir.glob("*.txt"))
        assert len(log_files) >= 20, f"Expected ≥20 log files, found {len(log_files)}"

    def test_expected_patches_exist(self):
        patches_dir = FIXTURES_DIR / "expected_patches"
        if not patches_dir.exists():
            pytest.skip("Fixtures directory not found")
        patch_files = list(patches_dir.glob("*.diff"))
        assert len(patch_files) >= 20, f"Expected ≥20 patch files, found {len(patch_files)}"

    def test_logs_and_patches_are_paired(self):
        logs_dir = FIXTURES_DIR / "sample_logs"
        patches_dir = FIXTURES_DIR / "expected_patches"
        if not logs_dir.exists() or not patches_dir.exists():
            pytest.skip("Fixtures directories not found")

        log_stems = {f.stem for f in logs_dir.glob("*.txt")}
        patch_stems = {f.stem for f in patches_dir.glob("*.diff")}

        unpaired_logs = log_stems - patch_stems
        assert not unpaired_logs, f"Log files without matching patches: {unpaired_logs}"

    def test_metadata_valid(self):
        meta_file = FIXTURES_DIR / "metadata.json"
        if not meta_file.exists():
            pytest.skip("metadata.json not found")

        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        assert len(metadata) >= 20
        for stem, meta in metadata.items():
            assert "category" in meta, f"Missing category for {stem}"
            assert "outcome" in meta, f"Missing outcome for {stem}"

    def test_all_fixture_logs_are_parseable(self):
        """Ensure parse_error_fields doesn't crash on any fixture."""
        logs_dir = FIXTURES_DIR / "sample_logs"
        if not logs_dir.exists():
            pytest.skip("Fixtures directory not found")

        for log_file in sorted(logs_dir.glob("*.txt")):
            content = log_file.read_text(encoding="utf-8")
            # Should not raise
            parsed = parse_error_fields(content, language="python")
            assert parsed.raw_log  # At minimum, raw_log should be populated
