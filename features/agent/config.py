"""
features/agent/config.py
决策引擎配置
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EngineType(str, Enum):
    CODEX_CLI = "codex_cli"
    AGENT_SDK = "agent_sdk"
    DIRECT_LLM = "direct_llm"
    RULE_ONLY = "rule_only"


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"


# provider → (default model, api key env var)
_PROVIDER_DEFAULTS: dict[ModelProvider, tuple[str, str]] = {
    ModelProvider.OPENAI: ("gpt-4o", "OPENAI_API_KEY"),
    ModelProvider.ANTHROPIC: ("claude-sonnet-4-20250514", "ANTHROPIC_API_KEY"),
    ModelProvider.GOOGLE: ("gemini-2.0-flash", "GOOGLE_API_KEY"),
    ModelProvider.OLLAMA: ("llama3", ""),
}


@dataclass
class EngineConfig:
    engine_type: EngineType = EngineType.RULE_ONLY
    model_provider: ModelProvider = ModelProvider.OPENAI
    model_name: Optional[str] = None
    api_key_env: Optional[str] = None

    # MCP Server
    mcp_server_command: str = field(default_factory=lambda: sys.executable)
    mcp_server_args: list[str] = field(default_factory=lambda: ["-m", "sts2_mcp"])
    mcp_server_cwd: Optional[str] = None
    mcp_tool_profile: str = "guided"

    # LLM params
    temperature: float = 0.3
    max_tokens: int = 1024

    # Safety
    max_retries: int = 2
    step_timeout: float = 30.0

    @property
    def resolved_model(self) -> str:
        if self.model_name:
            return self.model_name
        return _PROVIDER_DEFAULTS.get(self.model_provider, ("gpt-4o", ""))[0]

    @property
    def api_key(self) -> Optional[str]:
        env_var = self.api_key_env or _PROVIDER_DEFAULTS.get(
            self.model_provider, ("", "")
        )[1]
        return os.environ.get(env_var) if env_var else None

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def effective_engine_type(self) -> EngineType:
        """If LLM engine is requested but no API key, degrade to rule_only.
        Codex CLI uses its own auth — no API key needed here."""
        if self.engine_type in (EngineType.AGENT_SDK, EngineType.DIRECT_LLM):
            if not self.has_api_key:
                return EngineType.RULE_ONLY
        return self.engine_type
