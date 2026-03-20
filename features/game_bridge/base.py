"""
features/game_bridge/base.py
游戏状态获取抽象接口

所有状态来源（Mod HTTP API、CV 截图）都实现此接口，
使 coordinator 可以在不同来源之间无感切换。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from .schemas import GameSnapshot, SceneType


class GameBridgeBase(ABC):

    @abstractmethod
    def is_available(self) -> bool:
        """检查状态来源当前是否可用"""
        ...

    @abstractmethod
    def get_snapshot(self) -> Optional[GameSnapshot]:
        """获取当前完整游戏状态快照，不可用时返回 None"""
        ...

    @abstractmethod
    def get_scene(self) -> SceneType:
        """获取当前场景类型（快速路径，比完整 snapshot 开销小）"""
        ...

    def get_snapshot_safe(self) -> Optional[GameSnapshot]:
        """带异常捕获的 get_snapshot，任何错误都返回 None"""
        try:
            return self.get_snapshot()
        except Exception:
            return None
