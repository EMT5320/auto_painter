"""
features/agent/coordinator.py
场景调度器

职责：
  1. 识别当前游戏场景类型
  2. 从 game_bridge 获取完整状态快照
  3. 通过决策引擎（Agent SDK / Direct LLM / Rule）获取决策
  4. 调用 rule_guard 校验决策合法性
  5. 通过 game_bridge 执行最终动作
  6. 将决策轨迹交给 telemetry 记录
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from features.game_bridge.base import GameBridgeBase
from features.game_bridge.schemas import GameSnapshot, SceneType
from features.telemetry.recorder import TrajectoryRecorder

from .config import EngineConfig, EngineType
from .engine import ActionDecision, EngineBase, RuleEngine
from .rule_guard import RuleGuard

logger = logging.getLogger(__name__)


def _create_engine(config: EngineConfig, rule_guard: RuleGuard) -> EngineBase:
    """Factory: create the appropriate engine based on config."""
    effective = config.effective_engine_type()

    if effective == EngineType.CODEX_CLI:
        from .codex_engine import CodexCLIEngine
        return CodexCLIEngine(config)

    if effective == EngineType.AGENT_SDK:
        from .sdk_engine import AgentSDKEngine
        return AgentSDKEngine(config, rule_guard=rule_guard)

    if effective == EngineType.DIRECT_LLM:
        from .direct_engine import DirectLLMEngine
        return DirectLLMEngine(config)

    return RuleEngine(rule_guard)


class Coordinator:
    """
    游戏助手主循环协调器。

    调用方只需执行 coordinator.step()，
    Coordinator 会自动完成：感知 → 决策 → 校验 → 执行 → 记录。

    支持三种引擎模式:
      - agent_sdk:  LLM 通过 MCP 自主读状态+执行（coordinator 只管生命周期）
      - direct_llm: coordinator 读状态 → LLM 返回决策 → coordinator 执行
      - rule_only:  纯规则决策（RuleGuard 降级）
    """

    def __init__(
        self,
        bridge: GameBridgeBase,
        rule_guard: RuleGuard,
        recorder: Optional[TrajectoryRecorder] = None,
        config: Optional[EngineConfig] = None,
    ) -> None:
        self.bridge = bridge
        self.rule_guard = rule_guard
        self.recorder = recorder
        self._config = config or EngineConfig()
        self._engine: Optional[EngineBase] = None
        self._engine_started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the decision engine."""
        if self._engine_started:
            return
        self._engine = _create_engine(self._config, self.rule_guard)
        try:
            await self._engine.setup()
            self._engine_started = True
            logger.info(
                "Engine started: %s", self._config.effective_engine_type().value
            )
        except Exception:
            logger.exception("Engine setup failed, falling back to rule_only")
            self._engine = RuleEngine(self.rule_guard)
            await self._engine.setup()
            self._engine_started = True

    async def stop(self) -> None:
        """Shut down the decision engine."""
        if self._engine is not None:
            await self._engine.teardown()
            self._engine = None
            self._engine_started = False

    # ------------------------------------------------------------------
    # 主循环入口
    # ------------------------------------------------------------------

    def step(self) -> bool:
        """Synchronous wrapper — runs async_step in an event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an async context — schedule as a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.async_step()).result()

        return asyncio.run(self.async_step())

    async def async_step(self) -> bool:
        """
        Execute one decision cycle (async).

        Returns:
            True  — step executed successfully
            False — bridge unavailable or terminal scene
        """
        if not self._engine_started:
            await self.start()

        if not self.bridge.is_available():
            logger.warning("Bridge not available, skipping step.")
            return False

        snapshot = self.bridge.get_snapshot_safe()
        if snapshot is None:
            logger.warning("Failed to get snapshot, skipping step.")
            return False

        scene = snapshot.run.scene
        logger.debug("Current scene: %s", scene)

        if scene in (SceneType.GAME_OVER, SceneType.MAIN_MENU, SceneType.UNKNOWN):
            return False

        # --- Decision ---
        decision = await self._get_decision(snapshot)

        if decision is None:
            logger.warning("No decision for scene %s", scene)
            return False

        action = decision.action
        source = decision.source

        # Agent-managed mode: Codex CLI / Agent SDK already executed via MCP
        engine_type = self._config.effective_engine_type()
        is_agent_managed = (
            engine_type in (EngineType.CODEX_CLI, EngineType.AGENT_SDK)
            and action.get("type") == "agent_managed"
        )

        if is_agent_managed:
            result = {"status": "agent_managed"}
        else:
            # Validate + execute (direct_llm and rule_only modes)
            validated = self.rule_guard.validate(action, snapshot)
            if validated is None:
                logger.warning("Action rejected by rule_guard: %s", action)
                validated = self.rule_guard.safe_default(snapshot)
                source = "rule_fallback"
                decision = ActionDecision(
                    action=validated,
                    source=source,
                    reasoning="rule_guard fallback after validation failure",
                )
            action = validated
            result = self.bridge.perform_action(action)

        # --- Capture state delta (for offline reward computation) ---
        delta = self._compute_delta(snapshot)

        # --- Record ---
        if self.recorder is not None:
            self.recorder.record(
                snapshot=snapshot,
                action=action,
                result=result,
                source=source,
                decision=decision,
                delta=delta,
            )

        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_decision(
        self, snapshot: GameSnapshot
    ) -> Optional[ActionDecision]:
        """Try the engine, fall back to rule_guard on failure."""
        if self._engine is None:
            return None

        try:
            decision = await self._engine.decide(snapshot)
            if decision is not None:
                return decision
        except Exception:
            logger.exception("Engine decision failed, falling back to rules")

        # Fallback
        fallback = self.rule_guard.decide(snapshot)
        if fallback is None:
            return None
        return ActionDecision(
            action=fallback,
            source="rule_fallback",
            reasoning="engine failed, rule_guard fallback",
        )

    def _build_context(self, snapshot: GameSnapshot) -> dict:
        """
        Serialize GameSnapshot for debugging / direct_llm mode.
        """
        ctx: dict = {
            "scene": snapshot.run.scene.value,
            "character": snapshot.run.character,
            "act": snapshot.run.act,
            "floor": snapshot.run.floor,
            "hp": snapshot.run.hp,
            "max_hp": snapshot.run.max_hp,
            "gold": snapshot.run.gold,
        }
        if snapshot.battle:
            ctx["battle"] = {
                "energy": snapshot.battle.energy,
                "hand_count": len(snapshot.battle.hand),
                "enemies": [
                    {"name": e.name, "hp": e.hp, "intent": e.intent}
                    for e in snapshot.battle.enemies
                ],
            }
        if snapshot.map:
            ctx["map"] = {
                "available_next": [
                    {"id": n.node_id, "type": n.node_type.value}
                    for n in snapshot.map.available_next_nodes
                ]
            }
        return ctx

    def _compute_delta(self, snapshot_before: GameSnapshot) -> Optional[dict]:
        """
        Capture key state changes after action execution.

        Keeps it lightweight: only fetches HP/gold/scene from the bridge
        to compute deltas. Returns None if the bridge is unavailable.
        """
        after = self.bridge.get_snapshot_safe()
        if after is None:
            return None

        delta: dict = {}
        hp_before = snapshot_before.run.hp or 0
        hp_after = after.run.hp or 0
        gold_before = snapshot_before.run.gold or 0
        gold_after = after.run.gold or 0

        delta["hp_change"] = hp_after - hp_before
        delta["gold_change"] = gold_after - gold_before

        if after.run.scene != snapshot_before.run.scene:
            delta["scene_changed"] = after.run.scene.value

        if after.run.floor != snapshot_before.run.floor:
            delta["floor_changed"] = after.run.floor

        # Battle-specific: count enemies killed
        if snapshot_before.battle and after.battle:
            alive_before = sum(1 for e in snapshot_before.battle.enemies if not e.is_dead)
            alive_after = sum(1 for e in after.battle.enemies if not e.is_dead)
            if alive_before > alive_after:
                delta["enemies_killed"] = alive_before - alive_after

        return delta if delta else None
