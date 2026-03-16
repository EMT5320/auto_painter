"""
core/mouse.py
鼠标绘制执行模块
按住右键沿路径移动，模拟游戏内绘画

迁移自根目录 mouse_controller.py
"""

import time
import cv2
import pyautogui
import numpy as np

# 全局安全设置
pyautogui.FAIL_SAFE = True   # 鼠标移到左上角紧急停止
pyautogui.PAUSE = 0          # 关闭默认的0.1s全局暂停（这是速度慢的主要原因）


def countdown(seconds: int = 5, callback=None, stop_event=None):
    """倒计时，给用户时间切换到游戏窗口
    :param callback: 可选，callable(remaining_seconds) 用于GUI更新
    :param stop_event: 可选，threading.Event 用于中断
    :return: True=正常完成, False=被中断
    """
    if callback is None:
        print(f"\n⏳ 请在 {seconds} 秒内切换到游戏窗口...")
    for i in range(seconds, 0, -1):
        if stop_event and stop_event.is_set():
            return False
        if callback:
            callback(i)
        else:
            print(f"   {i}...", end="\r", flush=True)
        time.sleep(1)
    if callback is None:
        print("🎨 开始绘制！                    ")
    return True


def interpolate_points(p1, p2, step=4):
    """
    在两点之间插值，确保鼠标移动连贯
    step: 每隔多少像素取一个点（越大点越少越快）
    """
    x1, y1 = p1
    x2, y2 = p2
    dist = np.hypot(x2 - x1, y2 - y1)
    n = max(int(dist / step), 1)
    xs = np.linspace(x1, x2, n, dtype=int)
    ys = np.linspace(y1, y2, n, dtype=int)
    return list(zip(xs, ys))


def _safe_point(x, y, margin=5):
    """过滤掉屏幕边缘的点，防止触发 FailSafe"""
    sw, sh = pyautogui.size()
    return margin < x < sw - margin and margin < y < sh - margin


# ─────────────────────────────────────────────
#  暂停/恢复定位辅助
# ─────────────────────────────────────────────

def _get_draw_region(strokes: list, padding: int = 48):
    """根据全部笔画计算绘制区域，用于暂停恢复时限制搜索范围。"""
    points = [pt for stroke in strokes for pt in stroke]
    if not points:
        sw, sh = pyautogui.size()
        return 0, 0, sw, sh

    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]
    sw, sh = pyautogui.size()

    left = max(0, int(min(xs)) - padding)
    top = max(0, int(min(ys)) - padding)
    right = min(sw, int(max(xs)) + padding)
    bottom = min(sh, int(max(ys)) + padding)

    width = max(right - left, min(240, sw))
    height = max(bottom - top, min(240, sh))
    left = max(0, min(left, sw - width))
    top = max(0, min(top, sh - height))
    return left, top, width, height


def _capture_anchor(draw_region, anchor_ratio: float = 0.5):
    """截取绘制区域中央锚点，恢复时仅在绘制区域内搜索它。"""
    left, top, width, height = draw_region
    anchor_w = max(80, int(width * anchor_ratio))
    anchor_h = max(80, int(height * anchor_ratio))
    anchor_w = min(anchor_w, width)
    anchor_h = min(anchor_h, height)

    anchor_x = left + (width - anchor_w) // 2
    anchor_y = top + (height - anchor_h) // 2
    anchor_img = pyautogui.screenshot(region=(anchor_x, anchor_y, anchor_w, anchor_h))
    anchor_bgr = cv2.cvtColor(np.array(anchor_img), cv2.COLOR_RGB2BGR)
    return anchor_bgr, (anchor_x - left, anchor_y - top)


