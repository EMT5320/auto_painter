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
    MONSTER  = "monster"   # 普通敌人
    ELITE    = "elite"     # 精英
    REST     = "rest"      # 休息/营火
    MERCHANT = "merchant"  # 商人
    UNKNOWN  = "unknown"   # 未知/问号
    TREASURE = "treasure"  # 宝箱
    BOSS     = "boss"      # Boss（终点）

    @property
    def display_name(self) -> str:
        _names = {
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
    position:  tuple[int, int]   # 节点中心的屏幕坐标
    layer:     int = 0           # 所在层数（0 = 最底层起点）
    confidence: float = 1.0      # 识别置信度


# ── 常量 ──────────────────────────────────────────────────────

MATCH_THRESHOLD = 0.75          # 模板匹配置信度阈值
MATCH_SCALES    = [0.8, 0.9, 1.0, 1.1, 1.2]  # 多尺度匹配系数
NMS_IOU_THRESHOLD = 0.4         # NMS 重叠阈值（IoU）


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
    使用简单的 Y 坐标分组：相邻 Y 差值 < 阈值视为同层。
    """
    if not nodes:
        return nodes

    # 按 Y 坐标升序（越小越靠上 = 越接近Boss）
    sorted_nodes = sorted(nodes, key=lambda n: n.position[1])
    y_threshold = 60  # 同层节点的 Y 坐标最大差值（像素）

    layer_idx = 0
    prev_y = sorted_nodes[0].position[1]

    for node in sorted_nodes:
        if abs(node.position[1] - prev_y) > y_threshold:
            layer_idx += 1
            prev_y = node.position[1]
        node.layer = layer_idx

    # 翻转：最底层（Y最大）= 层0（起点），层号越大越靠近Boss
    max_layer = max(n.layer for n in nodes)
    for node in nodes:
        node.layer = max_layer - node.layer

    return nodes


# ── 边检测 ────────────────────────────────────────────────────

def _detect_edges_by_proximity(
    nodes: list[MapNode],
    screenshot_gray: np.ndarray,
) -> list[tuple[int, int]]:
    """
    通过节点间距离和层次关系推断连接边。

    策略：
      1. 相邻层（layer_i → layer_i+1）的节点，若两者之间存在路径像素则认为相连
      2. 对于连线检测：在两节点连线上采样像素，判断是否有路径色（灰色虚线）

    TODO (Phase 1): 目前返回空列表，待实现完整的虚线检测逻辑
    """
    # Phase 1 占位：仅返回同层相邻节点的推断连接（基于 Y 层次 + 位置）
    edges: list[tuple[int, int]] = []
    # 实现思路（待完成）：
    # 1. 对截图做形态学膨胀，将虚线补全为实线
    # 2. 在相邻层的节点对坐标之间，沿直线采样像素亮度
    # 3. 若平均亮度 > 阈值，则视为相连
    return edges


# ── 公开接口 ──────────────────────────────────────────────────

def load_all_templates(templates_dir: str) -> dict[NodeType, list[np.ndarray]]:
    """
    从模板目录加载所有节点类型的模板图片。

    目录结构：
        templates_dir/
            monster/  *.png
            elite/    *.png
            rest/     *.png
            ...
    """
    result: dict[NodeType, list[np.ndarray]] = {}
    for node_type in NodeType:
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

    return _assign_layers(nodes)


def recognize_map(
    screenshot: Image.Image,
    templates_dir: str,
    match_threshold: float = MATCH_THRESHOLD,
) -> tuple[list[MapNode], list[tuple[int, int]]]:
    """
    从游戏地图截图识别所有节点和连接边。

    :param screenshot:      游戏地图截图（PIL Image）
    :param templates_dir:   节点模板目录路径
    :param match_threshold: 匹配置信度阈值
    :return: (nodes, edges)
             nodes: 识别到的节点列表
             edges: 边列表，每项为 (from_node_id, to_node_id)

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
    edges = _detect_edges_by_proximity(nodes, screenshot_gray)

    print(f"🗺  识别完成：{len(nodes)} 个节点，{len(edges)} 条边")
    return nodes, edges
