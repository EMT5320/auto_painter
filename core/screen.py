"""
core/screen.py
屏幕捕获与区域管理工具
"""

from __future__ import annotations

import time

import cv2
import pyautogui
import numpy as np
from PIL import Image


def get_screen_size() -> tuple[int, int]:
    """返回 (width, height)"""
    return pyautogui.size()


def capture_screen() -> Image.Image:
    """捕获当前全屏截图"""
    return pyautogui.screenshot()


def capture_region(x: int, y: int, w: int, h: int) -> Image.Image:
    """捕获指定屏幕区域的截图"""
    return pyautogui.screenshot(region=(x, y, w, h))


def pil_to_gray_array(img: Image.Image) -> np.ndarray:
    """将 PIL Image 转换为灰度 numpy 数组"""
    return np.array(img.convert("L"))


def get_canvas_offset(ratio: float = 0.8) -> tuple[int, int, int, int]:
    """
    根据屏幕大小和画布比例，计算以屏幕中心为基准的画布区域。
    :return: (canvas_w, canvas_h, offset_x, offset_y)
             offset = 画布左上角的屏幕坐标
    """
    screen_w, screen_h = pyautogui.size()
    canvas_w = int(screen_w * ratio)
    canvas_h = int(screen_h * ratio)
    offset_x = (screen_w - canvas_w) // 2
    offset_y = (screen_h - canvas_h) // 2
    return canvas_w, canvas_h, offset_x, offset_y


# ── 地图滚动工具 ──────────────────────────────────────────────

def scroll_map(clicks: int, x: int, y: int) -> None:
    """
    在指定坐标滚动鼠标滚轮。

    :param clicks: 正数向上滚动（地图朝 Boss 方向移动），负数向下
    :param x, y:   鼠标放置坐标（应在地图区域内）
    """
    pyautogui.moveTo(x, y, duration=0.1)
    pyautogui.scroll(clicks, x=x, y=y)


def scroll_to_map_bottom(cx: int, cy: int, max_scrolls: int = 60) -> None:
    """
    将地图滚动到最底部（起点可见）。

    STS2 地图约 3-4 屏高，需要大量向下滚动。
    每次向下滚动 20 格，共最多 max_scrolls 次。

    :param cx, cy:     鼠标停放坐标（地图区域中心）
    :param max_scrolls: 最大滚动次数，应足以到达地图底部
    """
    pyautogui.moveTo(cx, cy, duration=0.2)
    for _ in range(max_scrolls):
        pyautogui.scroll(-20, x=cx, y=cy)
        time.sleep(0.02)
    time.sleep(0.6)  # 等待地图停止惯性滚动


def _adjust_scroll_clicks(
    similarity: float,
    current_clicks: int,
    grow_streak: int,
    shrink_streak: int,
) -> tuple[int, int, int, str | None]:
    """
    根据帧相似度分段调整滚轮量。

    设计目标：
      - 相似度持续偏高：说明滚动太少，使用逐步放大的乘数快速加速
      - 相似度持续偏低：说明滚动太猛，使用逐步放大的缩小系数快速回收
      - 进入合理区间后重置 streak，避免来回振荡
    """
    min_clicks = 8
    max_clicks = 180

    if similarity >= 0.88:
        grow_streak += 1
        shrink_streak = 0
        factor = 1.35 + 0.30 * min(grow_streak, 4)
        next_clicks = min(int(current_clicks * factor), max_clicks)
        return next_clicks, grow_streak, shrink_streak, "滚动偏少，继续放大"

    if similarity >= 0.78:
        grow_streak += 1
        shrink_streak = 0
        factor = 1.15 + 0.15 * min(grow_streak, 3)
        next_clicks = min(int(current_clicks * factor), max_clicks)
        return next_clicks, grow_streak, shrink_streak, "滚动略少，小幅放大"

    if similarity <= 0.18:
        shrink_streak += 1
        grow_streak = 0
        factor = max(0.30, 0.72 - 0.12 * min(shrink_streak, 3))
        next_clicks = max(int(current_clicks * factor), min_clicks)
        return next_clicks, grow_streak, shrink_streak, "滚动过多，快速回收"

    if similarity <= 0.30:
        shrink_streak += 1
        grow_streak = 0
        factor = max(0.45, 0.85 - 0.10 * min(shrink_streak, 3))
        next_clicks = max(int(current_clicks * factor), min_clicks)
        return next_clicks, grow_streak, shrink_streak, "滚动略多，小幅回收"

    return current_clicks, 0, 0, None


