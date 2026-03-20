"""
features/painter/ai_sketch.py
AI 素描模式 — 使用 Informative Drawings (ONNX) 将图片转为高质量线稿
再提取轮廓路径用于鼠标绘制

模型来源: https://huggingface.co/rocca/informative-drawings-line-art-onnx
论文: "Learning to generate line drawings that convey geometry and semantics" (CVPR 2022)

依赖: onnxruntime, opencv-python, numpy, Pillow, pyautogui
"""

import os
import sys
import urllib.request

import cv2
import numpy as np
from PIL import Image
import pyautogui

# ─────────────────────────────────────────────
#  模型管理
# ─────────────────────────────────────────────

# 模型存放在项目 assets/models/ 下
_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "models")
_MODEL_FILENAME = "informative_drawings_line_art.onnx"
_MODEL_PATH = os.path.normpath(os.path.join(_MODEL_DIR, _MODEL_FILENAME))

# HuggingFace 直链下载
_MODEL_URL = (
    "https://huggingface.co/rocca/informative-drawings-line-art-onnx"
    "/resolve/main/model.onnx"
)

# 全局缓存推理会话
_session = None


def _ensure_model() -> str:
    """确保模型文件存在，不存在时自动下载"""
    if os.path.exists(_MODEL_PATH):
        return _MODEL_PATH

    os.makedirs(_MODEL_DIR, exist_ok=True)
    print(f"📥 首次使用，正在下载 AI 素描模型（~17MB）...")
    print(f"   来源: {_MODEL_URL}")
    print(f"   保存: {_MODEL_PATH}")

    try:
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH, _download_progress)
        print("\n✅ 模型下载完成！")
    except Exception as e:
        # 清理不完整文件
        if os.path.exists(_MODEL_PATH):
            os.remove(_MODEL_PATH)
        raise RuntimeError(
            f"模型下载失败: {e}\n"
            f"请手动下载并放入: {_MODEL_PATH}\n"
            f"下载地址: {_MODEL_URL}"
        ) from e

    return _MODEL_PATH


def _download_progress(block_num, block_size, total_size):
    """下载进度回调"""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(downloaded / total_size * 100, 100)
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r   [{bar}] {pct:.1f}%", end="", flush=True)


def _get_session():
    """获取或创建 ONNX 推理会话（懒加载 + 缓存）"""
    global _session
    if _session is not None:
        return _session

    model_path = _ensure_model()

    try:
        import onnxruntime as ort
    except ImportError:
        raise ImportError(
            "AI 素描模式需要 onnxruntime，请先安装：\n"
            "  pip install onnxruntime"
        )

    print("🔧 加载 AI 素描模型...")
    _session = ort.InferenceSession(
        model_path,
        providers=["CPUExecutionProvider"],
    )
    print("✅ 模型加载完成")
    return _session


# ─────────────────────────────────────────────
#  核心推理
# ─────────────────────────────────────────────

def _image_to_line_art(img: Image.Image, model_size: int = 512) -> np.ndarray:
    """
    用 Informative Drawings 模型将图片转为线稿
    :param img: PIL RGB 图片
    :param model_size: 模型输入尺寸（正方形）
    :return: 灰度线稿 numpy 数组 (H, W)，0=线条, 255=背景
    """
    session = _get_session()

    # 记录原始尺寸
    orig_w, orig_h = img.size

    # 预处理：resize 到模型输入尺寸
    img_resized = img.resize((model_size, model_size), Image.LANCZOS)
    img_np = np.array(img_resized).astype(np.float32) / 255.0

    # 归一化 (ImageNet 标准)
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    img_np = (img_np - mean) / std

    # CHW + batch 维度
    img_np = img_np.transpose(2, 0, 1)  # HWC → CHW
    img_np = np.expand_dims(img_np, axis=0)  # (1, 3, H, W)

    # 推理
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: img_np})

    # 后处理
    result = output[0][0]  # 去掉 batch 维度

    # 处理不同的输出格式
    if result.ndim == 3:
        # (C, H, W) → 取第一个通道或平均
        if result.shape[0] == 1:
            result = result[0]
        else:
            result = result.mean(axis=0)

    # 归一化到 0-255
    result = result - result.min()
    if result.max() > 0:
        result = result / result.max()
    result = (result * 255).astype(np.uint8)

    # Resize 回原始尺寸
    result = cv2.resize(result, (orig_w, orig_h), interpolation=cv2.INTER_LANCZOS4)

    return result


# ─────────────────────────────────────────────
#  轮廓提取
# ─────────────────────────────────────────────

