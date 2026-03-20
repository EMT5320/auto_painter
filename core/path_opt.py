"""
core/path_opt.py
路径优化模块
对多段轮廓进行点稀疏化与路径排序，减少抬笔移动距离

迁移自根目录 path_optimizer.py
"""

import numpy as np

OPTIMIZE_ALGORITHMS = {
    "legacy": "经典最近邻",
    "quality": "增强路径优化",
}


def _contour_endpoints(contour):
    """获取轮廓的起点和终点"""
    return contour[0], contour[-1]


def _dist(p1, p2):
    """两点距离"""
    return np.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _stroke_length(stroke: list) -> float:
    """计算单段笔画总长度"""
    if len(stroke) < 2:
        return 0.0
    return float(sum(_dist(stroke[i - 1], stroke[i]) for i in range(1, len(stroke))))


def _estimate_start_point(contours: list) -> tuple[float, float]:
    """估计起笔点：使用全部端点均值，减小首次长距离跳笔概率"""
    points = []
    for contour in contours:
        if len(contour) >= 2:
            points.extend([contour[0], contour[-1]])
    if not points:
        return 0.0, 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return float(np.mean(xs)), float(np.mean(ys))


def _pick_nearest_to_point(contours: list, point: tuple[float, float]):
    """找到距离 point 最近的轮廓端点，返回(索引, 是否反转, 距离)"""
    best_idx = 0
    best_dist = float("inf")
    best_reversed = False

    for idx, c in enumerate(contours):
        start, end = _contour_endpoints(c)
        d_start = _dist(point, start)
        d_end = _dist(point, end)

        if d_start < best_dist:
            best_dist = d_start
            best_idx = idx
            best_reversed = False

        if d_end < best_dist:
            best_dist = d_end
            best_idx = idx
            best_reversed = True

    return best_idx, best_reversed, best_dist


def nearest_neighbor_sort(contours: list, start_point=None) -> list:
    """
    贪心最近邻算法：对多段轮廓排序
    每次从当前笔尾找最近的下一段轮廓起点（或终点，支持反转）
    返回排序后的轮廓列表
    """
    if not contours:
        return []

    remaining = list(contours)
    sorted_strokes = []

    if start_point is None:
        current = remaining.pop(0)
    else:
        idx, need_reverse, _ = _pick_nearest_to_point(remaining, start_point)
        current = remaining.pop(idx)
        if need_reverse:
            current = current[::-1]

    sorted_strokes.append(current)
    current_end = current[-1]

    while remaining:
        best_idx, best_reversed, _ = _pick_nearest_to_point(remaining, current_end)

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


def _prepare_strokes(raw_contours: list, min_dist: float) -> list:
    """通用预处理：点稀疏化 + 空笔画过滤"""
    thinned = [thin_points(c, min_dist) for c in raw_contours if len(c) > 1]
    return [c for c in thinned if len(c) >= 2]


def _lookahead_sort(contours: list,
                    start_point=None,
                    lookahead_weight: float = 0.35,
                    candidate_pool: int = 12) -> list:
    """
    轻量级前瞻排序：
    在“当前最近”的候选里，额外考虑下一跳代价，减少局部贪心导致的飞线。
    """
    if not contours:
        return []

    remaining = list(contours)
    sorted_strokes = []
    start = _estimate_start_point(remaining) if start_point is None else start_point

    first_idx, first_reverse, _ = _pick_nearest_to_point(remaining, start)
    current = remaining.pop(first_idx)
    if first_reverse:
        current = current[::-1]
    sorted_strokes.append(current)
    current_end = current[-1]

    while remaining:
        # 先按当前距离粗排，仅评估前 candidate_pool 个候选，控制复杂度
        coarse = []
        for idx, contour in enumerate(remaining):
            start_pt, end_pt = _contour_endpoints(contour)
            d_start = _dist(current_end, start_pt)
            d_end = _dist(current_end, end_pt)
            if d_start <= d_end:
                coarse.append((d_start, idx, False))
            else:
                coarse.append((d_end, idx, True))
        coarse.sort(key=lambda x: x[0])
        candidates = coarse[: max(1, min(candidate_pool, len(coarse)))]

        best_score = float("inf")
        best_choice = candidates[0]

        for base_dist, idx, need_reverse in candidates:
            chosen = remaining[idx]
            end_after = chosen[0] if need_reverse else chosen[-1]

            # 评估下一跳代价（如果还有下一段）
            if len(remaining) > 1:
                next_best = float("inf")
                for j, other in enumerate(remaining):
                    if j == idx:
                        continue
                    s2, e2 = _contour_endpoints(other)
                    next_best = min(next_best, _dist(end_after, s2), _dist(end_after, e2))
            else:
                next_best = 0.0

            # 对较长轮廓给一点优先权，减少碎线主导排序
            length_bonus = min(_stroke_length(chosen) * 0.02, 4.0)
            score = base_dist + lookahead_weight * next_best - length_bonus

            if score < best_score:
                best_score = score
                best_choice = (base_dist, idx, need_reverse)

        _, best_idx, best_reversed = best_choice
        chosen = remaining.pop(best_idx)
        if best_reversed:
            chosen = chosen[::-1]

        sorted_strokes.append(chosen)
        current_end = chosen[-1]

    return sorted_strokes