def _frame_similarity(gray_a: np.ndarray, gray_b: np.ndarray) -> float:
    """
    计算两张灰度截图的相似度 [0.0, 1.0]。

    使用归一化绝对差值：1.0 = 完全相同，0.0 = 完全不同。
    为了加速，只采样图像中间 60% 区域（排除 HUD/边框干扰）。
    """
    h, w = gray_a.shape[:2]
    # 裁剪中间 60% 区域
    y1, y2 = int(h * 0.2), int(h * 0.8)
    x1, x2 = int(w * 0.2), int(w * 0.8)
    crop_a = gray_a[y1:y2, x1:x2].astype(np.float32)
    crop_b = gray_b[y1:y2, x1:x2].astype(np.float32)
    diff = np.mean(np.abs(crop_a - crop_b))
    # diff=0 → 完全相同(1.0)，diff=255 → 完全不同(0.0)
    return max(0.0, 1.0 - diff / 128.0)


def capture_scrolled_map(
    region: tuple[int, int, int, int],
    map_center: tuple[int, int],
    initial_scroll_clicks: int = 48,
    max_frames: int | None = None,
    step_delay: float = 0.4,
    log_fn=None,
) -> tuple[list[tuple[Image.Image, int]], list[int]]:
    """
    自适应滚动截图：从地图底部逐步向上滚动，自动调整滚动量，到顶自动停止。

    调用前应确保镜头已在地图底部（先调用 scroll_to_map_bottom）。

        自适应策略：
            - 相似度持续偏高（例如 0.9+）：认为滚动太少，滚轮量按 streak 逐步放大
            - 相似度持续偏低：认为滚动太多，滚轮量按 streak 逐步回收
            - 不再要求用户设置固定步数，直到确认到顶才停止
            - 连续多次“高相似 + 激进滚动”无变化，判定已到 Boss 顶部

    :param region:                截图区域 (x, y, w, h)
    :param map_center:            鼠标停放坐标 (cx, cy)
    :param initial_scroll_clicks: 初始每步滚轮格数
    :param max_frames:            最大截图帧数（可选；默认内部安全上限 80，仅防死循环）
    :param step_delay:            每步滚动后等待时间（秒）
    :param log_fn:                日志回调函数（可选）
    :return: (frames, scroll_plan)
             frames: [(screenshot, scroll_step), ...]
             scroll_step=0 为最底部（起点可见），递增表示向上滚动
             scroll_plan[i] = 从第 i 帧滚到第 i+1 帧时实际使用的滚轮格数
    """
    cx, cy = map_center
    frames: list[tuple[Image.Image, int]] = []
    scroll_plan: list[int] = []
    scroll_clicks = initial_scroll_clicks
    prev_gray: np.ndarray | None = None
    grow_streak = 0
    shrink_streak = 0
    top_stall_count = 0
    hard_safety_frames = max_frames or 80

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    for step in range(hard_safety_frames):
        img = capture_region(*region)
        curr_gray = np.array(img.convert("L"))

        if prev_gray is not None:
            sim = _frame_similarity(prev_gray, curr_gray)
            _log(f"   帧 {step}: 相似度 {sim:.3f}, 滚轮={scroll_clicks}")

            if sim >= 0.985 and scroll_clicks >= 120:
                top_stall_count += 1
                _log(f"   → 激进滚动下仍几乎不变，顶部计数 {top_stall_count}/3")
                if top_stall_count >= 3:
                    _log("   已连续多次激进滚动仍无变化，判定到达 Boss 顶部")
                    break
            else:
                top_stall_count = 0

            next_clicks, grow_streak, shrink_streak, reason = _adjust_scroll_clicks(
                sim,
                scroll_clicks,
                grow_streak,
                shrink_streak,
            )
            if reason and next_clicks != scroll_clicks:
                _log(f"   → {reason}，滚轮 {scroll_clicks} -> {next_clicks}")
            scroll_clicks = next_clicks
        else:
            _log(f"   帧 {step}: 初始截图, 滚轮={scroll_clicks}")

        frames.append((img, step))
        prev_gray = curr_gray

        # 向上滚动到下一帧位置
        if step < hard_safety_frames - 1:
            scroll_plan.append(scroll_clicks)
            pyautogui.scroll(scroll_clicks, x=cx, y=cy)
            time.sleep(step_delay)

    _log(f"   采集完成: {len(frames)} 帧, 滚动计划={scroll_plan}")
    return frames, scroll_plan


