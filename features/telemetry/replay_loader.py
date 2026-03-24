"""
features/telemetry/replay_loader.py
轨迹数据加载与分析工具

用于离线读取 recorder.py 生成的 JSONL 轨迹文件，
提供过滤、统计、蒸馏数据集构建等功能。

支持的数据集格式：
  - BC (行为克隆):    {state, action}
  - SFT (监督微调):   {messages: [{role, content}, ...]}
  - 奖励回标:         为每步添加 outcome + discounted_reward
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Generator, Optional

from features.agent.prompts import build_system_prompt

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data/trajectories")


class ReplayLoader:

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # 数据读取
    # ------------------------------------------------------------------

    def list_runs(self) -> list[str]:
        """列出所有已记录的 run_id"""
        return [
            p.stem
            for p in sorted(self._data_dir.glob("run_*.jsonl"))
        ]

    def iter_steps(
        self,
        run_id: Optional[str] = None,
        source_filter: Optional[str] = None,
        scene_filter: Optional[str] = None,
    ) -> Generator[dict, None, None]:
        """
        逐行迭代轨迹记录。

        Args:
            run_id:        只读取指定 run，None 时读取全部
            source_filter: 只返回指定来源（"codex" | "rule_fallback"）
            scene_filter:  只返回指定场景（"battle" | "map" | ...）
        """
        files = (
            [self._data_dir / f"{run_id}.jsonl"]
            if run_id
            else sorted(self._data_dir.glob("run_*.jsonl"))
        )
        for path in files:
            if not path.exists():
                logger.warning("Trajectory file not found: %s", path)
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if source_filter and entry.get("source") != source_filter:
                        continue
                    if scene_filter and entry.get("scene") != scene_filter:
                        continue
                    yield entry

    # ------------------------------------------------------------------
    # 统计分析
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """返回所有轨迹的汇总统计"""
        total_steps = 0
        runs: dict[str, dict] = {}

        for entry in self.iter_steps():
            run_id = entry.get("run_id", "unknown")
            if run_id not in runs:
                runs[run_id] = {"steps": 0, "outcome": None, "floor": 0}
            if entry.get("event") == "run_end":
                runs[run_id]["outcome"] = entry.get("outcome")
                runs[run_id]["floor"] = entry.get("floor_reached", 0)
            else:
                runs[run_id]["steps"] += 1
                total_steps += 1

        victories = sum(1 for r in runs.values() if r.get("outcome") == "victory")
        return {
            "total_runs": len(runs),
            "total_steps": total_steps,
            "victories": victories,
            "win_rate": victories / max(len(runs), 1),
            "runs": runs,
        }

    # ------------------------------------------------------------------
    # 蒸馏数据集构建
    # ------------------------------------------------------------------

    def build_bc_dataset(
        self,
        source_filter: str = "codex",
        min_floor: int = 0,
        *,
        only_victories: bool = False,
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """
        构建行为克隆训练集。

        每条样本格式：{"state": {...}, "action": {...}}
        只保留来自指定来源且楼层达到 min_floor 的样本。

        Args:
            source_filter:   只保留指定来源的决策
            min_floor:       只保留楼层 >= min_floor 的步骤
            only_victories:  只保留最终通关 run 的数据
            min_confidence:  只保留 confidence >= 阈值的步骤
        """
        victory_runs = self._get_victory_run_ids() if only_victories else None

        dataset = []
        for entry in self.iter_steps(source_filter=source_filter):
            if only_victories and entry.get("run_id") not in victory_runs:
                continue
            floor = entry.get("floor", 0) or 0
            if floor < min_floor:
                continue
            if min_confidence and entry.get("confidence", 1.0) < min_confidence:
                continue
            state = entry.get("snapshot", {})
            action = entry.get("action")
            if state and action:
                dataset.append({"state": state, "action": action})
        return dataset

    def build_sft_dataset(
        self,
        source_filter: Optional[str] = None,
        *,
        only_victories: bool = False,
        min_confidence: float = 0.0,
    ) -> list[dict]:
        """
        构建 SFT 微调数据集（OpenAI fine-tuning messages 格式）。

        每条样本格式：
        {
          "messages": [
            {"role": "system", "content": "..."},
            {"role": "user",   "content": "..."},
            {"role": "assistant", "content": "..."}
          ]
        }

        assistant 消息包含 action + reasoning，模拟 CoT 输出。
        """
        victory_runs = self._get_victory_run_ids() if only_victories else None

        dataset = []
        for entry in self.iter_steps(source_filter=source_filter):
            if only_victories and entry.get("run_id") not in victory_runs:
                continue
            if min_confidence and entry.get("confidence", 1.0) < min_confidence:
                continue
            # Skip entries without action
            action = entry.get("action")
            if not action:
                continue
            # Skip run_end events
            if entry.get("event") == "run_end":
                continue

            sample = self._entry_to_sft(entry)
            if sample:
                dataset.append(sample)
        return dataset

    def label_rewards(
        self,
        gamma: float = 0.99,
        victory_bonus: float = 10.0,
        death_penalty: float = -5.0,
        hp_loss_weight: float = 0.01,
    ) -> list[dict]:
        """
        为每条轨迹步骤回标奖励。

        奖励规则：
          - immediate reward = hp_loss_weight * hp_change（来自 delta）
          - run 结束时：victory → +victory_bonus, death → +death_penalty
          - 折扣累积：R_t = r_immediate + gamma * R_{t+1}

        Returns:
            列表，每项为 {run_id, step, action, reward, discounted_return, outcome}
        """
        # Group steps by run
        runs: dict[str, list[dict]] = {}
        outcomes: dict[str, str] = {}

        for entry in self.iter_steps():
            run_id = entry.get("run_id", "unknown")
            if entry.get("event") == "run_end":
                outcomes[run_id] = entry.get("outcome", "unknown")
                continue
            runs.setdefault(run_id, []).append(entry)

        labeled = []
        for run_id, steps in runs.items():
            outcome = outcomes.get(run_id, "unknown")

            # Calculate immediate rewards
            rewards = []
            for step in steps:
                delta = step.get("delta") or {}
                hp_change = delta.get("hp_change", 0)
                r = hp_loss_weight * hp_change
                rewards.append(r)

            # Terminal bonus/penalty
            if outcome == "victory" and rewards:
                rewards[-1] += victory_bonus
            elif outcome == "death" and rewards:
                rewards[-1] += death_penalty

            # Backward discounted return
            returns = [0.0] * len(rewards)
            if rewards:
                returns[-1] = rewards[-1]
                for t in range(len(rewards) - 2, -1, -1):
                    returns[t] = rewards[t] + gamma * returns[t + 1]

            for step, r, g in zip(steps, rewards, returns):
                labeled.append({
                    "run_id": run_id,
                    "step": step.get("step"),
                    "scene": step.get("scene"),
                    "action": step.get("action"),
                    "reward": round(r, 4),
                    "discounted_return": round(g, 4),
                    "outcome": outcome,
                })

        return labeled

    def export_dataset(
        self,
        output_path: str | Path,
        fmt: str = "sft",
        **kwargs,
    ) -> int:
        """
        导出数据集到 JSONL 文件。

        Args:
            output_path: 输出文件路径
            fmt:         数据集格式 "sft" | "bc" | "rewards"
            **kwargs:    传递给对应的 build 方法

        Returns:
            导出的样本数量
        """
        if fmt == "sft":
            data = self.build_sft_dataset(**kwargs)
        elif fmt == "bc":
            data = self.build_bc_dataset(**kwargs)
        elif fmt == "rewards":
            data = self.label_rewards(**kwargs)
        else:
            raise ValueError(f"Unknown format: {fmt}")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        logger.info("Exported %d samples to %s (fmt=%s)", len(data), output_path, fmt)
        return len(data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_victory_run_ids(self) -> set[str]:
        """Collect run_ids that ended in victory."""
        ids = set()
        for entry in self.iter_steps():
            if entry.get("event") == "run_end" and entry.get("outcome") == "victory":
                ids.add(entry.get("run_id", ""))
        return ids

    def _entry_to_sft(self, entry: dict) -> Optional[dict]:
        """Convert a trajectory entry to an SFT training sample."""
        action = entry.get("action", {})
        reasoning = entry.get("reasoning", "")
        scene = entry.get("scene", "")

        # Build system prompt for this scene
        from features.game_bridge.schemas import SceneType
        try:
            scene_type = SceneType(scene)
        except ValueError:
            scene_type = None
        system = build_system_prompt(scene_type)

        # Reconstruct user message from snapshot or stored prompt
        extra = entry.get("extra", {})
        prompt = extra.get("prompt", {})

        if prompt.get("user"):
            user_msg = prompt["user"]
        elif prompt.get("combined"):
            # Codex: combined prompt already includes system, use as user
            user_msg = prompt["combined"]
        else:
            # Fallback: build from snapshot summary
            user_msg = self._snapshot_to_user_msg(entry)

        # Build assistant response: reasoning + action
        if reasoning:
            assistant_msg = f"{reasoning}\n\nAction: {json.dumps(action, ensure_ascii=False)}"
        else:
            assistant_msg = json.dumps(action, ensure_ascii=False)

        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ]
        }

    @staticmethod
    def _snapshot_to_user_msg(entry: dict) -> str:
        """Build a minimal user message from entry fields (when no prompt stored)."""
        parts = [
            f"Scene: {entry.get('scene', 'unknown')}",
            f"Floor: {entry.get('floor', '?')}, Act: {entry.get('act', '?')}",
            f"HP: {entry.get('hp', '?')}/{entry.get('max_hp', '?')}",
            f"Gold: {entry.get('gold', '?')}",
        ]
        return "Current game state:\n" + "\n".join(parts)
