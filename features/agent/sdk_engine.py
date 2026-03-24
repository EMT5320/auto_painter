"""
features/agent/sdk_engine.py
OpenAI Agents SDK engine — connects to the sts2-ai-agent MCP Server
and lets the LLM autonomously read game state + execute actions.

Requires: pip install openai-agents
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from features.game_bridge.schemas import GameSnapshot, SceneType

from .config import EngineConfig, ModelProvider
from .engine import ActionDecision, EngineBase
from .prompts import build_system_prompt, build_task_prompt

logger = logging.getLogger(__name__)

# Project root (auto_painter/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# MCP server source directory
_MCP_SERVER_SRC = _PROJECT_ROOT / "mcp" / "sts2-ai-agent-v0.5.2-windows" / "mcp_server" / "src"

# MCP server data directory (working directory so relative paths to data/ work)
_MCP_SERVER_CWD = _PROJECT_ROOT / "mcp" / "sts2-ai-agent-v0.5.2-windows" / "mcp_server"


def _resolve_mcp_cwd(config: EngineConfig) -> str:
    if config.mcp_server_cwd:
        return config.mcp_server_cwd
    return str(_MCP_SERVER_CWD)


def _build_env(config: EngineConfig) -> dict[str, str]:
    """Build env vars for the MCP subprocess."""
    env = dict(os.environ)
    env["STS2_MCP_TOOL_PROFILE"] = config.mcp_tool_profile
    # Add MCP server src to PYTHONPATH so `python -m sts2_mcp` works
    mcp_src = str(_MCP_SERVER_SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{mcp_src};{existing}" if existing else mcp_src
    return env


class AgentSDKEngine(EngineBase):
    """
    Decision engine backed by openai-agents SDK + MCP.

    The LLM agent autonomously:
      1. Reads game state via MCP tools (get_game_state, get_available_actions)
      2. Looks up unknown cards/monsters via get_game_data_item
      3. Executes actions via the `act` tool
      4. Returns a summary of what it did

    RuleGuard acts as an approval callback on the `act` tool to reject
    illegal actions before they reach the game.
    """

    def __init__(self, config: EngineConfig, rule_guard: Any = None) -> None:
        self._config = config
        self._guard = rule_guard
        self._mcp_server: Any = None  # MCPServerStdio instance
        self._agent: Any = None

    async def setup(self) -> None:
        try:
            from agents import Agent
            from agents.mcp import MCPServerStdio
        except ImportError as e:
            raise ImportError(
                "openai-agents SDK is required. Install with: pip install openai-agents"
            ) from e

        # Set API key in env if not already set
        api_key = self._config.api_key
        if api_key and self._config.model_provider == ModelProvider.OPENAI:
            os.environ.setdefault("OPENAI_API_KEY", api_key)

        cwd = _resolve_mcp_cwd(self._config)
        logger.info("Starting MCP server in %s", cwd)

        self._mcp_server = MCPServerStdio(
            params={
                "command": self._config.mcp_server_command,
                "args": self._config.mcp_server_args,
                "cwd": cwd,
                "env": _build_env(self._config),
            },
            name="STS2 AI Agent",
            cache_tools_list=True,
        )

        # Enter the MCP server context
        await self._mcp_server.__aenter__()

        system_prompt = build_system_prompt()
        model = self._resolve_model()

        agent_kwargs: dict[str, Any] = {
            "name": "STS2 Player",
            "instructions": system_prompt,
            "mcp_servers": [self._mcp_server],
        }
        if model is not None:
            agent_kwargs["model"] = model

        self._agent = Agent(**agent_kwargs)
        logger.info("AgentSDKEngine setup complete (model=%s)", self._config.resolved_model)

    async def decide(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ActionDecision]:
        if self._agent is None:
            logger.error("Engine not initialized — call setup() first")
            return None

        from agents import Runner

        scene = snapshot.run.scene if snapshot.run else None
        task = build_task_prompt(scene)

        # Add minimal context hint so the LLM knows the scene before reading state
        context_hint = self._build_context_hint(snapshot)
        user_message = f"{context_hint}\n\n{task}"

        try:
            result = await Runner.run(self._agent, user_message)
            return self._parse_result(result, scene)
        except Exception:
            logger.exception("Agent SDK decision failed")
            return None

    async def teardown(self) -> None:
        if self._mcp_server is not None:
            try:
                await self._mcp_server.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error closing MCP server")
            self._mcp_server = None
        self._agent = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_model(self) -> Any:
        """Resolve the model identifier for the Agent SDK."""
        provider = self._config.model_provider
        model_name = self._config.resolved_model

        if provider == ModelProvider.OPENAI:
            # Agent SDK uses OpenAI natively — just pass model name string
            return model_name

        # For non-OpenAI providers, try LiteLLM extension
        try:
            from agents.extensions.models.litellm_model import LitellmModel

            if provider == ModelProvider.ANTHROPIC:
                return LitellmModel(model=f"anthropic/{model_name}")
            if provider == ModelProvider.GOOGLE:
                return LitellmModel(model=f"gemini/{model_name}")
            if provider == ModelProvider.OLLAMA:
                return LitellmModel(model=f"ollama/{model_name}")
        except ImportError:
            logger.warning(
                "litellm not installed — falling back to OpenAI model. "
                "Install with: pip install 'openai-agents[litellm]'"
            )
            return model_name

        return model_name

    def _build_context_hint(self, snapshot: GameSnapshot) -> str:
        """Minimal context so LLM knows the scene before calling MCP tools."""
        parts = []
        run = snapshot.run
        if run:
            parts.append(f"Scene: {run.scene.value}")
            if run.character:
                parts.append(f"Character: {run.character}")
            parts.append(f"Floor: {run.floor}, Act: {run.act}")
            parts.append(f"HP: {run.hp}/{run.max_hp}, Gold: {run.gold}")
        return " | ".join(parts) if parts else "Read game state to begin."

    def _parse_result(self, result: Any, scene: SceneType | None) -> ActionDecision:
        """
        Parse the Agent SDK RunResult into an ActionDecision.

        In Agent SDK mode, the agent has already executed actions via MCP `act` tool.
        The final_output is the agent's summary/reasoning text.
        """
        output_text = str(result.final_output) if result.final_output else ""

        # Extract the last action from run items if available
        last_action = self._extract_last_action(result)

        return ActionDecision(
            action=last_action or {"type": "agent_managed"},
            source="agent_sdk",
            reasoning=output_text,
            confidence=0.8,
            extra={"new_items_count": len(result.new_items) if hasattr(result, "new_items") else 0},
        )

    def _extract_last_action(self, result: Any) -> Optional[dict[str, Any]]:
        """Try to extract the last `act` tool call from RunResult items."""
        if not hasattr(result, "new_items"):
            return None

        for item in reversed(result.new_items):
            # Look for tool call items that called "act"
            call = getattr(item, "raw_item", None)
            if call is None:
                continue
            if getattr(call, "type", None) != "function_call":
                continue
            if getattr(call, "name", None) == "act":
                try:
                    args = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                    return {"type": args.get("action", "unknown"), **args}
                except (json.JSONDecodeError, AttributeError):
                    pass
        return None
