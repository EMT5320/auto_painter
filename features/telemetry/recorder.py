"""
features/telemetry/recorder.py
决策轨迹自动记录器

每次决策引擎做出决策后调用 record()，
将 (状态快照, 决策, 执行结果, prompt 上下文, 状态变化) 追加写入 JSONL 文件。
JSONL 格式便于后续流式读取构建训练集。

记录的数据用途：
  - 行为克隆 (BC): snapshot + action
  - SFT 微调: prompt + reasoning + action
  - 奖励回标: delta + outcome（离线由 replay_loader 计算）
"""
from __future__ import annotations
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from features.agent.engine import ActionDecision

from features.game_bridge.schemas import GameSnapshot

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/trajectories")


class TrajectoryRecorder:

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        run_id: Optional[str] = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id or self._new_run_id()
        self._file_path = self._data_dir / f"{self._run_id}.jsonl"
        self._step = 0
        logger.info("Trajectory recording to: %s", self._file_path)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def record(
        self,
        snapshot: GameSnapshot,
        action: dict[str, Any],
        result: Optional[dict] = None,
        source: str = "codex",
        *,
        decision: Optional[ActionDecision] = None,
        delta: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        记录一条决策轨迹。

        Args:
            snapshot:  动作执行前的完整游戏状态
            action:    执行的动作（rule_guard 校验后的版本）
            result:    Mod API 返回的执行结果（可能为 None）
            source:    决策来源（decision 不为空时从 decision.source 取）
            decision:  完整的决策对象，含 reasoning / confidence / extra
            delta:     动作执行后的状态变化 {hp_change, gold_change, ...}
        """
        entry = {
            "run_id": self._run_id,
            "step": self._step,
            "timestamp": time.time(),
            "source": decision.source if decision else source,
            "scene": snapshot.run.scene.value,
            "floor": snapshot.run.floor,
            "act": snapshot.run.act,
            "hp": snapshot.run.hp,
            "max_hp": snapshot.run.max_hp,
            "gold": snapshot.run.gold,
            "action": action,
            "result": result,
            "snapshot": self._serialize_snapshot(snapshot),
        }

        # 丰富决策上下文 — 用于 SFT / 数据质量过滤
        if decision is not None:
            entry["reasoning"] = decision.reasoning
            entry["confidence"] = decision.confidence
            if decision.extra:
                entry["extra"] = decision.extra

        # 可用动作集 — 用于约束解码训练
        if snapshot.actions is not None:
            entry["available_actions"] = self._serialize_action_set(snapshot.actions)

        # 动作后状态变化 — 用于离线奖励计算
        if delta is not None:
            entry["delta"] = delta

        self._append(entry)
        self._step += 1

    def record_run_end(self, outcome: str, floor_reached: int) -> None:
        """
        记录对局结束事件。

        Args:
            outcome:       "victory" | "death" | "abandoned"
            floor_reached: 到达的最高楼层
        """
        entry = {
            "run_id": self._run_id,
            "step": self._step,
            "timestamp": time.time(),
            "event": "run_end",
            "outcome": outcome,
            "floor_reached": floor_reached,
        }
        self._append(entry)
        logger.info("Run %s ended: %s at floor %d", self._run_id, outcome, floor_reached)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def file_path(self) -> Path:
        return self._file_path

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _append(self, entry: dict) -> None:
        try:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as e:
            logger.error("Failed to write trajectory: %s", e)

    @staticmethod
    def _serialize_snapshot(snapshot: GameSnapshot) -> dict:
        """将 GameSnapshot 转换为可 JSON 序列化的字典"""
        if snapshot.raw is not None:
            return snapshot.raw
        try:
            return asdict(snapshot)
        except Exception:
            return {}

    @staticmethod
    def _serialize_action_set(actions: Any) -> dict:
        """将 ActionSet 序列化为字典"""
        if hasattr(actions, "raw") and actions.raw is not None:
            return actions.raw
        try:
            return asdict(actions)
        except Exception:
            return {}

    @staticmethod
    def _new_run_id() -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"run_{ts}"
