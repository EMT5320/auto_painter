"""
core/mouse.py
鼠标绘制执行模块
按住右键沿路径移动，模拟游戏内绘画

迁移自根目录 mouse_controller.py
"""

import time
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


def draw_strokes(strokes: list, move_speed: float = 0.0005, lift_speed: float = 0.001,
                 button: str = 'right', progress_callback=None, stop_event=None):
    """
    执行绘制
    :param strokes: [ [(x,y), ...], [(x,y), ...], ... ] 每个子列表是一段连续笔画
    :param move_speed: 绘制时每步停留秒数（越小越快）
    :param lift_speed: 抬笔移动时每步停留秒数
    :param button: 绘制用的鼠标键，'right' 或 'left'
    :param progress_callback: 可选，callable(current, total) 用于GUI进度更新
    :param stop_event: 可选，threading.Event 用于中断绘制
    """
    if not strokes:
        print("⚠ 没有可绘制的路径")
        return

    total_strokes = len(strokes)
    print(f"📊 共 {total_strokes} 段笔画，开始绘制...")

    current_pos = None

    for i, stroke in enumerate(strokes):
        if stop_event and stop_event.is_set():
            pyautogui.mouseUp(button=button)
            return

        if not stroke:
            continue

        if progress_callback:
            progress_callback(i + 1, total_strokes)
        else:
            pct = (i + 1) / total_strokes * 100
            print(f"   进度: {pct:.1f}%  ({i+1}/{total_strokes})", end="\r", flush=True)

        # 过滤屏幕边缘危险点
        stroke = [(x, y) for x, y in stroke if _safe_point(x, y)]
        if not stroke:
            continue
        start = stroke[0]

        # 抬笔移动到起点（如果不是第一笔）
        if current_pos is not None and current_pos != start:
            pyautogui.mouseUp(button=button)
            lift_path = interpolate_points(current_pos, start, step=20)
            for pt in lift_path:
                pyautogui.moveTo(pt[0], pt[1])
                time.sleep(lift_speed)

        # 落笔并沿路径移动
        pyautogui.moveTo(start[0], start[1])
        pyautogui.mouseDown(button=button)

        for j in range(1, len(stroke)):
            seg = interpolate_points(stroke[j-1], stroke[j], step=4)
            for pt in seg:
                pyautogui.moveTo(pt[0], pt[1])
                time.sleep(move_speed)

        current_pos = stroke[-1]

    pyautogui.mouseUp(button=button)
    print("\n✅ 绘制完成！")
