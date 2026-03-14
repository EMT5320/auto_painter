"""
features/route_planner/graph.py
地图图结构与路径枚举

职责：
  - 从节点/边列表构建有向无环图（DAG）
  - 枚举所有从起点到终点的完整路径（DFS）
  - 提供图查询接口

实现状态：核心逻辑已实现（Phase 1 可用）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict

from .recognizer import MapNode, NodeType


# ── 数据结构 ─────────────────────────────────────────────────

@dataclass
class MapGraph:
    """
    杀戮尖塔2 地图的有向图表示。

    图是一个 DAG，从起点层（layer=0）流向 Boss（layer=max）。
    edges 存储有向边：layer_i → layer_i+1 方向。
    """
    nodes: dict[int, MapNode] = field(default_factory=dict)
    # adjacency: node_id -> list of neighbor node_ids（方向：低层→高层）
    adjacency: dict[int, list[int]] = field(default_factory=lambda: defaultdict(list))

    @property
    def start_nodes(self) -> list[MapNode]:
        """返回起点层（layer=0）的所有节点"""
        return [n for n in self.nodes.values() if n.layer == 0]

    @property
    def end_nodes(self) -> list[MapNode]:
        """返回终点层（layer=max）的所有节点"""
        if not self.nodes:
            return []
        max_layer = max(n.layer for n in self.nodes.values())
        return [n for n in self.nodes.values() if n.layer == max_layer]

    def get_neighbors(self, node_id: int) -> list[MapNode]:
        """获取某节点的所有后继节点"""
        return [self.nodes[nid] for nid in self.adjacency.get(node_id, [])
                if nid in self.nodes]

    def get_node_type_count(self, path: list[int]) -> dict[NodeType, int]:
        """统计某路径上各节点类型的数量"""
        counts: dict[NodeType, int] = {}
        for nid in path:
            if nid in self.nodes:
                nt = self.nodes[nid].node_type
                counts[nt] = counts.get(nt, 0) + 1
        return counts


# ── 构建函数 ──────────────────────────────────────────────────

def build_map_graph(
    nodes: list[MapNode],
    edges: list[tuple[int, int]],
) -> MapGraph:
    """
    从识别结果构建 MapGraph。

    :param nodes: 节点列表（来自 recognizer.recognize_map）
    :param edges: 边列表，每项 (from_id, to_id)
    :return: 构建好的 MapGraph

    如果边列表为空（识别失败），会尝试通过层次关系自动推断连接：
      同层相邻节点之间、不同层 X 坐标最近的节点对，视为相连。
    """
    graph = MapGraph()
    graph.nodes = {n.node_id: n for n in nodes}

    if edges:
        for from_id, to_id in edges:
            graph.adjacency[from_id].append(to_id)
    else:
        # 回退策略：通过层次 + X 坐标推断连接
        _infer_edges_by_layer(graph)

    return graph


def _infer_edges_by_layer(graph: MapGraph) -> None:
    """
    当边检测失败时，通过层次关系推断连接。

    策略：对每个节点，在下一层（layer+1）中找 X 坐标最近的 1-2 个节点连接。
    适用于 STS2 地图的扇形展开结构。
    """
    if not graph.nodes:
        return

    max_layer = max(n.layer for n in graph.nodes.values())
    layers: dict[int, list[MapNode]] = defaultdict(list)
    for node in graph.nodes.values():
        layers[node.layer].append(node)

    # X 坐标相近阈值：屏幕宽度约 1920，节点间距约 100-300px
    X_PROXIMITY = 300

    for layer_idx in range(max_layer):
        current_layer = layers[layer_idx]
        next_layer = layers[layer_idx + 1]
        if not current_layer or not next_layer:
            continue

        for cur_node in current_layer:
            cx = cur_node.position[0]
            # 找 X 坐标在 cx ± X_PROXIMITY 范围内的下层节点
            candidates = [
                n for n in next_layer
                if abs(n.position[0] - cx) <= X_PROXIMITY
            ]
            if not candidates:
                # 找最近的节点
                candidates = [min(next_layer, key=lambda n: abs(n.position[0] - cx))]

            for candidate in candidates:
                graph.adjacency[cur_node.node_id].append(candidate.node_id)


# ── 路径枚举 ──────────────────────────────────────────────────

def find_all_routes(graph: MapGraph) -> list[list[int]]:
    """
    DFS 枚举所有从起点层到终点层的完整路径。

    :return: 路径列表，每条路径为节点 ID 序列（包含起点和终点）

    STS2 地图路径数量通常在几十到几百条，全枚举可行。
    若路径数超过阈值（5000条），自动截断并打印警告。
    """
    MAX_PATHS = 5000
    all_paths: list[list[int]] = []
    end_ids = {n.node_id for n in graph.end_nodes}

    def dfs(current_id: int, current_path: list[int]) -> None:
        if len(all_paths) >= MAX_PATHS:
            return
        current_path.append(current_id)

        if current_id in end_ids:
            all_paths.append(list(current_path))
        else:
            for neighbor_id in graph.adjacency.get(current_id, []):
                if neighbor_id not in current_path:  # 防环
                    dfs(neighbor_id, current_path)

        current_path.pop()

    for start_node in graph.start_nodes:
        dfs(start_node.node_id, [])

    if len(all_paths) >= MAX_PATHS:
        print(f"⚠ 路径数超过上限 {MAX_PATHS}，已截断")

    return all_paths
