"""
NeuroCI — Seed Data.

Pre-loads common failure→fix patterns into ChromaDB so the system
starts with baseline intelligence from day one. Without this,
ChromaDB would be empty and the RAG few-shot retrieval would have
zero examples until the first real fix is merged.

Usage:
    python -m src.memory.seed_data          # seed from built-in patterns
    python -m src.memory.seed_data --dir tests/fixtures   # seed from fixture files

These patterns are drawn from real-world CI failure archetypes
observed across Python, JavaScript, and Go codebases.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import structlog

from src.memory.vector_store import VectorStore

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════
# Built-in seed patterns — the 15 most common CI failures
# ═══════════════════════════════════════════════════════════
SEED_PATTERNS: list[dict[str, str]] = [
    # ── ImportError ──────────────────────────────────────────
    {
        "category": "ImportError",
        "failure_log": (
            "Traceback (most recent call last):\n"
            '  File "src/utils/parser.py", line 3, in <module>\n'
            "    from dateutil.parser import parse as parse_date\n"
            "ModuleNotFoundError: No module named 'dateutil'\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/requirements.txt\n"
            "+++ b/requirements.txt\n"
            "@@ -5,6 +5,7 @@\n"
            " requests>=2.28.0\n"
            " pydantic>=2.0\n"
            "+python-dateutil>=2.8.0\n"
            " structlog>=23.0\n"
        ),
        "outcome": "merged",
    },
    {
        "category": "ImportError",
        "failure_log": (
            "Traceback (most recent call last):\n"
            '  File "src/api/routes.py", line 7, in <module>\n'
            "    from src.services.notification import send_email\n"
            "ImportError: cannot import name 'send_email' from 'src.services.notification'\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/api/routes.py\n"
            "+++ b/src/api/routes.py\n"
            "@@ -7,1 +7,1 @@\n"
            "-from src.services.notification import send_email\n"
            "+from src.services.notification import send_notification_email as send_email\n"
        ),
        "outcome": "merged",
    },
    {
        "category": "ImportError",
        "failure_log": (
            "Traceback (most recent call last):\n"
            '  File "tests/test_auth.py", line 2, in <module>\n'
            "    from unittest.mock import AsyncMock\n"
            "ImportError: cannot import name 'AsyncMock' from 'unittest.mock'\n"
            "Hint: AsyncMock requires Python 3.8+\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -12,1 +12,1 @@\n"
            '-        python-version: "3.7"\n'
            '+        python-version: "3.11"\n'
        ),
        "outcome": "merged",
    },

    # ── DependencyVersionConflict ────────────────────────────
    {
        "category": "DependencyVersionConflict",
        "failure_log": (
            "ERROR: pip's dependency resolver does not currently take into account all the packages "
            "that are installed. As a result, the following dependency conflict was found:\n"
            "boto3 1.28.0 requires botocore<1.31.1,>=1.31.0, but you have botocore 1.29.76 which is "
            "incompatible.\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/requirements.txt\n"
            "+++ b/requirements.txt\n"
            "@@ -3,2 +3,2 @@\n"
            "-boto3==1.28.0\n"
            "-botocore==1.29.76\n"
            "+boto3==1.28.0\n"
            "+botocore>=1.31.0,<1.31.1\n"
        ),
        "outcome": "merged",
    },
    {
        "category": "DependencyVersionConflict",
        "failure_log": (
            "npm ERR! ERESOLVE unable to resolve dependency tree\n"
            "npm ERR! While resolving: myapp@1.0.0\n"
            "npm ERR! Found: react@18.2.0\n"
            "npm ERR! Could not resolve dependency:\n"
            "npm ERR! peer react@\"^17.0.0\" from react-router-dom@5.3.4\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/package.json\n"
            "+++ b/package.json\n"
            "@@ -10,1 +10,1 @@\n"
            '-    "react-router-dom": "^5.3.4"\n'
            '+    "react-router-dom": "^6.20.0"\n'
        ),
        "outcome": "merged",
    },

    # ── TestAssertion ────────────────────────────────────────
    {
        "category": "TestAssertion",
        "failure_log": (
            "FAILED tests/test_calculator.py::test_divide_by_zero\n"
            "    def test_divide_by_zero():\n"
            "        result = calculator.divide(10, 0)\n"
            ">       assert result == 0\n"
            "E       AssertionError: assert inf == 0\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/calculator.py\n"
            "+++ b/src/calculator.py\n"
            "@@ -15,2 +15,4 @@\n"
            " def divide(a: float, b: float) -> float:\n"
            "-    return a / b\n"
            "+    if b == 0:\n"
            "+        return 0\n"
            "+    return a / b\n"
        ),
        "outcome": "merged",
    },
    {
        "category": "TestAssertion",
        "failure_log": (
            "FAILED tests/test_user_service.py::test_create_user_returns_id\n"
            '    assert response.json()["id"] is not None\n'
            "E   KeyError: 'id'\n"
            "E   Full response: {'user_id': 'abc-123', 'name': 'test'}\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/tests/test_user_service.py\n"
            "+++ b/tests/test_user_service.py\n"
            "@@ -22,1 +22,1 @@\n"
            '-    assert response.json()["id"] is not None\n'
            '+    assert response.json()["user_id"] is not None\n'
        ),
        "outcome": "merged",
    },

    # ── ConfigMissing ────────────────────────────────────────
    {
        "category": "ConfigMissing",
        "failure_log": (
            "Traceback (most recent call last):\n"
            '  File "src/config.py", line 18, in <module>\n'
            '    DATABASE_URL = os.environ["DATABASE_URL"]\n'
            "KeyError: 'DATABASE_URL'\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/config.py\n"
            "+++ b/src/config.py\n"
            "@@ -18,1 +18,1 @@\n"
            '-DATABASE_URL = os.environ["DATABASE_URL"]\n'
            '+DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///local.db")\n'
        ),
        "outcome": "merged",
    },

    # ── TypeMismatch ─────────────────────────────────────────
    {
        "category": "TypeMismatch",
        "failure_log": (
            "src/handlers/webhook.py:42: error: Argument 1 to \"process\" has incompatible type "
            '"str"; expected "int"  [arg-type]\n'
            "Found 1 error in 1 file (checked 24 source files)\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/handlers/webhook.py\n"
            "+++ b/src/handlers/webhook.py\n"
            "@@ -42,1 +42,1 @@\n"
            "-    result = process(run_id_str)\n"
            "+    result = process(int(run_id_str))\n"
        ),
        "outcome": "merged",
    },
    {
        "category": "TypeMismatch",
        "failure_log": (
            "TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'\n"
            '  File "src/report.py", line 55, in generate_summary\n'
            "    full_text = header + body\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/report.py\n"
            "+++ b/src/report.py\n"
            "@@ -55,1 +55,1 @@\n"
            "-    full_text = header + body\n"
            "+    full_text = (header or \"\") + body\n"
        ),
        "outcome": "merged",
    },

    # ── SyntaxError ──────────────────────────────────────────
    {
        "category": "SyntaxError",
        "failure_log": (
            '  File "src/models/user.py", line 23\n'
            "    def get_name(self)\n"
            "                     ^\n"
            "SyntaxError: expected ':'\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/models/user.py\n"
            "+++ b/src/models/user.py\n"
            "@@ -23,1 +23,1 @@\n"
            "-    def get_name(self)\n"
            "+    def get_name(self):\n"
        ),
        "outcome": "merged",
    },

    # ── LogicBug ─────────────────────────────────────────────
    {
        "category": "LogicBug",
        "failure_log": (
            "FAILED tests/test_pagination.py::test_page_count\n"
            "    assert paginate(items=100, per_page=10).total_pages == 10\n"
            "E   AssertionError: assert 11 == 10\n"
            "E   Off-by-one: range(0, total_pages + 1) creates an extra page\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/utils/pagination.py\n"
            "+++ b/src/utils/pagination.py\n"
            "@@ -8,1 +8,1 @@\n"
            "-    total_pages = (total_items // per_page) + 1\n"
            "+    total_pages = -(-total_items // per_page)  # ceiling division\n"
        ),
        "outcome": "merged",
    },

    # ── JavaScript errors ────────────────────────────────────
    {
        "category": "ImportError",
        "failure_log": (
            "Error: Cannot find module './components/Header'\n"
            "Require stack:\n"
            "  - /app/src/App.js\n"
            "Module not found: Error: Can't resolve './components/Header' in '/app/src'\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/App.js\n"
            "+++ b/src/App.js\n"
            "@@ -2,1 +2,1 @@\n"
            "-import Header from './components/Header'\n"
            "+import Header from './components/header/Header'\n"
        ),
        "outcome": "merged",
    },

    # ── Go errors ────────────────────────────────────────────
    {
        "category": "SyntaxError",
        "failure_log": (
            "./main.go:15:2: undefined: fmt.Prinltn\n"
            "##[error]Process completed with exit code 2."
        ),
        "fix_diff": (
            "--- a/main.go\n"
            "+++ b/main.go\n"
            "@@ -15,1 +15,1 @@\n"
            '-\tfmt.Prinltn("Hello")\n'
            '+\tfmt.Println("Hello")\n'
        ),
        "outcome": "merged",
    },

    # ── Rejected fix (negative example for learning) ─────────
    {
        "category": "LogicBug",
        "failure_log": (
            "FAILED tests/test_auth.py::test_token_expiry\n"
            "    assert token.is_expired() is True\n"
            "E   AssertionError: assert False is True\n"
            "E   Token created 2 hours ago but is_expired() returned False\n"
            "##[error]Process completed with exit code 1."
        ),
        "fix_diff": (
            "--- a/src/auth/token.py\n"
            "+++ b/src/auth/token.py\n"
            "@@ -30,1 +30,1 @@\n"
            "-    return datetime.utcnow() > self.expires_at\n"
            "+    return datetime.now(timezone.utc) > self.expires_at\n"
        ),
        "outcome": "rejected",
    },
]


async def seed_from_patterns(
    patterns: list[dict[str, str]] | None = None,
) -> int:
    """
    Seed ChromaDB with built-in failure→fix patterns.
    Returns the number of patterns successfully seeded.
    """
    patterns = patterns or SEED_PATTERNS
    vs = VectorStore()
    seeded = 0

    for i, pattern in enumerate(patterns, 1):
        try:
            await vs.store_fix(
                failure_log=pattern["failure_log"],
                fix_diff=pattern["fix_diff"],
                category=pattern["category"],
                outcome=pattern.get("outcome", "merged"),
                repo="neuroci/seed-data",
                run_id=i,
            )
            seeded += 1
            logger.info(
                "seed.stored",
                index=i,
                category=pattern["category"],
                outcome=pattern.get("outcome", "merged"),
            )
        except Exception as e:
            logger.error("seed.store_error", index=i, error=str(e))

    logger.info("seed.complete", total=seeded, of=len(patterns))
    return seeded


async def seed_from_fixtures(fixtures_dir: str | Path) -> int:
    """
    Seed ChromaDB from fixture files on disk.

    Expected structure:
        fixtures_dir/
            sample_logs/
                001_import_error.txt
                002_dep_conflict.txt
                ...
            expected_patches/
                001_import_error.diff
                002_dep_conflict.diff
                ...
            metadata.json   (optional — maps filename to category/outcome)

    File matching: logs and patches are paired by filename stem (e.g.
    001_import_error.txt ↔ 001_import_error.diff).
    """
    fixtures_path = Path(fixtures_dir)
    logs_dir = fixtures_path / "sample_logs"
    patches_dir = fixtures_path / "expected_patches"

    if not logs_dir.exists():
        logger.error("seed.fixtures_missing", path=str(logs_dir))
        return 0

    # Load optional metadata
    metadata: dict[str, dict[str, str]] = {}
    meta_file = fixtures_path / "metadata.json"
    if meta_file.exists():
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))

    vs = VectorStore()
    seeded = 0

    for log_file in sorted(logs_dir.glob("*.txt")):
        stem = log_file.stem
        patch_file = patches_dir / f"{stem}.diff"

        failure_log = log_file.read_text(encoding="utf-8")
        fix_diff = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""

        meta = metadata.get(stem, {})
        category = meta.get("category", _guess_category_from_name(stem))
        outcome = meta.get("outcome", "merged")

        try:
            await vs.store_fix(
                failure_log=failure_log,
                fix_diff=fix_diff,
                category=category,
                outcome=outcome,
                repo="neuroci/fixtures",
                run_id=seeded + 1,
            )
            seeded += 1
            logger.info("seed.fixture_stored", file=stem, category=category)
        except Exception as e:
            logger.error("seed.fixture_error", file=stem, error=str(e))

    logger.info("seed.fixtures_complete", total=seeded)
    return seeded


def _guess_category_from_name(stem: str) -> str:
    """Best-effort category guess from fixture filename."""
    name = stem.lower()
    mapping = {
        "import": "ImportError",
        "dep": "DependencyVersionConflict",
        "version": "DependencyVersionConflict",
        "test": "TestAssertion",
        "assert": "TestAssertion",
        "config": "ConfigMissing",
        "env": "ConfigMissing",
        "type": "TypeMismatch",
        "syntax": "SyntaxError",
        "logic": "LogicBug",
        "flaky": "FlakyTest",
        "auth": "AuthError",
        "network": "NetworkTimeout",
        "timeout": "NetworkTimeout",
    }
    for keyword, category in mapping.items():
        if keyword in name:
            return category
    return "Unknown"


# ── CLI entrypoint ─────────────────────────────────────────
async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed NeuroCI ChromaDB with fix patterns")
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Path to fixtures directory (sample_logs/ + expected_patches/)",
    )
    args = parser.parse_args()

    if args.dir:
        count = await seed_from_fixtures(args.dir)
    else:
        count = await seed_from_patterns()

    print(f"\n✅ Seeded {count} patterns into ChromaDB")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
