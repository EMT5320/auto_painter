"""
features/game_bridge/mod_bridge.py
STS2AIAgent Mod HTTP API 客户端

通过 STS2AIAgent Mod 暴露的本地 HTTP API 获取游戏状态并发送操作指令。
端口号和路由在 Mod 安装后需按实际情况确认（默认尝试 58000）。
"""
from __future__ import annotations
import logging
from typing import Any, Optional

import requests

from .base import GameBridgeBase
from .schemas import GameSnapshot, SceneType

logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 58000
DEFAULT_TIMEOUT = 5.0


class ModBridge(GameBridgeBase):
    """通过 STS2AIAgent HTTP API 获取游戏状态"""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = f"http://{host}:{port}"
        self._timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # GameBridgeBase 接口实现
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            resp = self._session.get(
                f"{self._base_url}/health", timeout=self._timeout
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def get_snapshot(self) -> Optional[GameSnapshot]:
        data = self._get("/state")
        if data is None:
            return None
        try:
            return GameSnapshot.from_dict(data)
        except Exception as e:
            logger.warning("Failed to parse GameSnapshot: %s", e)
            return None

    def get_scene(self) -> SceneType:
        data = self._get("/scene")
        if data is None:
            return SceneType.UNKNOWN
        try:
            return SceneType(data.get("scene", "unknown"))
        except ValueError:
            return SceneType.UNKNOWN

    # ------------------------------------------------------------------
    # 动作执行
    # ------------------------------------------------------------------

    def perform_action(self, action: dict[str, Any]) -> Optional[dict]:
        """
        向 Mod 发送操作指令。

        action 格式示例（以实际 Mod API 文档为准）：
          {"type": "play_card", "card_id": "Strike", "target_index": 0}
          {"type": "end_turn"}
          {"type": "choose_node", "node_id": "node_3_2"}
          {"type": "choose_reward", "reward_id": "card_1"}
        """
        return self._post("/action", action)

    def end_turn(self) -> Optional[dict]:
        return self.perform_action({"type": "end_turn"})

    def play_card(self, card_id: str, target_index: Optional[int] = None) -> Optional[dict]:
        action: dict[str, Any] = {"type": "play_card", "card_id": card_id}
        if target_index is not None:
            action["target_index"] = target_index
        return self.perform_action(action)

    def choose_node(self, node_id: str) -> Optional[dict]:
        return self.perform_action({"type": "choose_node", "node_id": node_id})

    # ------------------------------------------------------------------
    # 内部 HTTP 方法
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Optional[dict]:
        try:
            resp = self._session.get(
                f"{self._base_url}{path}", timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.debug("GET %s failed: %s", path, e)
            return None

    def _post(self, path: str, payload: dict) -> Optional[dict]:
        try:
            resp = self._session.post(
                f"{self._base_url}{path}",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.debug("POST %s failed: %s", path, e)
            return None
