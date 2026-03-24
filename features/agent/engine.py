"""
features/agent/engine.py
决策引擎抽象层

定义 EngineBase 接口和通用数据类型。
具体实现: RuleEngine / AgentSDKEngine / DirectLLMEngine
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from features.game_bridge.schemas import GameSnapshot

logger = logging.getLogger(__name__)


@dataclass
class ActionDecision:
    """引擎产出的决策结果"""

    action: dict[str, Any]  # {"type": "play_card", "card_id": ..., ...}
    source: str = "unknown"  # "agent_sdk" | "direct_llm" | "rule_fallback"
    reasoning: str = ""
    confidence: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class EngineBase(abc.ABC):
    """决策引擎统一接口"""

    @abc.abstractmethod
    async def setup(self) -> None:
        """初始化引擎资源（MCP 子进程等）"""

    @abc.abstractmethod
    async def decide(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ActionDecision]:
        """
        根据游戏状态返回决策。

        Returns:
            ActionDecision or None（引擎无法给出决策时）
        """

    @abc.abstractmethod
    async def teardown(self) -> None:
        """释放引擎资源"""

    async def __aenter__(self) -> EngineBase:
        await self.setup()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.teardown()


class RuleEngine(EngineBase):
    """包装 RuleGuard.decide()，作为最终降级引擎。"""

    def __init__(self, rule_guard: Any) -> None:
        self._guard = rule_guard

    async def setup(self) -> None:
        pass

    async def decide(
        self,
        snapshot: GameSnapshot,
        available_actions: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[ActionDecision]:
        action = self._guard.decide(snapshot)
        if action is None:
            return None
        return ActionDecision(
            action=action,
            source="rule_fallback",
            reasoning="rule_guard fallback decision",
        )

    async def teardown(self) -> None:
        pass
