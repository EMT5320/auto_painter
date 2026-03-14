"""
core/screen.py
屏幕捕获与区域管理工具
"""

from __future__ import annotations

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
