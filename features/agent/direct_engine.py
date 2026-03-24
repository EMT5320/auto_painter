"""
features/agent/direct_engine.py
Direct LLM engine — calls LLM API directly without MCP.

Reads game state via ModBridge, builds a prompt, gets structured output,
and returns an ActionDecision for the coordinator to execute.

Useful for prompt debugging and when MCP Server is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from features.game_bridge.schemas import GameSnapshot, SceneType

from .config import EngineConfig, ModelProvider
from .engine import ActionDecision, EngineBase
from .prompts import build_system_prompt

logger = logging.getLogger(__name__)

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "description": "Action type, e.g. play_card, end_turn, choose_map_node"},
        "card_index": {"type": "integer"},
        "target_index": {"type": "integer"},
        "option_index": {"type": "integer"},
        "reasoning": {"type": "string", "description": "Brief explanation of your decision"},
    },
    "required": ["action", "reasoning"],
    "additionalProperties": False,
}


class DirectLLMEngine(EngineBase):
    """
    Lightweight engine that sends game state directly to an LLM API
    and parses the structured JSON response.

    Does NOT use MCP — the coordinator handles execution.
    """

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._client: Any = None

    async def setup(self) -> None:
        provider = self._config.model_provider

        if provider == ModelProvider.OPENAI:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError("openai package required: pip install openai") from e
            self._client = AsyncOpenAI(api_key=self._config.api_key)

        elif provider == ModelProvider.ANTHROPIC:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:
                raise ImportError("anthropic package required: pip install anthropic") from e
            self._client = AsyncAnthropic(api_key=self._config.api_key)

        else:
            # For other providers, fall back to OpenAI-compatible API
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError("openai package required: pip install openai") from e
            self._client = AsyncOpenAI(api_key=self._config.api_key)

        logger.info("DirectLLMEngine setup complete (provider=%s)", provider.value)

    async def decide(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ActionDecision]:
        if self._client is None:
            return None

        scene = snapshot.run.scene if snapshot.run else None
        system_prompt = build_system_prompt(scene)
        user_message = self._build_user_message(snapshot, available_actions)

        try:
            raw = await self._call_llm(system_prompt, user_message)
            return self._parse_response(raw, system_prompt, user_message)
        except Exception:
            logger.exception("DirectLLM decision failed")
            return None

    async def teardown(self) -> None:
        self._client = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_llm(self, system: str, user: str) -> dict[str, Any]:
        """Call the LLM and return parsed JSON."""
        provider = self._config.model_provider

        if provider == ModelProvider.ANTHROPIC:
            return await self._call_anthropic(system, user)

        # OpenAI / OpenAI-compatible
        return await self._call_openai(system, user)

    async def _call_openai(self, system: str, user: str) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self._config.resolved_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    async def _call_anthropic(self, system: str, user: str) -> dict[str, Any]:
        response = await self._client.messages.create(
            model=self._config.resolved_model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        text = response.content[0].text if response.content else "{}"
        # Extract JSON from response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            raise

    def _build_user_message(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]],
    ) -> str:
        """Serialize game state into a compact user message."""
        parts = ["Current game state:"]
        run = snapshot.run
        if run:
            parts.append(f"Scene: {run.scene.value}, Character: {run.character}")
            parts.append(f"Act: {run.act}, Floor: {run.floor}")
            parts.append(f"HP: {run.hp}/{run.max_hp}, Gold: {run.gold}")

        if snapshot.battle:
            b = snapshot.battle
            parts.append(f"\nCombat — Energy: {b.energy}/{b.max_energy}, Block: {b.player_block}")
            hand_desc = [
                f"{c.name}(cost={c.cost}, id={c.card_id})"
                for c in b.hand
            ]
            parts.append(f"Hand: {', '.join(hand_desc)}")
            enemy_desc = [
                f"{e.name}(hp={e.hp}/{e.max_hp}, intent={e.intent})"
                for e in b.enemies if not e.is_dead
            ]
            parts.append(f"Enemies: {', '.join(enemy_desc)}")

        if snapshot.map and snapshot.map.available_next_nodes:
            nodes_desc = [
                f"{n.node_id}({n.node_type.value})"
                for n in snapshot.map.available_next_nodes
            ]
            parts.append(f"\nAvailable map nodes: {', '.join(nodes_desc)}")

        if available_actions:
            parts.append(f"\nAvailable actions: {json.dumps(available_actions, ensure_ascii=False)}")

        parts.append(
            "\nRespond with a JSON object: "
            '{"action": "...", "reasoning": "...", '
            '"card_index": ..., "target_index": ..., "option_index": ...}'
            " (include only relevant index fields)"
        )
        return "\n".join(parts)

    def _parse_response(
        self,
        raw: dict[str, Any],
        system_prompt: str = "",
        user_message: str = "",
    ) -> ActionDecision:
        action_type = raw.get("action", "noop")
        params: dict[str, Any] = {"type": action_type}
        for key in ("card_index", "target_index", "option_index", "card_id", "node_id"):
            if key in raw:
                params[key] = raw[key]

        return ActionDecision(
            action=params,
            source="direct_llm",
            reasoning=raw.get("reasoning", ""),
            confidence=0.7,
            extra={
                "model": self._config.resolved_model,
                "prompt": {"system": system_prompt, "user": user_message},
            },
        )