def capture_scrolled_map_simple(
    region: tuple[int, int, int, int],
    map_center: tuple[int, int],
    clicks_per_step: int = 300,
    sub_click_size: int = 20,
    step_delay: float = 0.4,
    max_frames: int = 8,
    log_fn=None,
) -> tuple[list[tuple[Image.Image, int]], list[int]]:
    """
    简单固定步长滚动截图（仿 scroll_to_map_bottom 方式）。

    每步向上滚动 clicks_per_step 个滚轮格（拆成若干 sub_click_size 的小步快速打出），
    等待画面稳定后截图，直到连续 2 帧相似度 >= 0.97 判定到达顶部。

    优势：不依赖自适应算法，步长稳定，预期 3-6 帧覆盖完整 3-4 屏地图。
    调用前应确保镜头已在地图底部（先调用 scroll_to_map_bottom）。

    :param region:         截图区域 (x, y, w, h)
    :param map_center:     鼠标停放坐标 (cx, cy)
    :param clicks_per_step: 每步总滚轮格数（默认 300，约 1 屏高度）
    :param sub_click_size: 每次 pyautogui.scroll() 的单步格数（同 scroll_to_map_bottom）
    :param step_delay:     每步滚动后等待画面稳定的时间（秒）
    :param max_frames:     最大截图帧数（安全上限，防止意外死循环）
    :param log_fn:         日志回调
    :return: (frames, scroll_plan)
             frames[(img, scroll_step)], scroll_step=0 为底部起点
             scroll_plan[i] = 第 i 步使用的总滚轮格数（固定值）
    """
    cx, cy = map_center
    frames: list[tuple[Image.Image, int]] = []
    scroll_plan: list[int] = []
    prev_gray: np.ndarray | None = None
    top_stall = 0
    n_sub = max(1, clicks_per_step // sub_click_size)

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    pyautogui.moveTo(cx, cy, duration=0.05)

    for step in range(max_frames):
        img = capture_region(*region)
        curr_gray = np.array(img.convert("L"))

        if prev_gray is not None:
            sim = _frame_similarity(prev_gray, curr_gray)
            _log(f"   帧 {step}: 相似度 {sim:.3f}")
            if sim >= 0.97:
                top_stall += 1
                _log(f"   → 几乎无变化，顶部计数 {top_stall}/2")
                if top_stall >= 2:
                    frames.append((img, step))
                    _log("   连续 2 帧无变化，判定到达 Boss 顶部")
                    break
            else:
                top_stall = 0
        else:
            _log(f"   帧 {step}: 初始截图（底部起点）")

        frames.append((img, step))
        prev_gray = curr_gray

        # 向上滚动一步：多次 sub_click_size 快速打出
        scroll_plan.append(clicks_per_step)
        for _ in range(n_sub):
            pyautogui.scroll(sub_click_size, x=cx, y=cy)
            time.sleep(0.02)
        time.sleep(step_delay)

    _log(f"   采集完成: {len(frames)} 帧")
    return frames, scroll_plan


def capture_scrolled_map_anchor(
    region: tuple[int, int, int, int],
    map_center: tuple[int, int],
    scroll_clicks_per_tick: int = 20,
    tick_delay: float = 0.05,
    settle_delay: float = 0.35,
    anchor_rows: int = 120,
    match_threshold: float = 0.60,
    max_frames: int = 10,
    max_ticks_per_frame: int = 300,
    log_fn=None,
) -> tuple[list[tuple[Image.Image, int]], list[int], list[int]]:
    """
    锚点式滚动截图：边滚边截，只保留"锚点恰好滚到底部"时的关键帧。

    原理：
      - 记录当前关键帧顶部 anchor_rows 像素作为"锚点"
      - 反复向上小量滚动（每次 scroll_clicks_per_tick 格），每次检测
      - 在每张截图的底部区域搜索锚点模板
      - 一旦找到 → 稳定后截关键帧，两帧几乎零重叠，step_size 精确已知
      - 用新关键帧顶部更新锚点，循环直到到达 Boss 顶部

    相比固定步长/自适应步长方案，此方案帧数极少（约 4-6 帧），
    且拼接精度由像素级锚点匹配保证，不依赖后期重叠检测。

    :param region:                 截图区域 (x, y, w, h)
    :param map_center:             鼠标停放坐标 (cx, cy)
    :param scroll_clicks_per_tick: 每次小滚动的格数（建议 15~25）
    :param tick_delay:             每次小滚动后的等待时间（秒）
    :param settle_delay:           找到锚点后等画面稳定的等待（秒）
    :param anchor_rows:            用作锚点的顶部像素行数
    :param match_threshold:        模板匹配置信度阈值
    :param max_frames:             最多关键帧数（安全上限）
    :param max_ticks_per_frame:    每帧最多小滚动次数（防死循环）
    :param log_fn:                 日志回调
    :return: (keyframes, clicks_plan, step_sizes)
             keyframes[(img, scroll_step)], step=0 为地图底部起点
             clicks_plan[i]: 关键帧 i->i+1 的总滚轮格数（用于点击复现）
             step_sizes[i]:  关键帧 i+1 贡献的新像素高度（用于精确拼接）
    """
    cx, cy = map_center

    def _log(msg: str):
        if log_fn:
            log_fn(msg)

    pyautogui.moveTo(cx, cy, duration=0.05)
    time.sleep(0.3)

    # ── 关键帧 0：底部起点 ──────────────────────────────────────
    img0 = capture_region(*region)
    gray0 = np.array(img0.convert("L"))
    H, W = gray0.shape[:2]

    keyframes: list[tuple[Image.Image, int]] = [(img0, 0)]
    clicks_plan: list[int] = []
    step_sizes: list[int] = []

    # 锚点 = 第 0 帧顶部（地图底部附近已截到的内容）
    anchor = gray0[:anchor_rows, :].copy()
    _log(f"   关键帧 0: 底部起点，尺寸={W}×{H}，锚点={anchor_rows}px")

    # 搜索区域：底部 2/3（锚点应随滚动出现在画面下方）
    search_top = H // 3
    stall_count = 0

    for frame_idx in range(1, max_frames):
        total_clicks = 0
        found = False

        for _ in range(max_ticks_per_frame):
            pyautogui.scroll(scroll_clicks_per_tick, x=cx, y=cy)
            time.sleep(tick_delay)
            total_clicks += scroll_clicks_per_tick

            live_img = capture_region(*region)
            live_gray = np.array(live_img.convert("L"))

            # 在底部区域搜索锚点（留出锚点自身高度的安全边距）
            s_end = H - anchor_rows // 4
            s_region = live_gray[search_top:s_end, :]
            if anchor.shape[0] >= s_region.shape[0] or anchor.shape[1] > s_region.shape[1]:
                continue

            res = cv2.matchTemplate(s_region, anchor, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val < match_threshold:
                continue

            # 找到锚点 → 等画面稳定后截关键帧
            time.sleep(settle_delay)
            kf_img = capture_region(*region)
            kf_gray = np.array(kf_img.convert("L"))

            # 用稳定后的截图重新确认锚点位置（提高精度）
            s2 = kf_gray[search_top:s_end, :]
            if anchor.shape[0] < s2.shape[0] and anchor.shape[1] <= s2.shape[1]:
                res2 = cv2.matchTemplate(s2, anchor, cv2.TM_CCOEFF_NORMED)
                _, mv2, _, ml2 = cv2.minMaxLoc(res2)
                if mv2 >= match_threshold:
                    max_val, max_loc = mv2, ml2

            # step_size = 锚点在新帧的 Y 位置 = 新帧贡献的新增像素数
            y_match = search_top + max_loc[1]
            step_size = max(anchor_rows, y_match)

            sim = _frame_similarity(
                np.array(keyframes[-1][0].convert("L")), kf_gray
            )
            _log(
                f"   关键帧 {frame_idx}: 锚点置信={max_val:.3f} @ y={y_match}, "
                f"step={step_size}px, 总滚轮={total_clicks}, 相似度={sim:.3f}"
            )

            if sim >= 0.97:
                stall_count += 1
                _log(f"   → 与上帧高度相似，顶部计数 {stall_count}/2")
                if stall_count >= 2:
                    _log("   已到达 Boss 顶部，停止采集")
                    found = True
                    break
            else:
                stall_count = 0
                clicks_plan.append(total_clicks)
                step_sizes.append(step_size)
                keyframes.append((kf_img, frame_idx))
                anchor = kf_gray[:anchor_rows, :].copy()

            found = True
            break

        if not found:
            _log(f"   {max_ticks_per_frame} ticks 内未找到锚点，判定已到顶")
            break
        if stall_count >= 2:
            break

    _log(f"   采集完成: {len(keyframes)} 个关键帧，step_sizes={step_sizes}")
    return keyframes, clicks_plan, step_sizes
