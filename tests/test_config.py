"""
NeuroCI — Configuration Tests.

Tests for settings loading, validators, and helpers.
"""
from unittest.mock import patch


class TestSettings:
    """Test configuration settings."""

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_settings_loads(self):
        from src.config import Settings
        s = Settings()
        assert s.github_token == "t"

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_repo_allowlist_parsing(self):
        from src.config import Settings
        s = Settings(github_allowed_repos="o/r1,o/r2")
        assert s.allowed_repos_list == ["o/r1", "o/r2"]

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_restricted_paths_parsing(self):
        from src.config import Settings
        s = Settings(neuroci_restricted_paths="infra/,.env")
        assert "infra/" in s.neuroci_restricted_paths

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_is_repo_allowed(self):
        from src.config import Settings
        s = Settings(github_allowed_repos="o/r1")
        assert s.is_repo_allowed("o/r1") is True
        assert s.is_repo_allowed("o/r2") is False

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_empty_allowlist_allows_all(self):
        from src.config import Settings
        s = Settings(github_allowed_repos="")
        assert s.is_repo_allowed("any/repo") is True

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_is_path_restricted(self):
        from src.config import Settings
        s = Settings(neuroci_restricted_paths="infra/,secrets.py")
        assert s.is_path_restricted("infra/main.tf") is True
        assert s.is_path_restricted("src/secrets.py") is True
        assert s.is_path_restricted("src/main.py") is False

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_defaults(self):
        from src.config import Settings
        s = Settings()
        assert s.neuroci_confidence_threshold == 0.85
        assert s.neuroci_max_patch_lines == 20
        assert s.log_level == "INFO"

    @patch.dict("os.environ", {
        "GITHUB_TOKEN": "t", "GITHUB_WEBHOOK_SECRET": "s",
    }, clear=False)
    def test_project_root(self):
        from src.config import Settings
        s = Settings()
        assert s.project_root.exists()
