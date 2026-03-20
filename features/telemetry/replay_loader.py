"""
features/telemetry/replay_loader.py
轨迹数据加载与分析工具

用于离线读取 recorder.py 生成的 JSONL 轨迹文件，
提供过滤、统计、蒸馏数据集构建等功能。
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Generator, Optional

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
    # 蒸馏数据集构建（供 training/ 使用）
    # ------------------------------------------------------------------

    def build_bc_dataset(
        self,
        source_filter: str = "codex",
        min_floor: int = 0,
    ) -> list[dict]:
        """
        构建行为克隆训练集。

        每条样本格式：{"state": {...}, "action": {...}}
        只保留来自 Codex 决策且楼层达到 min_floor 的样本。
        """
        dataset = []
        for entry in self.iter_steps(source_filter=source_filter):
            floor = entry.get("floor", 0) or 0
            if floor < min_floor:
                continue
            state = entry.get("snapshot", {})
            action = entry.get("action")
            if state and action:
                dataset.append({"state": state, "action": action})
        return dataset
