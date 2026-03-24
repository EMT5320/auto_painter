# features/agent — 决策引擎层
# coordinator.py:   场景调度 + 引擎生命周期管理
# rule_guard.py:    合法性校验 + 安全边界 + 降级决策
# engine.py:        引擎抽象接口 (EngineBase, RuleEngine)
# config.py:        引擎配置 (EngineConfig, EngineType, ModelProvider)
# codex_engine.py:  Codex CLI 引擎 (订阅方案，推荐)
# sdk_engine.py:    Agent SDK 引擎 (MCP 集成)
# direct_engine.py: 直接 LLM API 引擎
# prompts.py:       System prompt 管理
from .config import EngineConfig, EngineType, ModelProvider
from .coordinator import Coordinator
from .engine import ActionDecision, EngineBase, RuleEngine
from .rule_guard import RuleGuard

__all__ = [
    "Coordinator",
    "RuleGuard",
    "EngineConfig",
    "EngineType",
    "ModelProvider",
    "EngineBase",
    "RuleEngine",
    "ActionDecision",
]
