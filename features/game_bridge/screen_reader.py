"""
features/game_bridge/screen_reader.py
CV 截图辅助桥接（仅用于地图识别，降级兜底）

当 STS2AIAgent Mod 不可用时，此模块提供有限的状态感知能力：
  - 地图节点识别（复用 features/route_planner/recognizer.py）
  - 无法感知战斗状态、卡牌、遗物等——战斗场景降级到纯规则

注意：此模块仅作降级兜底，不作为主要状态来源。
"""
from __future__ import annotations
import logging
from typing import Optional

import numpy as np

from core.screen import capture_screen
from features.route_planner.recognizer import recognize_map
from .base import GameBridgeBase
from .schemas import GameSnapshot, MapState, MapNodeData, NodeType, RunState, SceneType

logger = logging.getLogger(__name__)


class ScreenReader(GameBridgeBase):
    """基于 CV 截图的降级状态读取，仅支持地图场景"""

    def is_available(self) -> bool:
        try:
            img = capture_screen()
            return img is not None and img.size > 0
        except Exception:
            return False

    def get_snapshot(self) -> Optional[GameSnapshot]:
        try:
            img = capture_screen()
            map_graph = recognize_map(img)
            map_state = self._graph_to_map_state(map_graph)
            run = RunState(scene=SceneType.MAP)
            return GameSnapshot(run=run, map=map_state)
        except Exception as e:
            logger.warning("ScreenReader.get_snapshot failed: %s", e)
            return None

    def get_scene(self) -> SceneType:
        # CV 模式下无法可靠区分场景，保守返回 UNKNOWN
        return SceneType.UNKNOWN

    @staticmethod
    def _graph_to_map_state(map_graph) -> Optional[MapState]:
        """将 route_planner 的 MapGraph 转换为 MapState"""
        if map_graph is None:
            return None
        nodes = []
        for node in getattr(map_graph, "nodes", []):
            nodes.append(MapNodeData(
                node_id=str(getattr(node, "id", "")),
                node_type=NodeType(getattr(node, "node_type", "unknown")),
                x=getattr(node, "x", 0),
                y=getattr(node, "y", 0),
            ))
        return MapState(nodes=nodes)
