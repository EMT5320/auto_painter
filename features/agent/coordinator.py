"""
features/agent/coordinator.py
场景调度器

职责：
  1. 识别当前游戏场景类型
  2. 从 game_bridge 获取完整状态快照
  3. 构造传递给 Codex (via MCP) 的上下文
  4. 调用 rule_guard 校验 Codex 返回的动作
  5. 通过 game_bridge 执行最终动作
  6. 将决策轨迹交给 telemetry 记录
"""
from __future__ import annotations
import logging
from typing import Optional

from features.game_bridge.base import GameBridgeBase
from features.game_bridge.schemas import GameSnapshot, SceneType
from features.telemetry.recorder import TrajectoryRecorder
from .rule_guard import RuleGuard

logger = logging.getLogger(__name__)


class Coordinator:
    """
    游戏助手主循环协调器。

    调用方只需执行 coordinator.step()，
    Coordinator 会自动完成：感知 → 决策（Codex）→ 校验 → 执行 → 记录。
    """

    def __init__(
        self,
        bridge: GameBridgeBase,
        rule_guard: RuleGuard,
        recorder: Optional[TrajectoryRecorder] = None,
    ) -> None:
        self.bridge = bridge
        self.rule_guard = rule_guard
        self.recorder = recorder

    # ------------------------------------------------------------------
    # 主循环入口
    # ------------------------------------------------------------------

    def step(self) -> bool:
        """
        执行一步决策循环。

        Returns:
            True  — 本步成功执行
            False — bridge 不可用或场景为 UNKNOWN/GAME_OVER，循环应暂停
        """
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

        # 构造 Codex 输入上下文（供 MCP 工具调用使用）
        context = self._build_context(snapshot)

        # TODO: 调用 Codex MCP 工具获取决策
        # action = codex_client.decide(context)
        action = self._fallback_decision(snapshot)

        if action is None:
            logger.warning("No action produced for scene %s", scene)
            return False

        # 规则校验
        validated_action = self.rule_guard.validate(action, snapshot)
        if validated_action is None:
            logger.warning("Action rejected by rule_guard: %s", action)
            validated_action = self.rule_guard.safe_default(snapshot)

        # 执行
        result = self.bridge.perform_action(validated_action)

        # 记录轨迹
        if self.recorder is not None:
            self.recorder.record(
                snapshot=snapshot,
                action=validated_action,
                result=result,
                source="rule_fallback",
            )

        return True

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _build_context(self, snapshot: GameSnapshot) -> dict:
        """
        将 GameSnapshot 序列化为传给 Codex 的上下文字典。

        Codex 通过 MCP 工具读取此结构，无需手动序列化——
        此方法主要用于调试日志和非 MCP 模式的回退路径。
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

    def _fallback_decision(self, snapshot: GameSnapshot) -> Optional[dict]:
        """
        Codex 不可用时的降级决策入口，委托给 rule_guard。
        """
        return self.rule_guard.decide(snapshot)