def _line_art_to_contours(line_art: np.ndarray,
                          threshold: int = 128,
                          invert: bool = True) -> list:
    """
    从线稿图提取轮廓路径
    :param line_art: 灰度线稿 (H, W)
    :param threshold: 二值化阈值
    :param invert: 是否反转（模型输出通常线条为暗色）
    :return: [ [(x,y), ...], ... ]
    """
    # 二值化
    if invert:
        _, binary = cv2.threshold(line_art, threshold, 255, cv2.THRESH_BINARY_INV)
    else:
        _, binary = cv2.threshold(line_art, threshold, 255, cv2.THRESH_BINARY)

    # 轻微形态学操作：去除噪点、平滑线条
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 骨架化 / 细化线条（用形态学近似）
    thin = cv2.ximgproc.thinning(binary) if hasattr(cv2, 'ximgproc') else binary

    # 提取轮廓
    contours, _ = cv2.findContours(thin, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_L1)

    result = []
    for cnt in contours:
        pts = [(int(p[0][0]), int(p[0][1])) for p in cnt]
        if len(pts) > 2:
            pts.append(pts[0])  # 闭合
        if len(pts) >= 2:
            result.append(pts)

    return result


def _map_to_screen(contours: list, offset_x: int, offset_y: int) -> list:
    """将画布坐标转换为屏幕坐标"""
    return [[(x + offset_x, y + offset_y) for x, y in stroke]
            for stroke in contours]


# ─────────────────────────────────────────────
#  公开接口
# ─────────────────────────────────────────────

def process_image_ai(image_path: str,
                     canvas_ratio: float = 0.6,
                     threshold: int = 128,
                     model_size: int = 512,
                     detail_level: str = "normal") -> list:
    """
    AI 素描模式：将图片转为高质量线稿再提取绘制路径
    :param image_path: 图片路径
    :param canvas_ratio: 画布占屏幕比例
    :param threshold: 二值化阈值（越大线条越多越密）
    :param model_size: 模型输入尺寸（越大细节越多但推理越慢）
    :param detail_level: 细节等级 "minimal"/"normal"/"detailed"
    :return: 屏幕坐标轮廓列表
    """
    # 画布计算
    screen_w, screen_h = pyautogui.size()
    canvas_w = int(screen_w * canvas_ratio)
    canvas_h = int(screen_h * canvas_ratio)
    offset_x = (screen_w - canvas_w) // 2
    offset_y = (screen_h - canvas_h) // 2
    print(f"🖥  屏幕: {screen_w}x{screen_h}  画布: {canvas_w}x{canvas_h}")

    # 加载图片并缩放到画布
    img = Image.open(image_path).convert("RGB")
    scale = min(canvas_w / img.width, canvas_h / img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    extra_x = (canvas_w - new_w) // 2
    extra_y = (canvas_h - new_h) // 2
    print(f"🖼  图片尺寸: {new_w}x{new_h}  中心对齐偏移: +({extra_x},{extra_y})")

    # 根据细节等级调整参数
    detail_configs = {
        "minimal":  {"threshold": 80,  "model_size": 384},
        "normal":   {"threshold": threshold, "model_size": model_size},
        "detailed": {"threshold": 180, "model_size": 768},
    }
    cfg = detail_configs.get(detail_level, detail_configs["normal"])
    effective_threshold = cfg["threshold"]
    effective_model_size = cfg["model_size"]

    print(f"🎨 细节等级: {detail_level}  阈值: {effective_threshold}  模型输入: {effective_model_size}px")

    # AI 推理生成线稿
    print("🤖 AI 正在生成线稿...")
    line_art = _image_to_line_art(img, model_size=effective_model_size)
    print("✅ 线稿生成完成")

    # 提取轮廓
    contours = _line_art_to_contours(line_art, threshold=effective_threshold)
    print(f"🔍 检测到 {len(contours)} 段轮廓")

    # 坐标映射
    final_ox = offset_x + extra_x
    final_oy = offset_y + extra_y
    return _map_to_screen(contours, final_ox, final_oy)


def get_line_art_preview(image_path: str,
                         threshold: int = 128,
                         model_size: int = 512,
                         detail_level: str = "normal") -> Image.Image:
    """
    生成线稿预览图（用于 GUI 预览）
    :return: PIL 灰度图
    """
    detail_configs = {
        "minimal":  {"threshold": 80,  "model_size": 384},
        "normal":   {"threshold": threshold, "model_size": model_size},
        "detailed": {"threshold": 180, "model_size": 768},
    }
    cfg = detail_configs.get(detail_level, detail_configs["normal"])

    img = Image.open(image_path).convert("RGB")
    line_art = _image_to_line_art(img, model_size=cfg["model_size"])

    # 二值化
    _, binary = cv2.threshold(line_art, cfg["threshold"], 255, cv2.THRESH_BINARY)

    return Image.fromarray(binary)
