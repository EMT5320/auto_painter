# features/game_bridge — 游戏状态桥接层
# 主实现：mod_bridge.py（通过 STS2AIAgent HTTP API 获取状态）
# 辅助实现：screen_reader.py（仅用于地图 CV 识别，降级兜底）
from .schemas import RunState, BattleState, MapState, ActionSet
from .base import GameBridgeBase

__all__ = ["RunState", "BattleState", "MapState", "ActionSet", "GameBridgeBase"]
