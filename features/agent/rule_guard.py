"""
features/agent/rule_guard.py
合法性校验 + 安全边界 + 降级规则决策

职责（Codex 架构下）：
  1. 校验 Codex 返回的动作在当前状态下是否合法
  2. 血量过低时强制防御优先等安全边界
  3. Codex 不可用或返回非法动作时，提供基础规则决策作为 fallback
"""
from __future__ import annotations
import logging
from typing import Optional

from features.game_bridge.schemas import (
    GameSnapshot,
    SceneType,
    BattleState,
    MapState,
    NodeType,
)

logger = logging.getLogger(__name__)

LOW_HP_THRESHOLD = 0.30


class RuleGuard:

    # ------------------------------------------------------------------
    # 合法性校验
    # ------------------------------------------------------------------

    def validate(self, action: dict, snapshot: GameSnapshot) -> Optional[dict]:
        """
        校验 action 是否在当前状态下合法。

        Returns:
            原始 action（合法），或 None（非法，调用方应调用 safe_default）。
        """
        action_type = action.get("type")
        if not action_type:
            return None

        scene = snapshot.run.scene
        battle = snapshot.battle

        if action_type == "play_card":
            return self._validate_play_card(action, battle)

        if action_type == "end_turn":
            return action if scene == SceneType.BATTLE else None

        if action_type == "choose_node":
            return self._validate_choose_node(action, snapshot.map)

        if action_type in ("use_potion", "discard_potion"):
            return action

        if action_type in ("choose_reward", "skip_reward",
                           "buy_item", "leave_shop",
                           "choose_event_option", "rest", "smith"):
            return action

        logger.debug("Unknown action type: %s", action_type)
        return action

    def _validate_play_card(
        self, action: dict, battle: Optional[BattleState]
    ) -> Optional[dict]:
        if battle is None:
            return None
        card_id = action.get("card_id")
        if not card_id:
            return None
        hand_ids = {c.card_id for c in battle.hand}
        if card_id not in hand_ids:
            logger.debug("Card %s not in hand", card_id)
            return None
        card = next((c for c in battle.hand if c.card_id == card_id), None)
        if card and card.cost > battle.energy:
            logger.debug("Not enough energy for card %s", card_id)
            return None
        return action

    def _validate_choose_node(
        self, action: dict, map_state: Optional[MapState]
    ) -> Optional[dict]:
        if map_state is None:
            return None
        node_id = action.get("node_id")
        available_ids = {n.node_id for n in map_state.available_next_nodes}
        if node_id not in available_ids:
            logger.debug("Node %s not in available_next", node_id)
            return None
        return action

    # ------------------------------------------------------------------
    # 降级决策（Codex 不可用时）
    # ------------------------------------------------------------------

    def decide(self, snapshot: GameSnapshot) -> Optional[dict]:
        """提供基础规则决策，不依赖 Codex"""
        scene = snapshot.run.scene

        if scene == SceneType.BATTLE:
            return self._battle_fallback(snapshot)

        if scene == SceneType.MAP:
            return self._map_fallback(snapshot)

        if scene == SceneType.REST:
            return self._rest_fallback(snapshot)

        logger.debug("No fallback rule for scene: %s", scene)
        return None

    def _battle_fallback(self, snapshot: GameSnapshot) -> Optional[dict]:
        """极简规则：能量不足或无牌时结束回合"""
        battle = snapshot.battle
        if battle is None:
            return None

        hp_ratio = (snapshot.run.hp or 0) / max(snapshot.run.max_hp or 1, 1)
        is_low_hp = hp_ratio < LOW_HP_THRESHOLD

        for card in battle.hand:
            if card.cost > battle.energy:
                continue
            if is_low_hp and "attack" in card.card_id.lower():
                continue
            target_index = 0 if battle.enemies else None
            return {
                "type": "play_card",
                "card_id": card.card_id,
                "target_index": target_index,
            }

        return {"type": "end_turn"}

    def _map_fallback(self, snapshot: GameSnapshot) -> Optional[dict]:
        """地图降级：优先选 REST，其次按节点类型偏好排序"""
        map_state = snapshot.map
        if not map_state or not map_state.available_next_nodes:
            return None

        preference_order = [
            NodeType.REST,
            NodeType.SHOP,
            NodeType.TREASURE,
            NodeType.EVENT,
            NodeType.MONSTER,
            NodeType.ELITE,
        ]
        nodes = map_state.available_next_nodes
        for preferred_type in preference_order:
            for node in nodes:
                if node.node_type == preferred_type:
                    return {"type": "choose_node", "node_id": node.node_id}

        return {"type": "choose_node", "node_id": nodes[0].node_id}

    def _rest_fallback(self, snapshot: GameSnapshot) -> Optional[dict]:
        """休息点：血量低于 60% 时回血，否则锻造"""
        hp = snapshot.run.hp or 0
        max_hp = snapshot.run.max_hp or 1
        if hp / max_hp < 0.60:
            return {"type": "rest"}
        return {"type": "smith"}

    # ------------------------------------------------------------------
    # 兜底动作
    # ------------------------------------------------------------------

    def safe_default(self, snapshot: GameSnapshot) -> dict:
        """当 validate 返回 None 且 decide 也失败时的最终兜底"""
        if snapshot.run.scene == SceneType.BATTLE:
            return {"type": "end_turn"}
        return {"type": "noop"}
