"""
features/agent/codex_engine.py
Codex CLI engine — drives decisions via `codex exec` subprocess.

Uses the same MCP tools as AgentSDKEngine, but through Codex CLI
instead of the openai-agents SDK. This leverages the Codex subscription
($20/mo flat rate) for cost-effective validation before migrating to
native API calls.

The flow is intentionally identical to AgentSDKEngine:
  1. Codex reads game state via MCP tools (get_game_state, etc.)
  2. Codex looks up game knowledge via get_game_data_item
  3. Codex executes actions via the `act` tool
  4. We parse the JSONL output to extract what happened

Migration to AgentSDKEngine only requires changing --engine codex_cli
to --engine agent_sdk. Prompts and MCP tools are fully reused.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from features.game_bridge.schemas import GameSnapshot, SceneType

from .config import EngineConfig
from .engine import ActionDecision, EngineBase
from .prompts import build_system_prompt, build_task_prompt

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CodexCLIEngine(EngineBase):
    """
    Decision engine backed by `codex exec` CLI.

    Same agent_managed pattern as AgentSDKEngine — Codex autonomously
    reads state and executes actions via MCP, coordinator only manages
    lifecycle and records trajectories.
    """

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._codex_path: Optional[str] = None

    async def setup(self) -> None:
        self._codex_path = shutil.which("codex")
        if not self._codex_path:
            raise FileNotFoundError(
                "codex CLI not found in PATH. "
                "Install from: https://github.com/openai/codex"
            )
        logger.info("CodexCLIEngine ready (codex=%s)", self._codex_path)

    async def decide(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ActionDecision]:
        scene = snapshot.run.scene if snapshot.run else None
        prompt = self._build_prompt(snapshot, scene)

        try:
            events = await self._run_codex(prompt)
            return self._parse_events(events, scene, prompt)
        except Exception:
            logger.exception("Codex CLI decision failed")
            return None

    async def teardown(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Prompt construction — reuses the same prompts as AgentSDKEngine
    # ------------------------------------------------------------------

    def _build_prompt(self, snapshot: GameSnapshot, scene: SceneType | None) -> str:
        """Build the prompt sent to codex exec."""
        parts = []

        # System-level instructions (Codex exec uses prompt as combined input)
        parts.append(build_system_prompt(scene))

        # Context hint — same as AgentSDKEngine._build_context_hint
        parts.append("")
        parts.append(self._build_context_hint(snapshot))

        # Task instruction
        parts.append("")
        parts.append(build_task_prompt(scene))

        # Explicit instruction to use MCP and act
        parts.append("")
        parts.append(
            "Use the sts2-ai-agent MCP tools to read the full game state, "
            "then execute the best action via the `act` tool. "
            "After acting, briefly explain what you did and why."
        )

        return "\n".join(parts)

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

    # ------------------------------------------------------------------
    # Subprocess execution
    # ------------------------------------------------------------------

    async def _run_codex(self, prompt: str) -> list[dict[str, Any]]:
        """Run `codex exec` and return parsed JSONL events."""
        cmd = [
            self._codex_path,
            "exec",
            "--json",
            "--full-auto",
            "--ephemeral",
            "-C", str(_PROJECT_ROOT),
        ]

        # Model override
        if self._config.model_name:
            cmd.extend(["-m", self._config.model_name])

        # Prompt as argument
        cmd.append(prompt)

        timeout = self._config.step_timeout
        logger.debug("Running: %s", " ".join(cmd[:6]) + " ...")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("Codex exec timed out after %.0fs", timeout)
            return []

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            logger.warning(
                "Codex exec returned %d: %s", proc.returncode, stderr[:500]
            )

        if stderr.strip():
            logger.debug("Codex stderr: %s", stderr[:500])

        # Parse JSONL output
        events = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Non-JSON line from codex: %s", line[:200])

        logger.debug("Got %d events from codex exec", len(events))
        return events

    # ------------------------------------------------------------------
    # Event parsing — extract action and reasoning from JSONL
    # ------------------------------------------------------------------

    def _parse_events(
        self, events: list[dict[str, Any]], scene: SceneType | None,
        prompt: str = "",
    ) -> ActionDecision:
        """Parse codex exec JSONL events into an ActionDecision."""
        last_act_call: Optional[dict[str, Any]] = None
        reasoning_parts: list[str] = []
        total_tokens = 0

        for event in events:
            event_type = event.get("type", "")

            if event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "")

                # Agent text messages → collect as reasoning
                if item_type == "agent_message":
                    text = item.get("text", "")
                    if text:
                        reasoning_parts.append(text)

                # MCP tool calls → look for act calls
                elif item_type == "mcp_tool_call":
                    tool_name = item.get("tool", "") or item.get("name", "")
                    if tool_name.endswith("act") or tool_name == "act":
                        args = item.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        last_act_call = args

                # Function/tool calls (alternative format)
                elif item_type == "function_call":
                    name = item.get("name", "")
                    if "act" in name:
                        args_raw = item.get("arguments", "{}")
                        if isinstance(args_raw, str):
                            try:
                                args_raw = json.loads(args_raw)
                            except json.JSONDecodeError:
                                args_raw = {}
                        last_act_call = args_raw

            elif event_type == "turn.completed":
                usage = event.get("usage", {})
                total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        # Build action dict from the last act call
        if last_act_call:
            action = {
                "type": last_act_call.get("action", "unknown"),
                **last_act_call,
            }
        else:
            action = {"type": "agent_managed"}

        return ActionDecision(
            action=action,
            source="codex_cli",
            reasoning="\n".join(reasoning_parts),
            confidence=0.8,
            extra={
                "model": self._config.resolved_model,
                "prompt": {"combined": prompt},
                "total_tokens": total_tokens,
            },
        )
