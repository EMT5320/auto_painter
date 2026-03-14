"""
features/route_planner/optimizer.py
路线评分与推荐

职责：
  - 接收用户偏好（对各节点类型的权重）
  - 对所有候选路径打分，返回 Top N 推荐

实现状态：核心逻辑已实现（Phase 2 可用）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .recognizer import NodeType
from .graph import MapGraph


# ── 默认节点权重（中立基准） ──────────────────────────────────

# 节点基础价值（与偏好无关的固有价值，可根据游戏版本调整）
_BASE_VALUE: dict[NodeType, float] = {
    NodeType.MONSTER:  0.0,
    NodeType.ELITE:    1.5,   # 精英有掉落价值，默认略正向
    NodeType.REST:     1.0,   # 营火通常有帮助
    NodeType.MERCHANT: 0.8,
    NodeType.UNKNOWN:  0.5,
    NodeType.TREASURE: 1.2,
    NodeType.BOSS:     0.0,   # Boss 不计入偏好（必经路）
}


# ── 数据结构 ─────────────────────────────────────────────────

@dataclass
class RoutePreferences:
    """
    用户对各节点类型的偏好权重。

    weights: {NodeType: float}
      - 正值：偏好该类节点（尽量多经过）
      - 负值：厌恶该类节点（尽量少经过）
      - 0.0：中立
      - 建议范围：-2.0 ~ +2.0

    示例（想要尽量多营火少战斗）：
        prefs = RoutePreferences(weights={
            NodeType.REST:    +2.0,
            NodeType.MONSTER: -1.0,
        })
    """
    weights: dict[NodeType, float] = field(default_factory=dict)

    def get_weight(self, node_type: NodeType) -> float:
        return self.weights.get(node_type, 0.0)

    @classmethod
    def from_slider_values(cls, slider_dict: dict[str, int]) -> "RoutePreferences":
        """
        从 GUI 滑块值（-2~+2 整数）创建 RoutePreferences。

        slider_dict 格式：{"rest": 2, "elite": 1, "monster": -1, ...}
        """
        weights = {}
        key_to_type = {
            "monster":  NodeType.MONSTER,
            "elite":    NodeType.ELITE,
            "rest":     NodeType.REST,
            "merchant": NodeType.MERCHANT,
            "unknown":  NodeType.UNKNOWN,
            "treasure": NodeType.TREASURE,
        }
        for key, val in slider_dict.items():
            if key in key_to_type and val != 0:
                weights[key_to_type[key]] = float(val)
        return cls(weights=weights)


# ── 评分函数 ──────────────────────────────────────────────────

def score_route(
    path: list[int],
    graph: MapGraph,
    prefs: RoutePreferences,
) -> float:
    """
    计算单条路线的综合得分。

    得分 = Σ (base_value[type] + user_weight[type]) × 出现次数
          + diversity_bonus
          - consecutive_monster_penalty

    :param path:  节点 ID 序列
    :param graph: MapGraph
    :param prefs: 用户偏好
    :return: 浮点数得分（越高越推荐）
    """
    type_counts = graph.get_node_type_count(path)
    total_score = 0.0

    for node_type, count in type_counts.items():
        base = _BASE_VALUE.get(node_type, 0.0)
        user = prefs.get_weight(node_type)
        total_score += (base + user) * count

    # 多样性奖励（经过多种稀有节点加分）
    rare_types = {NodeType.ELITE, NodeType.MERCHANT, NodeType.TREASURE, NodeType.REST}
    visited_rare = rare_types & set(type_counts.keys())
    total_score += len(visited_rare) * 0.3

    # 连续怪物惩罚
    consecutive = 0
    max_consecutive = 0
    for nid in path:
        if nid in graph.nodes and graph.nodes[nid].node_type == NodeType.MONSTER:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
    total_score -= max(0, max_consecutive - 2) * 0.5

    return total_score


def rank_routes(
    routes: list[list[int]],
    graph: MapGraph,
    prefs: RoutePreferences,
    top_n: int = 3,
) -> list[tuple[float, list[int]]]:
    """
    对所有候选路径评分并返回 Top N。

    :param routes: find_all_routes() 返回的路径列表
    :param graph:  MapGraph
    :param prefs:  用户偏好
    :param top_n:  返回数量
    :return: [(score, path), ...] 按得分降序，最多 top_n 条

    使用示例：
        all_routes = find_all_routes(graph)
        prefs = RoutePreferences.from_slider_values({"rest": 2, "elite": 1})
        top_routes = rank_routes(all_routes, graph, prefs, top_n=3)
        for score, path in top_routes:
            print(f"得分 {score:.1f}: {path}")
    """
    if not routes:
        return []

    scored = [(score_route(path, graph, prefs), path) for path in routes]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]


def describe_route(path: list[int], graph: MapGraph) -> str:
    """生成路线的文字描述（用于 GUI 显示）"""
    if not path:
        return "（空路线）"

    type_counts = graph.get_node_type_count(path)
    parts = []
    for node_type in [NodeType.REST, NodeType.ELITE, NodeType.MERCHANT,
                      NodeType.TREASURE, NodeType.UNKNOWN, NodeType.MONSTER]:
        cnt = type_counts.get(node_type, 0)
        if cnt > 0:
            parts.append(f"{node_type.display_name}×{cnt}")

    return "  →  ".join(parts) if parts else f"共 {len(path)} 个节点"
