"""
features/route_planner/recognizer.py
地图节点识别模块

职责：
  从游戏地图截图中，使用模板匹配识别各类节点的位置和类型，
  并检测节点间的连线，输出供 graph.py 使用的原始数据。

实现状态：骨架（Phase 1 待实现）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cv2
import numpy as np
from PIL import Image


# ── 节点类型定义 ────────────────────────────────────────────

class NodeType(Enum):
    START    = "start"     # 起点（地图唯一入口，树的根节点）
    MONSTER  = "monster"   # 普通敌人
    ELITE    = "elite"     # 精英
    REST     = "rest"      # 休息/营火
    MERCHANT = "merchant"  # 商人
    UNKNOWN  = "unknown"   # 未知/问号
    TREASURE = "treasure"  # 宝箱
    BOSS     = "boss"      # Boss（终点，树的叶节点）

    @property
    def display_name(self) -> str:
        _names = {
            "start":    "🔰 起点",
            "monster":  "👾 敌人",
            "elite":    "👹 精英",
            "rest":     "🔥 休息",
            "merchant": "🏪 商人",
            "unknown":  "❓ 未知",
            "treasure": "🗝 宝箱",
            "boss":     "💀 Boss",
        }
        return _names[self.value]


# ── 数据结构 ─────────────────────────────────────────────────

@dataclass
class RawMatch:
    """模板匹配的原始命中结果（NMS 前）"""
    node_type: NodeType
    position:  tuple[int, int]   # 匹配区域左上角坐标
    score:     float             # 匹配置信度 [0, 1]
    scale:     float             # 使用的缩放系数


@dataclass
class MapNode:
    """地图上的单个节点"""
    node_id:   int
    node_type: NodeType
    position:  tuple[int, int]   # 节点中心坐标（拼接画布空间，或单帧屏幕坐标）
    screen_pos: tuple[int, int] = (0, 0)  # 原始屏幕坐标（用于点击操作，与 scroll_step 配合）
    scroll_step: int = 0         # 节点所在的滚动步骤（0 = 最底部/起点可见）
    layer:     int = 0           # 所在层数（0 = 最底层起点）
    confidence: float = 1.0      # 识别置信度


# ── 常量 ──────────────────────────────────────────────────────

MATCH_THRESHOLD = 0.75          # 模板匹配置信度阈值
MATCH_SCALES    = [0.8, 0.9, 1.0, 1.1, 1.2]  # 多尺度匹配系数
NMS_IOU_THRESHOLD = 0.4         # NMS 重叠阈值（IoU）
NODE_MERGE_X_THRESHOLD = 70     # 跨模板/跨帧的节点横向合并阈值
NODE_MERGE_Y_THRESHOLD = 70     # 跨模板/跨帧的节点纵向合并阈值
NODE_MERGE_DISTANCE = 90        # 节点中心欧氏距离合并阈值


# ── 内部工具函数 ──────────────────────────────────────────────

def _load_templates(tmpl_dir: str) -> list[np.ndarray]:
    """从目录加载所有 PNG/JPG 模板图片，转为灰度"""
    templates = []
    if not os.path.isdir(tmpl_dir):
        return templates
    for fname in os.listdir(tmpl_dir):
        if fname.lower().endswith((".png", ".jpg", ".bmp")):
            path = os.path.join(tmpl_dir, fname)
            tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tmpl is not None:
                templates.append(tmpl)
    return templates


def _iou(box1: tuple, box2: tuple) -> float:
    """计算两个矩形框的 IoU（Intersection over Union）"""
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    ix = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
    iy = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
    inter = ix * iy
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


def _nms(matches: list[RawMatch], template_size: tuple[int, int]) -> list[RawMatch]:
    """
    非极大值抑制：去除同一位置的重复匹配
    使用置信度排序后贪心保留
    """
    if not matches:
        return []

    # 按置信度降序
    sorted_m = sorted(matches, key=lambda m: m.score, reverse=True)
    kept: list[RawMatch] = []
    tw, th = template_size

    for m in sorted_m:
        mx, my = m.position
        box_m = (mx, my, int(tw * m.scale), int(th * m.scale))
        # 检查是否与已保留的框重叠过多
        if all(_iou(box_m, (k.position[0], k.position[1],
                             int(tw * k.scale), int(th * k.scale))) < NMS_IOU_THRESHOLD
               for k in kept):
            kept.append(m)

    return kept


def _assign_layers(nodes: list[MapNode]) -> list[MapNode]:
    """
    根据 Y 坐标将节点分配到层数。
    STS2 地图中，越靠下（Y值越大）的节点层数越低（越接近起点）。

    改进：使用自适应阈值，基于差值分布的双峰特性检测层边界。
    核心问题：固定 60px 阈值在拼接大图（>2000px）+ 大量噪声节点时，
    所有相邻节点 Y 差约 7px，阈值几乎从不触发 → 所有节点归入同一层 → 边检测全部失效。
    解决：根据差值的百分位分布自动识别"层内小差值"和"层间大差值"的分界点。
    """
    if not nodes:
        return nodes

    # 按 Y 坐标升序（越小越靠上 = 越接近Boss）
    sorted_nodes = sorted(nodes, key=lambda nd: nd.position[1])
    y_coords = [nd.position[1] for nd in sorted_nodes]

    if len(y_coords) == 1:
        sorted_nodes[0].layer = 0
        return sorted_nodes

    # 计算相邻节点 Y 差值序列
    diffs = [y_coords[i + 1] - y_coords[i] for i in range(len(y_coords) - 1)]
    diffs_sorted = sorted(diffs)
    nd_count = len(diffs_sorted)

    p50 = diffs_sorted[max(0, nd_count * 50 // 100)]
    p95 = diffs_sorted[min(nd_count - 1, nd_count * 95 // 100)]

    if p95 > p50 * 3 and p50 > 0:
        # 明显的双峰分布（层内小差值 << 层间大差值），取几何均值作为分界
        y_threshold = float((p50 * p95) ** 0.5)
    else:
        # 分布较均匀（如噪声节点均匀散布在拼接图上）
        # 基于总 Y 范围估算：STS2 最多约 10 层，层间距 = y_range / 10
        # 层内阈值 = 层间距 * 0.5
        y_range = y_coords[-1] - y_coords[0]
        y_threshold = max(35.0, y_range / 10 * 0.5)

    # 限制在合理范围内
    y_threshold = max(35.0, min(250.0, y_threshold))

    layer_idx = 0
    prev_y = sorted_nodes[0].position[1]

    for node in sorted_nodes:
        if abs(node.position[1] - prev_y) > y_threshold:
            layer_idx += 1
            prev_y = node.position[1]
        node.layer = layer_idx

    # 翻转：最底层（Y最大）= 层0（起点），层号越大越靠近Boss
    max_layer = max(node.layer for node in nodes)
    for node in nodes:
        node.layer = max_layer - node.layer

    return nodes


def _reindex_nodes(nodes: list[MapNode]) -> tuple[list[MapNode], dict[int, int]]:
    """将节点 ID 重排为连续编号，并返回 old_id -> new_id 映射。"""
    id_map: dict[int, int] = {}
    reindexed: list[MapNode] = []

    for new_id, node in enumerate(nodes):
        id_map[node.node_id] = new_id
        reindexed.append(MapNode(
            node_id=new_id,
            node_type=node.node_type,
            position=node.position,
            screen_pos=node.screen_pos,
            scroll_step=node.scroll_step,
            layer=node.layer,
            confidence=node.confidence,
        ))

    return reindexed, id_map


def _deduplicate_spatial_nodes(nodes: list[MapNode]) -> list[MapNode]:
    """
    对模板匹配得到的节点做二次空间去重。

    NMS 只能在“同一节点类型内部”去重，无法处理：
      - 同一节点被不同模板/尺度重复命中
      - 同一节点被不同类型误判命中
      - 滚动拼接后轻微重叠造成的重复节点

    这里按空间邻近聚类，将这些重复命中合并成唯一节点。
    """
    if not nodes:
        return []

    sorted_nodes = sorted(nodes, key=lambda n: n.confidence, reverse=True)
    clusters: list[list[MapNode]] = []

    for node in sorted_nodes:
        merged = False
        for cluster in clusters:
            ref = cluster[0]
            dx = abs(node.position[0] - ref.position[0])
            dy = abs(node.position[1] - ref.position[1])
            dist = float(np.hypot(dx, dy))
            if (
                dx <= NODE_MERGE_X_THRESHOLD
                and dy <= NODE_MERGE_Y_THRESHOLD
                and dist <= NODE_MERGE_DISTANCE
            ):
                cluster.append(node)
                merged = True
                break

        if not merged:
            clusters.append([node])

    deduped: list[MapNode] = []
    for cluster in clusters:
        # 使用置信度加权中心，减轻模板抖动
        total_weight = sum(max(n.confidence, 1e-6) for n in cluster)
        avg_x = int(round(sum(n.position[0] * max(n.confidence, 1e-6) for n in cluster) / total_weight))
        avg_y = int(round(sum(n.position[1] * max(n.confidence, 1e-6) for n in cluster) / total_weight))

        # 节点类型使用“按置信度加权投票”；并列时取最高置信度者
        type_votes: dict[NodeType, float] = {}
        for node in cluster:
            type_votes[node.node_type] = type_votes.get(node.node_type, 0.0) + node.confidence
        best_type = max(
            type_votes,
            key=lambda node_type: (type_votes[node_type], max(n.confidence for n in cluster if n.node_type == node_type)),
        )
        best_conf = max(n.confidence for n in cluster)
        best_node = max(cluster, key=lambda n: n.confidence)

        deduped.append(MapNode(
            node_id=best_node.node_id,
            node_type=best_type,
            position=(avg_x, avg_y),
            screen_pos=best_node.screen_pos,
            scroll_step=best_node.scroll_step,
            confidence=best_conf,
        ))

    return deduped


def _refine_detected_map(
    nodes: list[MapNode],
    edges: list[tuple[int, int]],
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """
    用树状图约束净化识别结果：
      1. 去掉重复边、自环和指向不存在节点的边
      2. 严格过滤方向错误的边：只保留从 layer_i → layer_i+1 的相邻层有向边
         （彻底杜绝横向跳跃 / 跨层移动 / 反向边）
      3. 保留最大弱连通分量，丢弃孤立噪声节点
      4. 兜底：若最大分量 < 总节点数的 40%（或 < 5 个），
         说明虚线检测基本失败，改用层次推断边重新求最大分量
      5. 重新编号节点并重新分层
    """
    if not nodes:
        return [], []

    node_ids = {node.node_id for node in nodes}
    node_layer = {node.node_id: node.layer for node in nodes}

    # ── 1. 去重 + 严格相邻层方向过滤 ──────────────────────────────
    # 边必须满足：to_id 所在层 = from_id 所在层 + 1
    # 这里同时保证了：
    #   • 无横向边（同层节点 layer 相等，差值=0 ≠ 1）
    #   • 无跨层边（层差≥2 的节点对）
    #   • 无反向边（from 层 > to 层）
    clean_edges: set[tuple[int, int]] = set()
    for from_id, to_id in edges:
        if (
            from_id != to_id
            and from_id in node_ids
            and to_id in node_ids
            and node_layer.get(to_id, -999) == node_layer.get(from_id, -998) + 1
        ):
            clean_edges.add((from_id, to_id))

    # ── 2. 构建无向邻接表（用于连通分量），并取最大分量 ──────────────
    def _find_largest_component(
        all_node_ids: set[int],
        directed_edges: set[tuple[int, int]],
    ) -> set[int]:
        undirected: dict[int, set[int]] = {nid: set() for nid in all_node_ids}
        for f, t in directed_edges:
            undirected[f].add(t)
            undirected[t].add(f)

        visited: set[int] = set()
        components: list[set[int]] = []
        for nid in undirected:
            if nid in visited:
                continue
            stack = [nid]
            comp: set[int] = set()
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.add(cur)
                stack.extend(undirected[cur] - visited)
            components.append(comp)

        return max(components, key=len) if components else set()

    largest = _find_largest_component(node_ids, clean_edges)

    # ── 3. 兜底：最大分量过小时，启用层次推断边补充 ─────────────────
    FALLBACK_RATIO = 0.40
    if len(largest) < max(5, int(len(nodes) * FALLBACK_RATIO)):
        _, fallback_edges = _infer_edges_fallback(nodes)
        # 推断边同样要过严格相邻层约束
        fallback_clean: set[tuple[int, int]] = {
            (f, t)
            for f, t in fallback_edges
            if node_layer.get(t, -999) == node_layer.get(f, -998) + 1
        }
        merged_edges = clean_edges | fallback_clean
        largest = _find_largest_component(node_ids, merged_edges)
        clean_edges = merged_edges

    # ── 4. 过滤到最大分量并重新编号 ───────────────────────────────
    filtered_nodes = [n for n in nodes if n.node_id in largest]
    filtered_edges = [(f, t) for f, t in clean_edges if f in largest and t in largest]

    filtered_nodes = _assign_layers(filtered_nodes)
    reindexed_nodes, id_map = _reindex_nodes(filtered_nodes)
    reindexed_edges = sorted({
        (id_map[f], id_map[t]) for f, t in filtered_edges
    })
    return reindexed_nodes, reindexed_edges


# ── 层次推断兜底 ──────────────────────────────────────────────

def _infer_edges_fallback(
    nodes: list[MapNode],
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """
    层次推断兜底：当虚线检测失败（边数过少）时，按 X 距离最近原则推断相邻层节点间的连接。

    策略：对每个节点，在上一层（layer+1）中找 X 坐标最近的 1-2 个节点连接。
    仅作为兜底使用，实际连线关系应以虚线检测为准。

    限制：只推断 X 差 <= 500px 的节点对，超过此范围的节点对视为不连通。
    """
    from collections import defaultdict
    if not nodes:
        return nodes, []

    layers: dict[int, list[MapNode]] = defaultdict(list)
    for node in nodes:
        layers[node.layer].append(node)

    max_layer = max(nd.layer for nd in nodes)
    inferred: list[tuple[int, int]] = []
    MAX_X_DIFF = 500

    for layer_idx in range(max_layer):
        curr = layers.get(layer_idx, [])
        nxt = layers.get(layer_idx + 1, [])
        if not curr or not nxt:
            continue
        for n1 in curr:
            cx = n1.position[0]
            candidates = sorted(
                [nd for nd in nxt if abs(nd.position[0] - cx) <= MAX_X_DIFF],
                key=lambda nd: abs(nd.position[0] - cx),
            )
            for n2 in candidates[:2]:
                inferred.append((n1.node_id, n2.node_id))

    return nodes, inferred


# ── 边检测 ────────────────────────────────────────────────────

def _detect_edges_by_lines(
    nodes: list[MapNode],
    screenshot_gray: np.ndarray,
) -> list[tuple[int, int]]:
    """
    通过检测虚线连接来判断相邻层节点之间的边。

    STS2 地图中，只有被虚线连接的节点才互通。虚线颜色比背景暗。
    策略：
      1. 对相邻层（layer_i → layer_i+1）的每对节点
      2. 做三重几何约束（方向 / 横向距离 / 斜率）—— 杜绝横向跳跃和跨层连接
      3. 在两节点中心连线上等间距采样像素
      4. 统计暗色像素（亮度低于阈值）占比
      5. 若暗色占比超过阈值（虚线是间断的，约 15-45% 为暗色），则认为有连接

    :param nodes:            已分层的节点列表
    :param screenshot_gray:  灰度截图（numpy 数组）
    :return: 边列表 [(from_id, to_id), ...]

    约束说明：
      - 横向跳跃：X 差超过屏幕宽 30%（原 50%）→ 必然不是同一路线上的节点
      - 跨层移动：只在相邻层（layer_i / layer_i+1）之间检测，且 n2.Y 必须小于 n1.Y
      - 水平假边：斜率过低（X差 > Y差 * 2.5）→ 层分配可能有误，拒绝连接
    """
    if not nodes:
        return []

    edges: list[tuple[int, int]] = []

    # 按层分组
    from collections import defaultdict
    layers: dict[int, list[MapNode]] = defaultdict(list)
    for node in nodes:
        layers[node.layer].append(node)

    max_layer = max(n.layer for n in nodes)
    h, w = screenshot_gray.shape[:2]

    # 估算背景亮度：使用图像四周边缘区域，避免被节点图标污染
    edge_samples = np.concatenate([
        screenshot_gray[:20, :].flatten(),
        screenshot_gray[-20:, :].flatten(),
        screenshot_gray[:, :20].flatten(),
        screenshot_gray[:, -20:].flatten(),
    ])
    bg_brightness = float(np.median(edge_samples))

    # 虚线比背景暗，暗色阈值 = 背景亮度 - 偏移
    dark_threshold = bg_brightness - 25
    # 虚线上暗色像素占采样点的最低比例
    MIN_DARK_RATIO = 0.15

    for layer_idx in range(max_layer):
        curr = layers.get(layer_idx, [])
        nxt = layers.get(layer_idx + 1, [])
        if not curr or not nxt:
            continue

        for n1 in curr:
            x1, y1 = n1.position
            for n2 in nxt:
                x2, y2 = n2.position

                # ────────────────────────────────────────────────────
                # 约束1：严格方向验证
                # layer_idx（下层）Y 坐标必须显著大于 layer_idx+1（上层）Y 坐标
                # Boss 在顶部（Y 最小），起点在底部（Y 最大）
                # 若 n2.Y >= n1.Y，说明层分配有误，此对节点不连接
                # ────────────────────────────────────────────────────
                y_sep = y1 - y2  # 正数 = n1 确实在 n2 下方（符合方向）
                if y_sep < 15:
                    continue

                # ────────────────────────────────────────────────────
                # 约束2：横向距离约束（原 50%，收紧至 30%）
                # STS2 路线为树状扇形展开，相邻层节点横向偏移有限
                # ────────────────────────────────────────────────────
                x_diff = abs(x2 - x1)
                if x_diff > w * 0.30:
                    continue

                # ────────────────────────────────────────────────────
                # 约束3：斜率（方向角）约束
                # 防止"几乎水平"的假边：X差 > Y差 * 2.5 时拒绝
                # 这类边通常是层分配把同层节点误分到相邻层造成的
                # ────────────────────────────────────────────────────
                if x_diff > y_sep * 2.5:
                    continue

                # 沿连线采样，跳过节点中心附近（避免节点图标干扰）
                dist = max(1.0, float((x_diff ** 2 + y_sep ** 2) ** 0.5))
                num_samples = max(20, int(dist / 4))

                # 跳过端点 25% 区域（节点图标可能遮挡连线，原20%略放大）
                skip_ratio = 0.25
                dark_count = 0
                valid_count = 0

                for i in range(num_samples):
                    t = i / (num_samples - 1)
                    if t < skip_ratio or t > (1 - skip_ratio):
                        continue

                    sx = int(x1 + (x2 - x1) * t)
                    sy = int(y1 + (y2 - y1) * t)

                    if 0 <= sx < w and 0 <= sy < h:
                        pixel_val = float(screenshot_gray[sy, sx])
                        valid_count += 1
                        if pixel_val < dark_threshold:
                            dark_count += 1

                if valid_count > 0:
                    dark_ratio = dark_count / valid_count
                    if dark_ratio >= MIN_DARK_RATIO:
                        edges.append((n1.node_id, n2.node_id))

    return edges


# ── 公开接口 ──────────────────────────────────────────────────

# START 和 BOSS 的图标每局随机变化，无法用固定模板匹配。
# 它们通过 graph.mark_structural_nodes 依据图拓扑结构推断：
#   START → 入度为 0 的节点（路线从此开始分叉）
#   BOSS  → 出度为 0 的节点（分叉路线在此收束）
_STRUCTURAL_NODE_TYPES: frozenset[NodeType] = frozenset({NodeType.START, NodeType.BOSS})


def load_all_templates(templates_dir: str) -> dict[NodeType, list[np.ndarray]]:
    """
    从模板目录加载所有节点类型的模板图片。

    注意：START 和 BOSS 被排除在外——它们由图拓扑结构推断，
    不依赖模板，以应对每局 Boss 图标随机变化的情况。

    目录结构：
        templates_dir/
            monster/  *.png
            elite/    *.png
            rest/     *.png
            ...
    """
    result: dict[NodeType, list[np.ndarray]] = {}
    for node_type in NodeType:
        if node_type in _STRUCTURAL_NODE_TYPES:
            continue  # 由图拓扑结构推断，跳过模板扫描
        tmpl_dir = os.path.join(templates_dir, node_type.value)
        templates = _load_templates(tmpl_dir)
        if templates:
            result[node_type] = templates
    return result


def detect_nodes(
    screenshot_gray: np.ndarray,
    templates: dict[NodeType, list[np.ndarray]],
    match_threshold: float = MATCH_THRESHOLD,
) -> list[MapNode]:
    """
    对灰度截图执行多尺度模板匹配，返回去重后的节点列表。

    :param screenshot_gray: 游戏地图截图（灰度 numpy 数组）
    :param templates: load_all_templates() 返回的模板字典
    :param match_threshold: 置信度阈值，建议 0.70~0.80
    :return: 识别到的节点列表（已做 NMS 去重 + 层次分配）

    实现状态：TODO (Phase 1)
    """
    all_matches: list[RawMatch] = []

    for node_type, tmpl_list in templates.items():
        for tmpl in tmpl_list:
            th, tw = tmpl.shape[:2]
            for scale in MATCH_SCALES:
                scaled_w = int(tw * scale)
                scaled_h = int(th * scale)
                if scaled_w > screenshot_gray.shape[1] or scaled_h > screenshot_gray.shape[0]:
                    continue
                scaled_tmpl = cv2.resize(tmpl, (scaled_w, scaled_h))
                result = cv2.matchTemplate(screenshot_gray, scaled_tmpl, cv2.TM_CCOEFF_NORMED)
                locs = np.where(result >= match_threshold)
                for pt in zip(*locs[::-1]):  # (x, y)
                    all_matches.append(RawMatch(
                        node_type=node_type,
                        position=(int(pt[0]), int(pt[1])),
                        score=float(result[pt[1], pt[0]]),
                        scale=scale,
                    ))

    # 按类型分组做 NMS
    nodes: list[MapNode] = []
    node_id = 0

    type_groups: dict[NodeType, list[RawMatch]] = {}
    for m in all_matches:
        type_groups.setdefault(m.node_type, []).append(m)

    for node_type, group in type_groups.items():
        tmpl = templates[node_type][0]
        th, tw = tmpl.shape[:2]
        kept = _nms(group, (tw, th))
        for m in kept:
            center_x = m.position[0] + int(tw * m.scale / 2)
            center_y = m.position[1] + int(th * m.scale / 2)
            nodes.append(MapNode(
                node_id=node_id,
                node_type=node_type,
                position=(center_x, center_y),
                confidence=m.score,
            ))
            node_id += 1

    nodes = _deduplicate_spatial_nodes(nodes)
    nodes = _assign_layers(nodes)
    reindexed_nodes, _ = _reindex_nodes(nodes)
    return reindexed_nodes


def recognize_map(
    screenshot: Image.Image,
    templates_dir: str,
    match_threshold: float = MATCH_THRESHOLD,
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """
    从游戏地图截图识别所有节点和连接边（单张截图版）。

    适用于已有截图或快速测试，不涉及滚动逻辑。
    节点的 position / screen_pos 均为截图内的坐标（等同），scroll_step=0。

    :param screenshot:      游戏地图截图（PIL Image）
    :param templates_dir:   节点模板目录路径
    :param match_threshold: 匹配置信度阈值
    :return: (nodes, edges)

    使用示例：
        from core.screen import capture_screen
        from features.route_planner import recognize_map

        screenshot = capture_screen()
        nodes, edges = recognize_map(screenshot, "assets/node_templates")
    """
    screenshot_gray = np.array(screenshot.convert("L"))
    templates = load_all_templates(templates_dir)

    if not templates:
        print("⚠ 未找到节点模板，请先将模板图片放入 assets/node_templates/ 目录")
        return [], []

    nodes = detect_nodes(screenshot_gray, templates, match_threshold)
    # 单张截图时，screen_pos 与 position 相同
    for node in nodes:
        node.screen_pos = node.position

    edges = _detect_edges_by_lines(nodes, screenshot_gray)
    nodes, edges = _refine_detected_map(nodes, edges)

    print(f"🗺  识别完成：{len(nodes)} 个节点，{len(edges)} 条边")
    return nodes, edges


# ── 滚动采集与全图拼接 ────────────────────────────────────────

@dataclass
class _ScrollFrame:
    """单次滚动截图帧的内部记录"""
    screenshot: Image.Image
    scroll_step: int
    y_offset: int = 0   # 此帧在拼接画布中的 Y 起始坐标（拼接后填充）


def _detect_frame_overlap(
    frame_lower_gray: np.ndarray,
    frame_upper_gray: np.ndarray,
) -> int:
    """
    检测两相邻滚动截图帧的像素重叠高度。

    当向上滚动时，上方帧（frame_upper）的底部与下方帧（frame_lower）的顶部内容相同：
      - 取 frame_lower 顶部 30% 作为模板
      - 在 frame_upper 底部 60% 区域搜索
      - 匹配位置决定重叠像素数

    :param frame_lower_gray: scroll_step=i 的灰度截图（较低的地图位置）
    :param frame_upper_gray: scroll_step=i+1 的灰度截图（较高的地图位置）
    :return: 重叠像素高度
    """
    H = frame_lower_gray.shape[0]
    tmpl_h = max(50, int(H * 0.30))
    template = frame_lower_gray[:tmpl_h, :]

    search_start = int(H * 0.40)
    search_region = frame_upper_gray[search_start:, :]

    if template.shape[0] >= search_region.shape[0] or template.shape[1] > search_region.shape[1]:
        return H // 2  # 无法匹配时回退为估算值

    result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
    max_val: float
    max_loc: tuple[int, int]
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < 0.50:
        return H // 2  # 匹配质量差，使用默认估算

    # max_loc[1] 是模板在 search_region 中的 Y 位置
    # 模板对应 frame_upper 的绝对 Y = search_start + max_loc[1]
    match_y_in_upper = search_start + max_loc[1]
    overlap = H - match_y_in_upper
    return max(10, min(overlap, H - 10))


def stitch_screenshots(
    frames: list[Image.Image],
) -> tuple[Image.Image, list[int]]:
    """
    将多张滚动截图拼接为完整地图图像。

    frames[0] 对应 scroll_step=0（最底部，起点可见）；
    frames[-1] 对应最顶部（Boss 可见）。
    拼接后画布 Y=0 为地图顶部（Boss 侧），Y 最大处为地图底部（起点侧）。

    :param frames: 按滚动步骤从底到顶排列的截图列表
    :return: (stitched_image, y_offsets)
             y_offsets[i] = 帧 i 在拼接画布中的 Y 起始坐标
    """
    if len(frames) == 1:
        return frames[0].copy(), [0]

    grays = [np.array(f.convert("L")) for f in frames]
    H, W = grays[0].shape[:2]

    # 计算相邻帧间步长（= 帧高 - 重叠像素）
    step_sizes: list[int] = []
    for i in range(len(frames) - 1):
        overlap = _detect_frame_overlap(grays[i], grays[i + 1])
        step_sizes.append(max(1, H - overlap))

    total_height = H + sum(step_sizes)

    # frame[0] 贴在画布底部，frame[-1] 贴在画布顶部
    y_offsets: list[int] = [0] * len(frames)
    y_offsets[0] = total_height - H
    for i in range(1, len(frames)):
        y_offsets[i] = y_offsets[i - 1] - step_sizes[i - 1]

    canvas = Image.new("RGB", (W, total_height), (0, 0, 0))
    for i, frame in enumerate(frames):
        y = y_offsets[i]
        if 0 <= y < total_height:
            canvas.paste(frame, (0, y))
        elif y < 0:
            # 仅粘贴画布范围内的部分（上方帧可能超出顶边）
            crop_top = -y
            canvas.paste(frame.crop((0, crop_top, W, H)), (0, 0))

    return canvas, y_offsets


def stitch_with_step_sizes(
    frames: list[Image.Image],
    step_sizes: list[int],
) -> tuple[Image.Image, list[int]]:
    """
    使用预计算步长拼接截图，无需重新检测重叠区域。

    配合 capture_scrolled_map_anchor 使用：锚点式采集已精确记录每帧
    贡献的新像素高度（step_size），直接用于拼接，避免重叠检测误差。

    :param frames:     按滚动顺序（底→顶）排列的截图列表
    :param step_sizes: step_sizes[i] = frames[i+1] 贡献的新像素高度
    :return: (stitched_image, y_offsets)
             y_offsets[i] = 帧 i 在拼接画布中的 Y 起始坐标
    """
    if not frames:
        raise ValueError("frames is empty")
    if len(frames) == 1:
        return frames[0].copy(), [0]
    if len(step_sizes) != len(frames) - 1:
        raise ValueError(
            f"step_sizes 长度不匹配: {len(step_sizes)} vs {len(frames) - 1}"
        )

    W, H = frames[0].width, frames[0].height
    clamped = [max(1, min(s, H - 10)) for s in step_sizes]
    total_height = H + sum(clamped)

    y_offsets: list[int] = [0] * len(frames)
    y_offsets[0] = total_height - H
    for i in range(1, len(frames)):
        y_offsets[i] = y_offsets[i - 1] - clamped[i - 1]

    canvas = Image.new("RGB", (W, total_height), (0, 0, 0))
    for i, frame in enumerate(frames):
        y = y_offsets[i]
        if y >= 0:
            canvas.paste(frame, (0, y))
        else:
            crop_top = -y
            canvas.paste(frame.crop((0, crop_top, W, H)), (0, 0))

    return canvas, y_offsets


def recognize_full_map_scrolled(
    map_region: tuple[int, int, int, int],
    templates_dir: str,
    num_scroll_steps: int = 6,
    scroll_clicks_per_step: int = 5,
    match_threshold: float = MATCH_THRESHOLD,
) -> tuple[list[MapNode], list[tuple[int, int]], Image.Image]:
    """
    全图滚动采集 + 拼接 + 识别一体化接口。

    流程：
      1. 调用 core.screen.scroll_to_map_bottom 滚到底部（起点可见）
      2. 逐步向上滚动，每步截图，共 num_scroll_steps 张
      3. stitch_screenshots 拼接为完整地图图像
      4. 在拼接图上做模板匹配，得到拼接坐标系下的节点
      5. 将拼接坐标映射回各帧的原始屏幕坐标，附带 scroll_step

    :param map_region:           地图区域 (x, y, w, h)
    :param templates_dir:        节点模板目录
    :param num_scroll_steps:     截图步数（含初始帧）
    :param scroll_clicks_per_step: 每步向上滚动的滚轮格数
    :param match_threshold:      模板匹配阈值
    :return: (nodes, edges, stitched_image)
             nodes[i].position   = 拼接画布坐标（用于分层、路径分析）
             nodes[i].screen_pos = 对应帧的原始屏幕坐标（用于点击）
             nodes[i].scroll_step = 应先滚到此步骤才能看到该节点
    """
    # 延迟导入避免循环依赖
    from core.screen import scroll_to_map_bottom, capture_scrolled_map

    rx, ry, rw, rh = map_region
    map_center = (rx + rw // 2, ry + rh // 2)

    # 1. 滚到底部
    scroll_to_map_bottom(map_center[0], map_center[1])

    # 2. 逐步截图（自适应滚动）
    raw_frames, _scroll_plan = capture_scrolled_map(
        region=map_region,
        map_center=map_center,
        initial_scroll_clicks=scroll_clicks_per_step,
    )

    screenshots = [img for img, _ in raw_frames]

    # 3. 拼接
    stitched, y_offsets = stitch_screenshots(screenshots)

    templates = load_all_templates(templates_dir)
    if not templates:
        print("⚠ 未找到节点模板，请先将模板图片放入 assets/node_templates/ 目录")
        return [], [], stitched

    # 4. 在拼接图上识别节点
    stitched_gray = np.array(stitched.convert("L"))
    nodes = detect_nodes(stitched_gray, templates, match_threshold)

    frame_h = screenshots[0].height

    # 5. 将拼接坐标映射回屏幕坐标 + scroll_step
    for node in nodes:
        canvas_x, canvas_y = node.position
        # 找到该节点属于哪一帧（y_offset[i] <= canvas_y < y_offset[i] + frame_h）
        best_step = 0
        min_dist = float("inf")
        for step, y_off in enumerate(y_offsets):
            # 节点相对于该帧顶部的偏移
            local_y = canvas_y - y_off
            if 0 <= local_y < frame_h:
                dist = abs(local_y - frame_h // 2)  # 优先选节点在帧中间的帧
                if dist < min_dist:
                    min_dist = dist
                    best_step = step

        node.scroll_step = best_step
        # 原始屏幕坐标 = 区域偏移 + 节点在对应帧内的局部坐标
        local_y_in_frame = canvas_y - y_offsets[best_step]
        node.screen_pos = (
            rx + canvas_x,
            ry + local_y_in_frame,
        )

    edges = _detect_edges_by_lines(nodes, stitched_gray)
    nodes, edges = _refine_detected_map(nodes, edges)

    print(f"🗺  全图识别完成：{len(nodes)} 个节点，{len(edges)} 条边（{num_scroll_steps} 帧拼接）")
    return nodes, edges, stitched