def _match_anchor_in_region(draw_region, anchor_bgr):
    """在绘制区域内匹配锚点模板。"""
    left, top, width, height = draw_region
    screen_img = pyautogui.screenshot(region=(left, top, width, height))
    screen_bgr = cv2.cvtColor(np.array(screen_img), cv2.COLOR_RGB2BGR)
    ah, aw = anchor_bgr.shape[:2]
    if screen_bgr.shape[0] < ah or screen_bgr.shape[1] < aw:
        return 0.0, (0, 0)

    result = cv2.matchTemplate(screen_bgr, anchor_bgr, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return float(max_val), max_loc


def _restore_view_from_anchor(draw_region, anchor_bgr, anchor_rel, stop_event=None,
                              settle_delay: float = 0.02):
    """
    参考项目的做法：
    1. 先滚动扫描，尽量把原区域找回来
    2. 找到后用左键拖动画面，物理对齐到原位置
    3. 返回很小的残差偏移，避免恢复瞬间出现飞线
    """
    left, top, width, height = draw_region
    center_x = left + width // 2
    center_y = top + height // 2
    best_score = 0.0
    best_loc = (0, 0)
    found = False

    scroll_sweeps = [0] + [120] * 5 + [-120] * 10 + [120] * 5
    for sweep in scroll_sweeps:
        if stop_event and stop_event.is_set():
            return False, 0, 0
        if sweep != 0:
            pyautogui.moveTo(center_x, center_y)
            pyautogui.scroll(sweep)
            time.sleep(max(0.25, settle_delay * 8))

        score, loc = _match_anchor_in_region(draw_region, anchor_bgr)
        if score > best_score:
            best_score = score
            best_loc = loc
        if score >= 0.80:
            found = True
            break

    if not found:
        print(f"   ⚠ 未能找回原位置（最高匹配度 {best_score:.2f}），保留当前位置继续")
        return True, 0, 0

    dx = best_loc[0] - anchor_rel[0]
    dy = best_loc[1] - anchor_rel[1]
    print(f"   已锁定锚点，初始偏差: ({dx:+d}, {dy:+d})，匹配度 {best_score:.2f}")

    residual_dx = dx
    residual_dy = dy
    for _ in range(5):
        if stop_event and stop_event.is_set():
            return False, 0, 0
        if abs(residual_dx) <= 2 and abs(residual_dy) <= 2:
            residual_dx = 0
            residual_dy = 0
            break

        pyautogui.moveTo(center_x, center_y)
        pyautogui.mouseDown(button='left')
        time.sleep(max(0.03, settle_delay * 2))
        pyautogui.move(-residual_dx, -residual_dy, duration=0.18)
        time.sleep(max(0.03, settle_delay * 2))
        pyautogui.mouseUp(button='left')
        time.sleep(max(0.25, settle_delay * 8))

        score, loc = _match_anchor_in_region(draw_region, anchor_bgr)
        if score < 0.50:
            break
        residual_dx = loc[0] - anchor_rel[0]
        residual_dy = loc[1] - anchor_rel[1]

    residual_dx = int(max(min(residual_dx, 80), -80))
    residual_dy = int(max(min(residual_dy, 80), -80))
    if residual_dx or residual_dy:
        print(f"   对齐完成，保留小残差修正: ({residual_dx:+d}, {residual_dy:+d})")
    else:
        print("   对齐完成，已回到原位置")
    return True, residual_dx, residual_dy


def draw_strokes(strokes: list, move_speed: float = 0.0005, lift_speed: float = 0.001,
                 button: str = 'right', progress_callback=None, stop_event=None,
                 pause_event=None):
    """
    执行绘制。
    :param strokes: [ [(x,y), ...], ... ] 原始屏幕坐标，每段为一笔
    :param move_speed: 绘制时每步停留秒数（越小越快）
    :param lift_speed: 抬笔移动时每步停留秒数
    :param button: 'right' 或 'left'
    :param progress_callback: callable(current, total)
    :param stop_event: threading.Event，set 时中止
    :param pause_event: threading.Event，set 时暂停；恢复时用模板匹配修正坐标偏移
    """
    if not strokes:
        print("⚠ 没有可绘制的路径")
        return

    total_strokes = len(strokes)
    print(f"📊 共 {total_strokes} 段笔画，开始绘制...")

    draw_region = _get_draw_region(strokes)
    settle_delay = max(0.02, min(0.08, lift_speed * 20))
    current_pos = None
    current_shift = [0, 0]

    def shifted(point):
        return point[0] + current_shift[0], point[1] + current_shift[1]

    def _handle_pause(stroke_idx, should_redraw_down=False):
        pyautogui.mouseUp(button=button)
        anchor_bgr, anchor_rel = _capture_anchor(draw_region)
        print(f"\n⏸ 绘制暂停（{stroke_idx}/{total_strokes} 段），已保存中央锚点")

        while pause_event.is_set():
            if stop_event and stop_event.is_set():
                return False
            time.sleep(0.05)

        print("▶ 正在滚动搜索并恢复原位置...")
        ok, shift_x, shift_y = _restore_view_from_anchor(
            draw_region,
            anchor_bgr,
            anchor_rel,
            stop_event=stop_event,
            settle_delay=settle_delay,
        )
        if not ok:
            return False

        current_shift[0] = shift_x
        current_shift[1] = shift_y
        if current_pos is not None:
            resume_pt = shifted(current_pos)
            if _safe_point(*resume_pt):
                pyautogui.moveTo(*resume_pt, duration=0.01)
                time.sleep(settle_delay)
                if should_redraw_down:
                    pyautogui.mouseDown(button=button)
                    time.sleep(settle_delay)
        return True

    for i, stroke in enumerate(strokes):
        # 停止检查
        if stop_event and stop_event.is_set():
            pyautogui.mouseUp(button=button)
            return

        # 笔画间暂停（鼠标已抬起，安全位置）
        if pause_event and pause_event.is_set():
            if not _handle_pause(i):
                return

        if not stroke:
            continue

        if progress_callback:
            progress_callback(i + 1, total_strokes)
        else:
            pct = (i + 1) / total_strokes * 100
            print(f"   进度: {pct:.1f}%  ({i+1}/{total_strokes})", end="\r", flush=True)

        # 计算起点（含偏移）
        start = shifted(stroke[0])
        if not _safe_point(*start):
            continue

        # 抬笔移动到起点（如果不是第一笔）
        if current_pos is not None:
            cur = shifted(current_pos)
            if cur != start:
                pyautogui.mouseUp(button=button)
                lift_path = interpolate_points(cur, start, step=20)
                for pt in lift_path:
                    pyautogui.moveTo(pt[0], pt[1])
                    time.sleep(lift_speed)

        pyautogui.moveTo(*start)
        pyautogui.mouseDown(button=button)

        for j in range(1, len(stroke)):
            # 笔画中途暂停
            if pause_event and pause_event.is_set():
                current_pos = stroke[j - 1]   # 记录暂停的原始坐标
                if not _handle_pause(i, should_redraw_down=True):
                    return

            # 停止检查
            if stop_event and stop_event.is_set():
                pyautogui.mouseUp(button=button)
                return

            p_prev = shifted(stroke[j - 1])
            p_next = shifted(stroke[j])
            if not _safe_point(*p_next):
                continue

            seg = interpolate_points(p_prev, p_next, step=4)
            for pt in seg:
                pyautogui.moveTo(pt[0], pt[1])
                time.sleep(move_speed)

        current_pos = stroke[-1]   # 保存原始坐标

    pyautogui.mouseUp(button=button)
    print("\n✅ 绘制完成！")
