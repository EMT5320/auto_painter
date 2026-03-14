"""
features/route_planner/drawer.py
路线绘制模块

职责：
  将推荐路线的节点坐标转换为鼠标绘制指令，
  调用 core.mouse 在游戏地图上画出路线标记。

绘制方案：
  1. 连接线：在相邻节点之间绘制直线
  2. 节点标记：在每个选中节点处画小圆圈（通过多段圆弧模拟）

实现状态：骨架（Phase 3 待实现）
"""

from __future__ import annotations

import math
import threading

import numpy as np

from core.mouse import draw_strokes
from .graph import MapGraph


# ── 圆弧点生成 ────────────────────────────────────────────────

def _circle_points(cx: int, cy: int, radius: int, steps: int = 24) -> list[tuple[int, int]]:
    """生成圆圈的离散点序列"""
    pts = []
    for i in range(steps + 1):
        angle = 2 * math.pi * i / steps
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        pts.append((x, y))
    return pts


def _line_points(p1: tuple[int, int], p2: tuple[int, int], spacing: int = 8) -> list[tuple[int, int]]:
    """在两点之间按间距生成中间点序列"""
    x1, y1 = p1
    x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    n = max(int(dist / spacing), 2)
    xs = np.linspace(x1, x2, n, dtype=int)
    ys = np.linspace(y1, y2, n, dtype=int)
    return list(zip(xs.tolist(), ys.tolist()))


# ── 公开接口 ──────────────────────────────────────────────────

def route_to_strokes(
    route: list[int],
    graph: MapGraph,
    node_circle_radius: int = 20,
) -> list[list[tuple[int, int]]]:
    """
    将路线转换为可供 draw_strokes 执行的笔画列表。

    每段笔画为连续点序列（按住鼠标键绘制）：
      - 连接线：相邻节点之间的直线段
      - 节点圆圈：每个路线节点位置的圆圈标记

    :param route:  节点 ID 序列
    :param graph:  MapGraph（提供节点坐标）
    :param node_circle_radius: 节点圆圈半径（像素）
    :return: 笔画列表
    """
    strokes: list[list[tuple[int, int]]] = []

    # 连接线
    for i in range(len(route) - 1):
        n1 = graph.nodes.get(route[i])
        n2 = graph.nodes.get(route[i + 1])
        if n1 and n2:
            strokes.append(_line_points(n1.position, n2.position))

    # 节点圆圈标记（排除起点和终点）
    for nid in route:
        node = graph.nodes.get(nid)
        if node:
            strokes.append(_circle_points(
                node.position[0], node.position[1], node_circle_radius
            ))

    return strokes


def draw_route_on_screen(
    route: list[int],
    graph: MapGraph,
    draw_speed: float = 0.0004,
    button: str = "right",
    node_circle_radius: int = 20,
    stop_event: threading.Event | None = None,
) -> None:
    """
    将选定路线通过鼠标绘制到游戏地图上。

    调用流程：
      1. 将路线转换为笔画序列（route_to_strokes）
      2. 调用 core.mouse.draw_strokes 执行绘制

    :param route:              节点 ID 序列（来自 optimizer.rank_routes）
    :param graph:              MapGraph
    :param draw_speed:         绘制速度（每步停留秒数）
    :param button:             鼠标按键（'right' 或 'left'）
    :param node_circle_radius: 节点标记圆圈半径
    :param stop_event:         中断事件（threading.Event）

    TODO (Phase 3):
      - 当前实现为骨架，待集成倒计时和进度回调
      - 需要测试在不同游戏分辨率下的坐标准确性
      - 考虑添加"箭头"或"起点三角"标记
    """
    if not route:
        print("⚠ 路线为空，无需绘制")
        return

    strokes = route_to_strokes(route, graph, node_circle_radius)

    if not strokes:
        print("⚠ 无法生成笔画，请检查路线节点坐标")
        return

    print(f"🗺  开始绘制路线：{len(route)} 个节点，{len(strokes)} 段笔画")
    draw_strokes(
        strokes,
        move_speed=draw_speed,
        button=button,
        stop_event=stop_event,
    )