def _quality_sort(contours: list, min_dist: float) -> list:
    """
    增强算法：
    1. 过滤过短噪点笔画
    2. 前瞻式排序降低跳笔
    """
    if not contours:
        return []

    # AI 素描通常会出现大量碎线，这里做轻度过滤；若全被过滤则回退原数据
    min_stroke_len = max(2.5, min_dist * 2.5)
    filtered = [c for c in contours if _stroke_length(c) >= min_stroke_len]
    active = filtered if filtered else contours

    # 超大规模场景回退经典策略，避免前瞻排序过慢
    if len(active) > 1200:
        return nearest_neighbor_sort(active, start_point=_estimate_start_point(active))

    return _lookahead_sort(active, start_point=_estimate_start_point(active))


def get_stroke_stats(strokes: list) -> dict:
    """计算路径统计信息，便于算法对比。"""
    if not strokes:
        return {
            "stroke_count": 0,
            "point_count": 0,
            "draw_distance": 0.0,
            "lift_distance": 0.0,
            "total_distance": 0.0,
        }

    stroke_count = len(strokes)
    point_count = sum(len(s) for s in strokes)
    draw_distance = float(sum(_stroke_length(s) for s in strokes))

    lift_distance = 0.0
    for i in range(1, len(strokes)):
        prev_end = strokes[i - 1][-1]
        cur_start = strokes[i][0]
        lift_distance += _dist(prev_end, cur_start)

    return {
        "stroke_count": stroke_count,
        "point_count": point_count,
        "draw_distance": draw_distance,
        "lift_distance": float(lift_distance),
        "total_distance": draw_distance + float(lift_distance),
    }


def format_stroke_stats(stats: dict) -> str:
    """将路径统计格式化为一行日志文本。"""
    return (
        f"笔画 {stats['stroke_count']} 段 / 点 {stats['point_count']} 个 / "
        f"落笔 {stats['draw_distance']:.0f}px / 抬笔 {stats['lift_distance']:.0f}px / "
        f"总路径 {stats['total_distance']:.0f}px"
    )


def optimize_strokes(raw_contours: list,
                     min_dist: float = 2.0,
                     algorithm: str = "legacy") -> list:
    """
    完整优化流程：
    1. 稀疏化每段轮廓点
    2. 根据 algorithm 进行路径排序

    :param raw_contours: 原始轮廓路径
    :param min_dist: 点稀疏化距离阈值
    :param algorithm: "legacy" 或 "quality"
    """
    algo = (algorithm or "legacy").lower().strip()
    if algo not in OPTIMIZE_ALGORITHMS:
        supported = ", ".join(sorted(OPTIMIZE_ALGORITHMS.keys()))
        raise ValueError(f"未知优化算法: {algorithm}，可选: {supported}")

    thinned = _prepare_strokes(raw_contours, min_dist=min_dist)
    if algo == "legacy":
        return nearest_neighbor_sort(thinned)
    if algo == "quality":
        return _quality_sort(thinned, min_dist=min_dist)

    # 理论不可达，保留防御式回退
    return nearest_neighbor_sort(thinned)
