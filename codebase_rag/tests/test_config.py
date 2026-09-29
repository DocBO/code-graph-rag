from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from codebase_rag.config import (
    BASE_IGNORE_PATTERNS,
    DEFAULT_APP_URL,
    AppConfig,
    ModelConfig,
    _parse_ignore_dirs,
    openrouter_attribution_headers,
)
from codebase_rag.config import (
    settings as config_settings,
)


class TestModelConfig:
    def test_default_values(self) -> None:
        config = ModelConfig(provider="openai", model_id="gpt-4o")
        assert config.provider == "openai"
        assert config.model_id == "gpt-4o"
        assert config.api_key is None
        assert config.endpoint is None
        assert config.project_id is None
        assert config.region is None
        assert config.provider_type is None
        assert config.thinking_budget is None
        assert config.reasoning_effort == "high"
        assert config.service_account_file is None

    def test_all_fields_set(self) -> None:
        config = ModelConfig(
            provider="google",
            model_id="gemini-2.5-pro",
            api_key="key123",
            endpoint="https://api.example.com",
            project_id="my-project",
            region="europe-west1",
            provider_type="vertex",
            thinking_budget=8000,
            reasoning_effort="medium",
            service_account_file="/path/sa.json",
        )
        assert config.provider == "google"
        assert config.model_id == "gemini-2.5-pro"
        assert config.api_key == "key123"
        assert config.thinking_budget == 8000
        assert config.reasoning_effort == "medium"
        assert config.service_account_file == "/path/sa.json"


class TestParseIgnoreDirs:
    def test_parses_comma_separated(self) -> None:
        result = _parse_ignore_dirs("dir1, dir2 , dir3/")
        assert result == {"dir1", "dir2", "dir3"}

    def test_handles_empty_string(self) -> None:
        assert _parse_ignore_dirs("") == set()

    def test_handles_none(self) -> None:
        assert _parse_ignore_dirs(None) == set()

    def test_strips_trailing_slashes(self) -> None:
        result = _parse_ignore_dirs("build/, dist/")
        assert result == {"build", "dist"}


class TestIgnorePatterns:
    def test_base_patterns_include_standard_dirs(self) -> None:
        for d in [
            ".git",
            "venv",
            ".venv",
            "__pycache__",
            "node_modules",
            "build",
            "dist",
        ]:
            assert d in BASE_IGNORE_PATTERNS

    def test_ignore_patterns_are_combined(self) -> None:
        with (
            patch.object(AppConfig, "__init__", lambda self: None),
            patch.dict(os.environ, {"INGEST_IGNORE_DIRS": "custom_dir, other_dir"}),
        ):
            combined = BASE_IGNORE_PATTERNS | {"custom_dir", "other_dir"}
            assert ".git" in combined
            assert "custom_dir" in combined


class TestAppConfigParseModelString:
    def test_bare_model_defaults_to_ollama(self) -> None:
        config = AppConfig()
        provider, model = config.parse_model_string("llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_provider_model_split_on_first_colon(self) -> None:
        config = AppConfig()
        provider, model = config.parse_model_string("openai:gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_model_with_colons_preserved(self) -> None:
        config = AppConfig()
        provider, model = config.parse_model_string("openai:gpt-oss:20b")
        assert provider == "openai"
        assert model == "gpt-oss:20b"

    def test_empty_provider_raises(self) -> None:
        config = AppConfig()
        with pytest.raises(ValueError, match="Provider name cannot be empty"):
            config.parse_model_string(":model")

    def test_provider_cased_lowered(self) -> None:
        config = AppConfig()
        provider, model = config.parse_model_string("OpenAI:gpt-4o")
        assert provider == "openai"


class TestBatchSizeResolution:
    def test_uses_explicit_value(self) -> None:
        config = AppConfig()
        assert config.resolve_batch_size(500) == 500

    def test_falls_back_to_config(self) -> None:
        config = AppConfig()
        result = config.resolve_batch_size(None)
        assert result == config.MEMGRAPH_BATCH_SIZE
        assert result > 0

    def test_zero_raises(self) -> None:
        config = AppConfig()
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            config.resolve_batch_size(0)

    def test_negative_raises(self) -> None:
        config = AppConfig()
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            config.resolve_batch_size(-1)


class TestDefaultFallback:
    def test_no_env_yields_ollama_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig(_env_file=None)
            orch = config.active_orchestrator_config
            assert orch.provider == "ollama"
            assert orch.model_id == "llama3.2"

    def test_default_cypher_is_ollama(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig(_env_file=None)
            cyp = config.active_cypher_config
            assert cyp.provider == "ollama"

    def test_reasoning_effort_is_configured_per_model_role(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_PROVIDER": "openrouter",
                "ORCHESTRATOR_MODEL": "openai/gpt-5.6-luna",
                "CYPHER_PROVIDER": "openrouter",
                "CYPHER_MODEL": "openai/gpt-5.6-luna",
                "REASONING_EFFORT_ORCHESTRATOR": "low",
                "REASONING_EFFORT_CYPHER": "medium",
            },
            clear=True,
        ):
            config = AppConfig(_env_file=None)

            assert config.active_orchestrator_config.reasoning_effort == "low"
            assert config.active_cypher_config.reasoning_effort == "medium"


class TestOpenRouterAttributionHeaders:
    """Attribution is opt-in via APP_ID and never sent to unrelated endpoints."""

    def test_nothing_sent_without_app_id(self) -> None:
        with (
            patch.object(config_settings, "APP_ID", None),
            patch.object(config_settings, "APP_URL", None),
        ):
            assert openrouter_attribution_headers("https://openrouter.ai/api/v1") == {}

    def test_app_id_uses_project_referer_for_openrouter(self) -> None:
        with (
            patch.object(config_settings, "APP_ID", "code-graph-rag"),
            patch.object(config_settings, "APP_URL", None),
        ):
            headers = openrouter_attribution_headers("https://openrouter.ai/api/v1")

        assert headers == {
            "HTTP-Referer": DEFAULT_APP_URL,
            "X-OpenRouter-Title": "code-graph-rag",
        }

    def test_app_url_overrides_referer(self) -> None:
        with (
            patch.object(config_settings, "APP_ID", "my-fork"),
            patch.object(config_settings, "APP_URL", "https://example.com/app"),
        ):
            headers = openrouter_attribution_headers("https://openrouter.ai/api/v1")

        assert headers["HTTP-Referer"] == "https://example.com/app"
        assert headers["X-OpenRouter-Title"] == "my-fork"

    def test_foreign_endpoint_without_app_url_is_left_alone(self) -> None:
        with (
            patch.object(config_settings, "APP_ID", "code-graph-rag"),
            patch.object(config_settings, "APP_URL", None),
        ):
            assert openrouter_attribution_headers("https://api.openai.com/v1") == {}

    def test_app_url_reaches_an_explicitly_attributed_endpoint(self) -> None:
        with (
            patch.object(config_settings, "APP_ID", "my-fork"),
            patch.object(config_settings, "APP_URL", "https://example.com/app"),
        ):
            headers = openrouter_attribution_headers("https://proxy.example.com/v1")

        assert headers["HTTP-Referer"] == "https://example.com/app"
