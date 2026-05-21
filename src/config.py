"""
NeuroCI — Configuration & Settings.

Centralised settings management using pydantic-settings.
All secrets and configuration are loaded from environment variables / .env file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        str_strip_whitespace=True,
    )

    # ── GitHub ──────────────────────────────────────────────
    github_token: str = Field(..., description="GitHub PAT or App token")
    github_webhook_secret: str = Field(..., description="HMAC shared secret for webhook verification")
    github_allowed_repos: str = Field(
        default="",
        description="Comma-separated list of allowed repos (owner/repo)",
    )

    @property
    def allowed_repos_list(self) -> list[str]:
        """Parse allowed repos from comma-separated string."""
        if not self.github_allowed_repos:
            return []
        return [r.strip() for r in self.github_allowed_repos.split(",") if r.strip()]

    # ── LLM Provider ───────────────────────────────────────
    llm_provider: Literal["gemini", "groq", "ollama", "openai"] = Field(
        "gemini", description="LLM provider: gemini (free), groq (free), ollama (local), openai (paid)"
    )

    # ── Google Gemini (FREE — recommended) ─────────────────
    gemini_api_key: str = Field("", description="Google Gemini API key (free at aistudio.google.com)")
    gemini_model: str = Field("gemini-2.0-flash", description="Gemini model")
    gemini_embedding_model: str = Field("models/text-embedding-004", description="Gemini embedding model")

    # ── Groq (FREE tier) ──────────────────────────────────
    groq_api_key: str = Field("", description="Groq API key (free at console.groq.com)")
    groq_model: str = Field("llama-3.3-70b-versatile", description="Groq model")

    # ── Ollama (FREE — local, no API key) ──────────────────
    ollama_url: str = Field("http://localhost:11434", description="Ollama server URL")
    ollama_model: str = Field("llama3.1", description="Ollama model name")
    ollama_embedding_model: str = Field("nomic-embed-text", description="Ollama embedding model")

    # ── OpenAI (paid) ──────────────────────────────────────
    openai_api_key: str = Field("", description="OpenAI API key")
    openai_model: str = Field("gpt-4o", description="OpenAI model")
    openai_embedding_model: str = Field("text-embedding-3-small", description="Embedding model")

    # ── Redis ──────────────────────────────────────────────
    redis_url: str = Field("redis://localhost:6379/0", description="Redis connection URL")

    # ── ChromaDB ───────────────────────────────────────────
    chroma_host: str = Field("localhost", description="ChromaDB host")
    chroma_port: int = Field(8000, description="ChromaDB port")
    chroma_collection: str = Field("neuroci_fixes", description="ChromaDB collection name")

    # ── Slack ──────────────────────────────────────────────
    slack_bot_token: str = Field("", description="Slack bot OAuth token")
    slack_signing_secret: str = Field("", description="Slack signing secret")
    slack_channel: str = Field("#neuroci-alerts", description="Default Slack channel")

    # ── OPA ────────────────────────────────────────────────
    opa_url: str = Field("http://localhost:8181", description="OPA server URL")
    opa_policy_path: str = Field("v1/data/neuroci/allow", description="OPA policy path")

    # ── NeuroCI Core ───────────────────────────────────────
    dry_run: bool = Field(False, description="Enable dry run mode (Slack only, no PR)")
    neuroci_confidence_threshold: float = Field(
        0.85,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for auto-PR",
    )
    neuroci_max_patch_lines: int = Field(20, description="Maximum lines changed per patch")
    neuroci_max_log_tokens: int = Field(8000, description="Max tokens from CI log to send to LLM")
    neuroci_restricted_paths: str = Field(
        default="infra/,terraform/,secrets.py,auth.py,.env",
        description="Comma-separated file paths NeuroCI is never allowed to modify",
    )
    ci_failure_store_path: str = Field(
        "data/ci_failures.json",
        description="Local JSON file used to store recent CI failure analyses",
    )
    ci_remediation_store_path: str = Field(
        "data/ci_remediations.json",
        description="Local JSON file used to store remediation attempts",
    )
    github_remediation_enabled: bool = Field(
        False,
        description="Enable automatic remediation branch and pull request creation",
    )
    github_remediation_dry_run: bool = Field(
        True,
        description="Generate remediation plans without writing branches or pull requests",
    )

    @property
    def restricted_paths_list(self) -> list[str]:
        """Parse restricted paths from comma-separated string."""
        if not self.neuroci_restricted_paths:
            return []
        return [p.strip() for p in self.neuroci_restricted_paths.split(",") if p.strip()]

    # ── Observability ──────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field("INFO")
    prometheus_port: int = Field(9090, description="Prometheus metrics port")

    # ── LangSmith (optional) ───────────────────────────────
    langchain_tracing_v2: bool = Field(False, description="Enable LangSmith tracing")
    langchain_api_key: str = Field("", description="LangSmith API key")
    langchain_project: str = Field("neuroci", description="LangSmith project name")

    # ── Helpers ────────────────────────────────────────────
    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def is_repo_allowed(self, repo_full_name: str) -> bool:
        """Check if a repository is in the allowlist."""
        repos = self.allowed_repos_list
        if not repos:
            return True  # No allowlist = allow all
        return repo_full_name in repos

    def is_path_restricted(self, file_path: str) -> bool:
        """Check if a file path is in the restricted list."""
        return any(file_path.startswith(rp) or file_path.endswith(rp) for rp in self.restricted_paths_list)

    @field_validator("github_webhook_secret", mode="before")
    @classmethod
    def trim_webhook_secret(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for application settings."""
    return Settings()  # type: ignore[call-arg]
