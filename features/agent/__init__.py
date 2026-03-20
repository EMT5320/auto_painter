# features/agent — 决策协调与规则兜底层
# coordinator.py: 识别当前场景，构造 MCP 上下文，分发给 Codex
# rule_guard.py:  合法性校验 + 安全边界 + Codex 不可用时的降级决策
from .coordinator import Coordinator
from .rule_guard import RuleGuard

__all__ = ["Coordinator", "RuleGuard"]
