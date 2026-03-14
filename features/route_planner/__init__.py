"""
features/route_planner/__init__.py
路线规划功能模块

公开接口：
  - NodeType        : 节点类型枚举
  - MapNode         : 单个地图节点
  - MapGraph        : 地图图结构
  - RoutePreferences: 用户路线偏好
  - recognize_map   : 从截图识别地图
  - build_map_graph : 构建图结构
  - rank_routes     : 路线评分排序
  - draw_route_on_screen: 在游戏内绘制路线
"""

from .recognizer import NodeType, MapNode, recognize_map
from .graph import MapGraph, build_map_graph, find_all_routes
from .optimizer import RoutePreferences, rank_routes
from .drawer import draw_route_on_screen

__all__ = [
    "NodeType", "MapNode", "recognize_map",
    "MapGraph", "build_map_graph", "find_all_routes",
    "RoutePreferences", "rank_routes",
    "draw_route_on_screen",
]
