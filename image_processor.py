"""
image_processor.py
图像/文字处理模块
将图片或文字转换为可绘制的轮廓路径（屏幕坐标）
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pyautogui


def get_canvas_size(ratio: float = 0.6):
    """
    根据屏幕大小和比例计算画布尺寸与中心偏移
    :param ratio: 占屏幕的比例，0.5~0.7
    :return: (canvas_w, canvas_h, offset_x, offset_y)
             offset = 画布左上角的屏幕坐标
    """
    screen_w, screen_h = pyautogui.size()
    canvas_w = int(screen_w * ratio)
    canvas_h = int(screen_h * ratio)
    offset_x = (screen_w - canvas_w) // 2
    offset_y = (screen_h - canvas_h) // 2
    print(f"🖥  屏幕: {screen_w}x{screen_h}  画布: {canvas_w}x{canvas_h}  偏移: ({offset_x},{offset_y})")
    return canvas_w, canvas_h, offset_x, offset_y


def _image_to_contours(img_gray: np.ndarray,
                       canny_low: int = 50,
                       canny_high: int = 150) -> list:
    """
    对灰度图执行Canny边缘检测并提取轮廓点列表
    返回：[ [(x,y), ...], ... ]  每项为一段连续轮廓
    """
    # 轻微模糊去噪
    blurred = cv2.GaussianBlur(img_gray, (3, 3), 0)

    # Canny边缘检测
    edges = cv2.Canny(blurred, canny_low, canny_high)

    # 提取轮廓
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_L1)

    result = []
    for cnt in contours:
        # cnt shape: (N, 1, 2) → [(x,y), ...]
        pts = [(int(p[0][0]), int(p[0][1])) for p in cnt]
        # 闭合轮廓：将首点加到末尾
        if len(pts) > 2:
            pts.append(pts[0])
        result.append(pts)

    return result


def _map_to_screen(contours: list, offset_x: int, offset_y: int) -> list:
    """将画布坐标转换为屏幕坐标"""
    return [[(x + offset_x, y + offset_y) for x, y in stroke]
            for stroke in contours]


# ─────────────────────────────────────────────
#  公开接口
# ─────────────────────────────────────────────

def process_image(image_path: str,
                  canvas_ratio: float = 0.6,
                  canny_low: int = 50,
                  canny_high: int = 150) -> list:
    """
    从图片文件提取绘制路径
    :param image_path: 图片路径
    :param canvas_ratio: 画布占屏幕比例
    :return: 屏幕坐标轮廓列表
    """
    canvas_w, canvas_h, offset_x, offset_y = get_canvas_size(canvas_ratio)

    # 读取并缩放图片
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((canvas_w, canvas_h), Image.LANCZOS)

    # 居中放置：如果图片比画布小，计算额外偏移
    extra_x = (canvas_w - img.width) // 2
    extra_y = (canvas_h - img.height) // 2

    # 转为灰度 numpy 数组
    img_gray = np.array(img.convert("L"))

    print(f"🖼  图片尺寸: {img.width}x{img.height}  中心对齐偏移: +({extra_x},{extra_y})")

    contours = _image_to_contours(img_gray, canny_low, canny_high)
    print(f"🔍 检测到 {len(contours)} 段轮廓")

    # 应用总偏移
    final_ox = offset_x + extra_x
    final_oy = offset_y + extra_y

    return _map_to_screen(contours, final_ox, final_oy)


def process_text(text: str,
                 font_path: str = None,
                 font_size: int = None,
                 canvas_ratio: float = 0.6,
                 canny_low: int = 30,
                 canny_high: int = 100) -> list:
    """
    将文字渲染为图片，再提取轮廓路径
    :param text: 要绘制的文字
    :param font_path: 字体文件路径（None则使用默认字体）
    :param font_size: 字体大小（None则自动计算）
    :param canvas_ratio: 画布占屏幕比例
    :return: 屏幕坐标轮廓列表
    """
    canvas_w, canvas_h, offset_x, offset_y = get_canvas_size(canvas_ratio)

    # 自动计算字体大小：以画布高度的60%为目标
    if font_size is None:
        lines = text.strip().split('\n')
        line_count = max(len(lines), 1)
        font_size = max(int(canvas_h * 0.55 / line_count), 20)

    # 加载字体
    try:
        if font_path:
            font = ImageFont.truetype(font_path, font_size)
        else:
            # 尝试常见系统字体
            for candidate in [
                "C:/Windows/Fonts/msyh.ttc",        # 微软雅黑（中文）
                "C:/Windows/Fonts/simhei.ttf",       # 黑体
                "C:/Windows/Fonts/arial.ttf",        # Arial
                "C:/Windows/Fonts/calibri.ttf",      # Calibri
            ]:
                try:
                    font = ImageFont.truetype(candidate, font_size)
                    print(f"🔠 使用字体: {candidate}  大小: {font_size}")
                    break
                except Exception:
                    continue
            else:
                font = ImageFont.load_default()
                print("⚠  使用默认像素字体（建议指定字体路径）")
    except Exception as e:
        print(f"⚠  字体加载失败：{e}，使用默认字体")
        font = ImageFont.load_default()

    # 计算文字实际尺寸
    dummy = Image.new("L", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 如果文字超出画布，缩小字号重试
    if text_w > canvas_w or text_h > canvas_h:
        scale = min(canvas_w / text_w, canvas_h / text_h) * 0.9
        font_size = max(int(font_size * scale), 12)
        print(f"🔠 文字过大，自动缩小字号到 {font_size}")
        return process_text(text, font_path, font_size, canvas_ratio, canny_low, canny_high)

    print(f"📝 文字尺寸: {text_w}x{text_h}  字号: {font_size}")

    # 渲染白色文字到黑色背景
    img = Image.new("L", (text_w + 10, text_h + 10), color=0)
    d = ImageDraw.Draw(img)
    d.text((5, 5), text, fill=255, font=font)

    img_array = np.array(img)

    contours = _image_to_contours(img_array, canny_low, canny_high)
    print(f"🔍 检测到 {len(contours)} 段轮廓")

    # 居中偏移
    extra_x = (canvas_w - text_w) // 2
    extra_y = (canvas_h - text_h) // 2
    final_ox = offset_x + extra_x
    final_oy = offset_y + extra_y

    return _map_to_screen(contours, final_ox, final_oy)
