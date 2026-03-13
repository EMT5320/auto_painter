"""
path_optimizer.py
路径优化模块
对多段轮廓进行最近邻排序，减少抬笔移动距离
"""

import numpy as np


def _contour_endpoints(contour):
    """获取轮廓的起点和终点"""
    return contour[0], contour[-1]


def _dist(p1, p2):
    """两点距离"""
    return np.hypot(p1[0] - p2[0], p1[1] - p2[1])


def nearest_neighbor_sort(contours: list) -> list:
    """
    贪心最近邻算法：对多段轮廓排序
    每次从当前笔尾找最近的下一段轮廓起点（或终点，支持反转）
    返回排序后的轮廓列表
    """
    if not contours:
        return []

    remaining = list(contours)
    sorted_strokes = []

    # 从第一段开始
    current = remaining.pop(0)
    sorted_strokes.append(current)
    current_end = current[-1]

    while remaining:
        best_idx = 0
        best_dist = float('inf')
        best_reversed = False

        for idx, c in enumerate(remaining):
            start, end = _contour_endpoints(c)
            d_start = _dist(current_end, start)
            d_end = _dist(current_end, end)

            if d_start < best_dist:
                best_dist = d_start
                best_idx = idx
                best_reversed = False

            if d_end < best_dist:
                best_dist = d_end
                best_idx = idx
                best_reversed = True

        chosen = remaining.pop(best_idx)
        if best_reversed:
            chosen = chosen[::-1]

        sorted_strokes.append(chosen)
        current_end = chosen[-1]

    return sorted_strokes


def thin_points(contour: list, min_distance: float = 2.0) -> list:
    """
    对轮廓点进行稀疏化：相邻点距离小于 min_distance 时跳过
    减少不必要的密集点，提高绘制速度
    """
    if not contour:
        return contour

    result = [contour[0]]
    for pt in contour[1:]:
        if _dist(result[-1], pt) >= min_distance:
            result.append(pt)

    return result


def optimize_strokes(raw_contours: list, min_dist: float = 2.0) -> list:
    """
    完整优化流程：
    1. 稀疏化每段轮廓点
    2. 最近邻排序减少抬笔
    """
    # 稀疏化
    thinned = [thin_points(c, min_dist) for c in raw_contours if len(c) > 1]

    # 过滤太短的（只有1个点）
    thinned = [c for c in thinned if len(c) >= 2]

    # 最近邻排序
    sorted_strokes = nearest_neighbor_sort(thinned)

    return sorted_strokes
