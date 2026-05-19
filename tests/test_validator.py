"""
NeuroCI — Patch Validator Tests.

Tests for unified diff application and multi-language syntax validation.
"""

import pytest

from src.agent.validator import (
    apply_unified_diff,
    validate_python,
)


class TestDiffApplication:
    """Test unified diff application."""

    def test_simple_line_addition(self):
        """Adding a new import line."""
        original = "import os\nimport sys\n\ndef main():\n    pass\n"
        diff = """@@ -1,2 +1,3 @@
 import os
 import sys
+import json
"""
        result = apply_unified_diff(original, diff)
        assert result is not None
        assert "import json" in result

    def test_simple_line_removal(self):
        """Removing a line."""
        original = "import os\nimport sys\nimport json\n"
        diff = """@@ -1,3 +1,2 @@
 import os
-import sys
 import json
"""
        result = apply_unified_diff(original, diff)
        assert result is not None
        assert "import sys" not in result

    def test_line_replacement(self):
        """Replacing one line with another."""
        original = "x = 1\ny = 2\nz = 3\n"
        diff = """@@ -1,3 +1,3 @@
 x = 1
-y = 2
+y = 42
 z = 3
"""
        result = apply_unified_diff(original, diff)
        assert result is not None
        assert "y = 42" in result
        assert "y = 2" not in result


class TestPythonValidation:
    """Test Python syntax validation."""

    def test_valid_python(self):
        """Valid Python should pass validation."""
        code = """
def hello():
    print("Hello, world!")

if __name__ == "__main__":
    hello()
"""
        errors = validate_python(code)
        assert len(errors) == 0

    def test_syntax_error(self):
        """Invalid syntax should be caught."""
        code = """
def hello(
    print("unclosed parenthesis")
"""
        errors = validate_python(code)
        assert len(errors) > 0
        assert any("SyntaxError" in e for e in errors)

    def test_empty_code(self):
        """Empty code should be valid."""
        errors = validate_python("")
        assert len(errors) == 0

    def test_valid_class(self):
        """Valid class definition should pass."""
        code = """
class MyClass:
    def __init__(self, x: int):
        self.x = x

    def get_x(self) -> int:
        return self.x
"""
        errors = validate_python(code)
        assert len(errors) == 0


class TestLogParser:
    """Test log parsing utilities."""

    def test_strip_ansi(self):
        """ANSI codes should be stripped."""
        from src.pipeline.log_parser import strip_ansi

        text = "\x1b[31mError:\x1b[0m Something failed"
        result = strip_ansi(text)
        assert result == "Error: Something failed"

    def test_detect_language(self):
        """Language detection from file extension."""
        from src.pipeline.log_parser import detect_language

        assert detect_language("main.py") == "python"
        assert detect_language("app.js") == "javascript"
        assert detect_language("main.go") == "go"
        assert detect_language("unknown.xyz") == "python"  # default

    def test_parse_python_error(self):
        """Parse a Python ImportError from log."""
        from src.pipeline.log_parser import parse_error_fields

        log = '''
Traceback (most recent call last):
  File "src/main.py", line 42, in <module>
    from utils import helper
ModuleNotFoundError: No module named 'utils'
'''
        parsed = parse_error_fields(log, "python")
        assert parsed.file_path == "src/main.py"
        assert parsed.line_number == 42
        assert "ModuleNotFoundError" in parsed.error_type

    def test_parse_error_empty_log(self):
        """Empty log should return empty fields."""
        from src.pipeline.log_parser import parse_error_fields

        parsed = parse_error_fields("", "python")
        assert parsed.file_path == ""
        assert parsed.error_type == ""
