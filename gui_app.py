"""
gui_app.py
Auto Painter GUI 应用程序
杀戮尖塔2 地图自动绘画工具 - 图形界面版
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog

import cv2
import numpy as np
import pyautogui
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from features.painter.processor import process_image, process_text
from core.path_opt import optimize_strokes
from core.mouse import draw_strokes
from features.route_planner import (
    NodeType, recognize_map, build_map_graph, find_all_routes,
    RoutePreferences, rank_routes, draw_route_on_screen,
)
from features.route_planner.recognizer import (
    recognize_full_map_scrolled, stitch_screenshots, stitch_with_step_sizes,
)
from features.route_planner.optimizer import describe_route
from features.route_planner.drawer import route_to_strokes

# 可选：Windows 文件拖入支持
try:
    import windnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ── 常量 ──────────────────────────────────────
PREVIEW_SIZE = (400, 300)
SPEED_MAP = {"慢速": 0.001, "中速": 0.0004, "快速": 0.00008}
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]


class AutoPainterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("STS2 Game Assistant — 杀戮尖塔2 游戏助手")
        self.geometry("960x740")
        self.minsize(880, 660)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # 状态
        self.image_path = None
        self.font_path = None
        self.drawing_thread = None
        self.stop_event = threading.Event()
        self.is_drawing = False
        self._preview_photo = None  # 防止 GC 回收
        self._thumb_photo = None
        self._route_screenshot = None   # 路线规划：当前截图
        self._route_preview_photo = None

        self._build_ui()
        self.log("就绪。选择绘画功能或路线规划功能开始使用。")

    # ═══════════════════════════════════════════
    #  UI 构建
    # ═══════════════════════════════════════════

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── 标题栏 ──
        title_frame = ctk.CTkFrame(self, corner_radius=8)
        title_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            title_frame, text="⚔ STS2 Assistant",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left", padx=15, pady=8)
        ctk.CTkLabel(
            title_frame,
            text="杀戮尖塔2 游戏助手  ·  ⚡ 鼠标移到左上角紧急停止",
            font=ctk.CTkFont(size=12), text_color="#aaaaaa"
        ).pack(side="left", padx=10)

        # ── 功能标签页 ──
        self.feature_tabs = ctk.CTkTabview(self, corner_radius=8)
        self.feature_tabs.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # 绘画标签页
        paint_tab = self.feature_tabs.add("🎨 绘画")
        paint_tab.grid_columnconfigure(0, weight=0, minsize=380)
        paint_tab.grid_columnconfigure(1, weight=1, minsize=440)
        paint_tab.grid_rowconfigure(0, weight=1)
        self._build_left_panel(paint_tab)
        self._build_right_panel(paint_tab)

        # 路线规划标签页
        route_tab = self.feature_tabs.add("🗺 路线规划")
        self._build_route_panel(route_tab)

        # ── 底部控制区 ──
        self._build_bottom()

    def _build_left_panel(self, parent):
        left = ctk.CTkFrame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=0)
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(left, corner_radius=8)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self._build_image_tab()
        self._build_text_tab()

    def _build_image_tab(self):
        tab = self.tabview.add("🖼 图片模式")
        tab.grid_columnconfigure(0, weight=1)

        # 拖入/选择区域
        drop_frame = ctk.CTkFrame(
            tab, height=110, corner_radius=8,
            border_width=2, border_color="#555555"
        )
        drop_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        drop_frame.grid_propagate(False)
        drop_frame.grid_columnconfigure(0, weight=1)
        drop_frame.grid_rowconfigure(0, weight=1)

        self.drop_label = ctk.CTkLabel(
            drop_frame,
            text="📁 点击选择图片，或拖入图片文件\n支持 jpg / png / bmp",
            font=ctk.CTkFont(size=13), text_color="#888888",
            cursor="hand2"
        )
        self.drop_label.grid(row=0, column=0, sticky="nsew")
        self.drop_label.bind("<Button-1>", lambda e: self._browse_image())
        drop_frame.bind("<Button-1>", lambda e: self._browse_image())

        # 注册文件拖入，强制使用 Unicode 路径，避免 Windows ANSI/bytes 路径解析问题
        if HAS_DND:
            windnd.hook_dropfiles(self, func=self._on_image_drop, force_unicode=True)

        # 文件信息
        self.file_label = ctk.CTkLabel(
            tab, text="未选择文件", text_color="#888888",
            font=ctk.CTkFont(size=11)
        )
        self.file_label.grid(row=1, column=0, sticky="w", padx=15, pady=(0, 10))

        # Canny 参数
        canny_frame = ctk.CTkFrame(tab, fg_color="transparent")
        canny_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        canny_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            canny_frame, text="Canny 低阈值:", font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.canny_low_var = tk.IntVar(value=50)
        ctk.CTkSlider(
            canny_frame, from_=10, to=200,
            variable=self.canny_low_var, number_of_steps=190
        ).grid(row=0, column=1, sticky="ew", padx=5)
        self.canny_low_display = ctk.CTkLabel(
            canny_frame, text="50", width=40, font=ctk.CTkFont(size=12)
        )
        self.canny_low_display.grid(row=0, column=2, padx=5)
        self.canny_low_var.trace_add("write", lambda *_: self.canny_low_display.configure(
            text=str(self.canny_low_var.get())))

        ctk.CTkLabel(
            canny_frame, text="Canny 高阈值:", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.canny_high_var = tk.IntVar(value=150)
        ctk.CTkSlider(
            canny_frame, from_=10, to=400,
            variable=self.canny_high_var, number_of_steps=390
        ).grid(row=1, column=1, sticky="ew", padx=5)
        self.canny_high_display = ctk.CTkLabel(
            canny_frame, text="150", width=40, font=ctk.CTkFont(size=12)
        )
        self.canny_high_display.grid(row=1, column=2, padx=5)
        self.canny_high_var.trace_add("write", lambda *_: self.canny_high_display.configure(
            text=str(self.canny_high_var.get())))

    def _build_text_tab(self):
        tab = self.tabview.add("✏ 文字模式")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab, text="输入要绘制的文字（支持多行）：",
            font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, sticky="nw", padx=10, pady=(10, 2))

        self.text_input = ctk.CTkTextbox(
            tab, height=160, font=ctk.CTkFont(size=14), corner_radius=6
        )
        self.text_input.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        # 字体选择
        font_frame = ctk.CTkFrame(tab, fg_color="transparent")
        font_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        font_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            font_frame, text="字体:", font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, sticky="w", padx=5)
        self.font_label = ctk.CTkLabel(
            font_frame, text="系统自动选择",
            text_color="#888888", font=ctk.CTkFont(size=11)
        )
        self.font_label.grid(row=0, column=1, sticky="w", padx=5)
        ctk.CTkButton(
            font_frame, text="选择字体", width=80, height=28,
            command=self._browse_font
        ).grid(row=0, column=2, padx=5)

    def _build_right_panel(self, parent):
        right = ctk.CTkFrame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=0)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        # 预览区域
        preview_frame = ctk.CTkFrame(right, corner_radius=8)
        preview_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            preview_frame, text="边缘预览",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))

        self.preview_label = ctk.CTkLabel(
            preview_frame,
            text="选择图片或输入文字后\n点击「预览效果」查看边缘检测结果",
            text_color="#666666", font=ctk.CTkFont(size=12),
            corner_radius=6, fg_color="#1a1a1a"
        )
        self.preview_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))

        # 绘制设置
        settings_frame = ctk.CTkFrame(right, corner_radius=8)
        settings_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
        settings_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            settings_frame, text="绘制设置",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 5))

        # 画布比例
        ctk.CTkLabel(
            settings_frame, text="画布比例:", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, sticky="w", padx=(12, 5), pady=4)
        self.ratio_var = tk.IntVar(value=80)
        ctk.CTkSlider(
            settings_frame, from_=50, to=95,
            variable=self.ratio_var, number_of_steps=45
        ).grid(row=1, column=1, sticky="ew", padx=5, pady=4)
        self.ratio_display = ctk.CTkLabel(
            settings_frame, text="80%", width=50, font=ctk.CTkFont(size=12)
        )
        self.ratio_display.grid(row=1, column=2, padx=(5, 12), pady=4)
        self.ratio_var.trace_add("write", lambda *_: self.ratio_display.configure(
            text=f"{self.ratio_var.get()}%"))

        # 倒计时
        ctk.CTkLabel(
            settings_frame, text="倒计时:", font=ctk.CTkFont(size=12)
        ).grid(row=2, column=0, sticky="w", padx=(12, 5), pady=4)
        self.countdown_var = tk.IntVar(value=5)
        ctk.CTkSlider(
            settings_frame, from_=1, to=15,
            variable=self.countdown_var, number_of_steps=14
        ).grid(row=2, column=1, sticky="ew", padx=5, pady=4)
        self.countdown_display = ctk.CTkLabel(
            settings_frame, text="5秒", width=50, font=ctk.CTkFont(size=12)
        )
        self.countdown_display.grid(row=2, column=2, padx=(5, 12), pady=4)
        self.countdown_var.trace_add("write", lambda *_: self.countdown_display.configure(
            text=f"{self.countdown_var.get()}秒"))

        # 绘制速度
        ctk.CTkLabel(
            settings_frame, text="绘制速度:", font=ctk.CTkFont(size=12)
        ).grid(row=3, column=0, sticky="w", padx=(12, 5), pady=4)
        self.speed_var = tk.StringVar(value="中速")
        speed_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        speed_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=5, pady=4)
        for label in ["慢速", "中速", "快速"]:
            ctk.CTkRadioButton(
                speed_frame, text=label, variable=self.speed_var,
                value=label, font=ctk.CTkFont(size=12)
            ).pack(side="left", padx=8)

        # 鼠标按键
        ctk.CTkLabel(
            settings_frame, text="鼠标按键:", font=ctk.CTkFont(size=12)
        ).grid(row=4, column=0, sticky="w", padx=(12, 5), pady=(4, 8))
        self.button_var = tk.StringVar(value="right")
        btn_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        btn_frame.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=(4, 8))
        ctk.CTkRadioButton(
            btn_frame, text="右键", variable=self.button_var,
            value="right", font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=8)
        ctk.CTkRadioButton(
            btn_frame, text="左键", variable=self.button_var,
            value="left", font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=8)

    # ═══════════════════════════════════════════
    #  路线规划面板
    # ═══════════════════════════════════════════

    def _build_route_panel(self, parent):
        """路线规划功能面板"""
        parent.grid_columnconfigure(0, weight=1, minsize=360)
        parent.grid_columnconfigure(1, weight=1, minsize=440)
        parent.grid_rowconfigure(0, weight=1)

        # ── 左侧：偏好设置 + 操作 ──
        left = ctk.CTkFrame(parent, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=0)
        left.grid_columnconfigure(0, weight=1)

        # ── 节点偏好设置 ──
        pref_frame = ctk.CTkFrame(left, corner_radius=6)
        pref_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 5))
        pref_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            pref_frame, text="路线偏好设置",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 2))

        ctk.CTkLabel(
            pref_frame,
            text="滑块：← 尽量少  ·  中立  ·  尽量多 →",
            font=ctk.CTkFont(size=10), text_color="#888888"
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        node_prefs = [
            ("🔥 休息 (营火)", "rest"),
            ("👹 精英",        "elite"),
            ("🏪 商人",        "merchant"),
            ("❓ 未知",        "unknown"),
            ("🗝 宝箱",        "treasure"),
            ("👾 敌人",        "monster"),
        ]
        self._route_weight_vars: dict[str, tk.IntVar] = {}
        _slider_labels = ["最少", "较少", "中立", "较多", "最多"]

        for row_i, (label, key) in enumerate(node_prefs, start=2):
            ctk.CTkLabel(
                pref_frame, text=label, font=ctk.CTkFont(size=12)
            ).grid(row=row_i, column=0, sticky="w", padx=(10, 5), pady=3)

            var = tk.IntVar(value=0)
            self._route_weight_vars[key] = var

            ctk.CTkSlider(
                pref_frame, from_=-2, to=2, number_of_steps=4,
                variable=var
            ).grid(row=row_i, column=1, sticky="ew", padx=5, pady=3)

            display = ctk.CTkLabel(
                pref_frame, text="中立", width=42, font=ctk.CTkFont(size=11)
            )
            display.grid(row=row_i, column=2, padx=(0, 10), pady=3)

            def _make_handler(v=var, d=display):
                def _h(*_):
                    idx = max(0, min(4, v.get() + 2))
                    d.configure(text=_slider_labels[idx])
                return _h
            var.trace_add("write", _make_handler())

        # ── 滚动采集设置 ──
        scroll_frame = ctk.CTkFrame(left, corner_radius=6)
        scroll_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 5))
        scroll_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            scroll_frame, text="地图采集设置",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))

        # 倒计时
        ctk.CTkLabel(
            scroll_frame, text="倒计时:", font=ctk.CTkFont(size=12)
        ).grid(row=1, column=0, sticky="w", padx=(10, 5), pady=3)
        self._route_countdown_var = tk.IntVar(value=5)
        ctk.CTkSlider(
            scroll_frame, from_=2, to=10, number_of_steps=8,
            variable=self._route_countdown_var,
        ).grid(row=1, column=1, sticky="ew", padx=5, pady=3)
        self._route_cd_display = ctk.CTkLabel(
            scroll_frame, text="5秒", width=42, font=ctk.CTkFont(size=11)
        )
        self._route_cd_display.grid(row=1, column=2, padx=(0, 10), pady=3)
        self._route_countdown_var.trace_add("write", lambda *_:
            self._route_cd_display.configure(text=f"{self._route_countdown_var.get()}秒"))

        ctk.CTkLabel(
            scroll_frame,
            text="提示：滚动截图自适应调整，无需手动设置步数",
            font=ctk.CTkFont(size=10), text_color="#888888"
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(2, 8))

        # ── 操作按钮 ──
        self._route_start_btn = ctk.CTkButton(
            left, text="▶ 开始规划并绘制", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2d5a9e", hover_color="#3a72c4",
            command=self._route_start
        )
        self._route_start_btn.grid(row=2, column=0, sticky="ew", padx=12, pady=(12, 5))

        self._route_stop_btn = ctk.CTkButton(
            left, text="■ 停止", height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#aa3333", hover_color="#cc4444",
            command=self._route_stop,
            state="disabled"
        )
        self._route_stop_btn.grid(row=3, column=0, sticky="ew", padx=12, pady=(5, 12))

        # ── 右侧：地图预览 + 路线方案列表 ──
        right = ctk.CTkFrame(parent, corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=0)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=2)
        right.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            right, text="地图预览",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 2))

        self.route_preview_label = ctk.CTkLabel(
            right,
            text="点击「开始规划」后\n将自动截图并分析地图",
            text_color="#666666", font=ctk.CTkFont(size=12),
            corner_radius=6, fg_color="#1a1a1a"
        )
        self.route_preview_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))

        ctk.CTkLabel(
            right, text="推荐路线",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=2, column=0, sticky="w", padx=12, pady=(4, 2))

        # 路线列表（CTkScrollableFrame 内放单选按钮）
        self._route_list_frame = ctk.CTkScrollableFrame(right, height=120, corner_radius=6)
        self._route_list_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=(2, 8))
        self._route_list_frame.grid_columnconfigure(0, weight=1)
        self._route_selected_var = tk.IntVar(value=-1)

        ctk.CTkLabel(
            self._route_list_frame,
            text="点击「开始规划」后，推荐方案将在此处显示",
            text_color="#666666", font=ctk.CTkFont(size=11)
        ).grid(row=0, column=0, sticky="w", padx=8, pady=8)

        # 内部状态
        self._route_graph = None
        self._route_ranked = []   # [(score, path), ...]
        self._route_stitched = None  # 拼接全图
        self._route_scroll_plan = []
        self._route_thread = None
        self._route_stop_event = threading.Event()

    # ── 路线规划事件处理 ─────────────────────────────────────

    def _route_start(self):
        """开始一体化路线规划 + 绘制流程"""
        if self._route_thread and self._route_thread.is_alive():
            return

        self._route_stop_event.clear()
        self.stop_event.clear()
        self._route_start_btn.configure(state="disabled")
        self._route_stop_btn.configure(state="normal")

        self._route_thread = threading.Thread(
            target=self._route_worker, daemon=True
        )
        self._route_thread.start()

    def _route_stop(self):
        """中断路线规划流程"""
        self._route_stop_event.set()
        self.stop_event.set()
        self._log_safe("⏹ 正在停止...")

    def _route_worker(self):
        """一体化路线规划 + 绘制后台线程"""
        try:
            countdown = self._route_countdown_var.get()

            # ── 1. 倒计时 ──
            for i in range(countdown, 0, -1):
                if self._route_stop_event.is_set():
                    self._route_finish("⏹ 已取消")
                    return
                self._log_safe(f"⏳ 请切换到游戏地图界面... {i}s")
                self._status_safe(f"⏳ 切换到游戏... {i}s")
                time.sleep(1)

            # ── 2. 最小化 GUI 窗口 ──
            self.after(0, self.iconify)
            time.sleep(0.5)

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # ── 3. 获取屏幕参数，执行滚动截图 ──
            self._log_safe("📷 开始滚动采集地图...")
            self._status_safe("📷 滚动采集中...")

            screen_w, screen_h = pyautogui.size()
            margin_x = int(screen_w * 0.05)
            margin_y = int(screen_h * 0.05)
            map_region = (margin_x, margin_y,
                          screen_w - 2 * margin_x, screen_h - 2 * margin_y)
            map_cx = screen_w // 2
            map_cy = screen_h // 2

            from core.screen import scroll_to_map_bottom, capture_scrolled_map_anchor, scroll_map

            # 先滚到底部（起点）—— 大量向下滚动确保到底
            self._log_safe("↓ 滚动到地图底部...")
            scroll_to_map_bottom(map_cx, map_cy)

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # 锚点式截图：每帧在前一帧的基础上精确衔接，无重叠/无多余帧
            # anchor_rows=120: 用顶部 120px 做匹配锚点
            # scroll_clicks_per_tick=20: 每小步 20 格，平滑滚动
            raw_frames, scroll_plan, step_sizes = capture_scrolled_map_anchor(
                region=map_region,
                map_center=(map_cx, map_cy),
                scroll_clicks_per_tick=20,
                anchor_rows=120,
                log_fn=self._log_safe,
            )
            screenshots = [img for img, _ in raw_frames]
            self._route_scroll_plan = scroll_plan
            self._log_safe(
                f"📷 采集完成：{len(screenshots)} 个关键帧，"
                f"step_sizes={step_sizes}"
            )

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # ── 4. 拼接截图（使用锚点精确步长，跳过重叠检测）──
            self._log_safe("🧩 拼接地图中...")
            self._status_safe("🧩 拼接中...")
            if step_sizes:
                stitched, y_offsets = stitch_with_step_sizes(screenshots, step_sizes)
            else:
                # 只有 1 帧（地图极短或直接到顶）
                stitched, y_offsets = screenshots[0].copy(), [0]
            self._route_stitched = stitched
            self._update_route_preview(stitched)

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # ── 5. 模板匹配识别节点 ──
            self._log_safe("🔍 识别地图节点...")
            self._status_safe("🔍 节点识别中...")

            templates_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "assets", "node_templates"
            )

            from features.route_planner.recognizer import (
                load_all_templates, detect_nodes, _detect_edges_by_lines, _refine_detected_map
            )

            templates = load_all_templates(templates_dir)
            if not templates:
                self._log_safe("⚠ 未找到节点模板！请将模板图片放入 assets/node_templates/<类型>/")
                for d in os.listdir(templates_dir):
                    dpath = os.path.join(templates_dir, d)
                    if os.path.isdir(dpath):
                        files = [f for f in os.listdir(dpath) if f.lower().endswith(('.png','.jpg','.bmp'))]
                        self._log_safe(f"   {d}/: {len(files)} 张图片")
                self._route_finish("❌ 模板不足，无法识别")
                return

            self._log_safe(f"   已加载模板: {', '.join(t.name for t in templates)}")

            stitched_gray = np.array(stitched.convert("L"))
            nodes = detect_nodes(stitched_gray, templates)
            self._log_safe(f"   原始识别到 {len(nodes)} 个节点")

            if len(nodes) < 2:
                self._log_safe("⚠ 识别到的节点过少，请检查模板图片或调整截图步数")
                self._route_finish("❌ 节点不足")
                return

            # ── 5.5 虚线边检测 ──
            self._log_safe("🔗 检测节点间虚线连接...")
            edges = _detect_edges_by_lines(nodes, stitched_gray)
            self._log_safe(f"   原始检测到 {len(edges)} 条虚线连接")

            # 为节点附加 screen_pos 和 scroll_step
            frame_h = screenshots[0].height
            rx, ry = map_region[0], map_region[1]
            for node in nodes:
                cx, cy = node.position
                best_step = 0
                min_dist = float("inf")
                for step, y_off in enumerate(y_offsets):
                    local_y = cy - y_off
                    if 0 <= local_y < frame_h:
                        dist = abs(local_y - frame_h // 2)
                        if dist < min_dist:
                            min_dist = dist
                            best_step = step
                node.scroll_step = best_step
                local_y_in_frame = cy - y_offsets[best_step]
                node.screen_pos = (rx + cx, ry + local_y_in_frame)

            nodes, edges = _refine_detected_map(nodes, edges)
            self._log_safe(f"   去重净化后：{len(nodes)} 个节点，{len(edges)} 条边")

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # ── 6. 构建图 + 枚举路径 + 评分 ──
            self._log_safe("🗺 构建地图图结构...")
            self._status_safe("🗺 路线分析中...")

            graph = build_map_graph(nodes, edges)
            all_routes = find_all_routes(graph)
            self._log_safe(f"   枚举到 {len(all_routes)} 条可行路径")

            if not all_routes:
                self._log_safe("⚠ 未找到可行路线，地图识别可能不完整")
                self._route_finish("❌ 无可行路线")
                return

            # 评分
            slider_vals = {k: v.get() for k, v in self._route_weight_vars.items()}
            prefs = RoutePreferences.from_slider_values(slider_vals)
            ranked = rank_routes(all_routes, graph, prefs, top_n=5)

            self._route_graph = graph
            self._route_ranked = ranked

            # 显示推荐
            self._log_safe(f"✅ 分析完成！Top {len(ranked)} 推荐路线：")
            for i, (score, path) in enumerate(ranked):
                desc = describe_route(path, graph)
                self._log_safe(f"   #{i+1} (得分 {score:.1f}): {desc}")

            self.after(0, self._route_update_list)

            # ── 7. 选择最优路线（得分相同则随机） ──
            import random
            best_score = ranked[0][0]
            best_routes = [(s, p) for s, p in ranked if s == best_score]
            chosen_score, chosen_path = random.choice(best_routes)

            chosen_idx = ranked.index((chosen_score, chosen_path))
            desc = describe_route(chosen_path, graph)
            self._log_safe(f"🎯 选中路线 #{chosen_idx+1} (得分 {chosen_score:.1f}): {desc}")

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 已取消")
                return

            # ── 8. 直接绘制选中路线 ──
            self._log_safe("🖊 开始绘制路线...")
            self._status_safe("🖊 绘制路线中...")

            # 先滚回底部
            scroll_to_map_bottom(map_cx, map_cy)
            time.sleep(0.3)

            # 按 scroll_step 分组绘制
            scroll_plan = getattr(self, "_route_scroll_plan", [])
            step_groups: dict[int, list[int]] = {}
            for nid in chosen_path:
                node = graph.nodes[nid]
                step_groups.setdefault(node.scroll_step, []).append(nid)

            current_step = 0
            for target_step in sorted(step_groups.keys()):
                steps_to_scroll = target_step - current_step
                if steps_to_scroll > 0:
                    for step_idx in range(current_step, target_step):
                        scroll_clicks = scroll_plan[step_idx] if step_idx < len(scroll_plan) else 48
                        scroll_map(scroll_clicks, map_cx, map_cy)
                        time.sleep(0.3)
                    current_step = target_step

                if self._route_stop_event.is_set():
                    self._route_finish("⏹ 绘制已中断")
                    return

                group_nids = set(step_groups[target_step])
                sub_path = [nid for nid in chosen_path if nid in group_nids]
                strokes = route_to_strokes(sub_path, graph)
                if strokes:
                    draw_strokes(
                        strokes, move_speed=0.0004, button="right",
                        stop_event=self.stop_event,
                    )

            if self._route_stop_event.is_set():
                self._route_finish("⏹ 绘制已中断")
            else:
                self.after(0, self.deiconify)
                self._route_finish_done("✅ 路线规划 + 绘制完成！")

        except pyautogui.FailSafeException:
            self.after(0, self.deiconify)
            self._route_finish("⚡ 紧急中止（鼠标移到左上角）")
        except Exception as e:
            self.after(0, self.deiconify)
            self._route_finish(f"❌ 错误: {e}")

    def _route_update_list(self):
        """更新路线列表 UI（主线程调用）"""
        for w in self._route_list_frame.winfo_children():
            w.destroy()

        self._route_selected_var.set(0)

        for i, (score, path) in enumerate(self._route_ranked):
            desc = describe_route(path, self._route_graph)
            text = f"#{i+1}  得分 {score:.1f}  |  {desc}"
            rb = ctk.CTkRadioButton(
                self._route_list_frame,
                text=text,
                variable=self._route_selected_var,
                value=i,
                font=ctk.CTkFont(size=11),
            )
            rb.grid(row=i, column=0, sticky="w", padx=8, pady=4)

    def _update_route_preview(self, img):
        """更新地图预览缩略图（线程安全）"""
        thumb = img.copy()
        thumb.thumbnail((440, 300), Image.LANCZOS)
        photo = ctk.CTkImage(light_image=thumb, dark_image=thumb,
                             size=(thumb.width, thumb.height))
        self._route_preview_photo = photo
        self.after(0, lambda: self.route_preview_label.configure(
            image=self._route_preview_photo, text=""
        ))

    def _route_finish(self, msg):
        """路线规划结束（失败/取消）"""
        self._log_safe(msg)
        self._status_safe(msg)
        self.after(0, self.deiconify)
        self.after(0, lambda: self._route_start_btn.configure(state="normal"))
        self.after(0, lambda: self._route_stop_btn.configure(state="disabled"))

    def _route_finish_done(self, msg):
        """路线规划+绘制全流程成功"""
        self._log_safe(msg)
        self._status_safe(msg)
        self.after(0, lambda: self._route_start_btn.configure(state="normal"))
        self.after(0, lambda: self._route_stop_btn.configure(state="disabled"))

    def _build_bottom(self):
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
        bottom.grid_columnconfigure(0, weight=1)

        # 按钮行
        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        btn_row.grid_columnconfigure(3, weight=1)

        self.preview_btn = ctk.CTkButton(
            btn_row, text="📸 预览效果", width=130, height=36,
            command=self._update_preview, font=ctk.CTkFont(size=13)
        )
        self.preview_btn.grid(row=0, column=0, padx=5)

        self.start_btn = ctk.CTkButton(
            btn_row, text="▶ 开始绘制", width=130, height=36,
            fg_color="#2d7d2d", hover_color="#3a9a3a",
            command=self._start_drawing,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.start_btn.grid(row=0, column=1, padx=5)

        self.stop_btn = ctk.CTkButton(
            btn_row, text="■ 停止", width=90, height=36,
            fg_color="#aa3333", hover_color="#cc4444",
            command=self._stop_drawing, state="disabled",
            font=ctk.CTkFont(size=13)
        )
        self.stop_btn.grid(row=0, column=2, padx=5)

        self.status_label = ctk.CTkLabel(
            btn_row, text="", font=ctk.CTkFont(size=12), text_color="#aaaaaa"
        )
        self.status_label.grid(row=0, column=3, sticky="e", padx=10)

        # 进度条
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(bottom, variable=self.progress_var)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.progress_bar.set(0)

        # 日志区
        self.log_box = ctk.CTkTextbox(
            bottom, height=100, font=ctk.CTkFont(size=11),
            state="disabled", corner_radius=6
        )
        self.log_box.grid(row=2, column=0, sticky="ew", padx=5, pady=(0, 5))

    # ═══════════════════════════════════════════
    #  文件选择
    # ═══════════════════════════════════════════

    def _browse_image(self):
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")]
        )
        if path:
            self._set_image(path)

    def _on_image_drop(self, files):
        if not files:
            return
        raw = files[0]

        if isinstance(raw, bytes):
            raw = raw.replace(b'\x00', b'')
            for enc in ("utf-8", "gbk"):
                try:
                    path = raw.decode(enc)
                    break
                except (UnicodeDecodeError, AttributeError):
                    continue
            else:
                path = str(raw)
        else:
            path = str(raw)

        path = path.replace("\x00", "").strip()
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        path = os.path.normpath(path.strip().strip('"').strip())

        ext = os.path.splitext(path)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp"):
            self._set_image(path)
            self.tabview.set("🖼 图片模式")
        else:
            self.log(f"⚠ 不支持的文件格式: {ext}  路径: {path}")

    def _set_image(self, path):
        if not os.path.exists(path):
            self.log(f"❌ 文件不存在: {path}")
            return
        self.image_path = path
        name = os.path.basename(path)
        self.file_label.configure(text=f"📄 {name}", text_color="#cccccc")

        # 显示缩略图
        try:
            img = Image.open(path)
            img.thumbnail((80, 80), Image.LANCZOS)
            self._thumb_photo = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(img.width, img.height)
            )
            self.drop_label.configure(
                image=self._thumb_photo,
                text=f"\n{name}\n点击重新选择"
            )
        except Exception:
            self.drop_label.configure(text=f"📄 {name}\n点击重新选择")

        self.log(f"已选择图片: {name}")

    def _browse_font(self):
        path = filedialog.askopenfilename(
            title="选择字体文件",
            filetypes=[("字体文件", "*.ttf *.ttc *.otf"), ("所有文件", "*.*")]
        )
        if path:
            self.font_path = path
            self.font_label.configure(
                text=os.path.basename(path), text_color="#cccccc"
            )

    # ═══════════════════════════════════════════
    #  预览
    # ═══════════════════════════════════════════

    def _load_font(self, size):
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        for candidate in FONT_CANDIDATES:
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _update_preview(self):
        tab = self.tabview.get()
        try:
            if tab == "🖼 图片模式":
                self._preview_image_mode()
            else:
                self._preview_text_mode()
        except Exception as e:
            self.log(f"❌ 预览生成失败: {e}")

    def _preview_image_mode(self):
        if not self.image_path:
            self.log("⚠ 请先选择图片")
            return

        img = Image.open(self.image_path).convert("L")
        canny_low = self.canny_low_var.get()
        canny_high = self.canny_high_var.get()

        # 缩放到预览尺寸
        img.thumbnail(PREVIEW_SIZE, Image.LANCZOS)

        img_array = np.array(img)
        blurred = cv2.GaussianBlur(img_array, (3, 3), 0)
        edges = cv2.Canny(blurred, canny_low, canny_high)

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        self._show_preview(Image.fromarray(edges))
        self.log(f"📸 预览已更新 — 检测到 {len(contours)} 段轮廓")

    def _preview_text_mode(self):
        text = self.text_input.get("1.0", "end").strip()
        if not text:
            self.log("⚠ 请输入文字")
            return

        font = self._load_font(80)
        dummy = Image.new("L", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        margin = 30
        img = Image.new("L", (tw + 2 * margin, th + 2 * margin), color=0)
        d = ImageDraw.Draw(img)
        d.text((margin - bbox[0], margin - bbox[1]), text, fill=255, font=font)

        img.thumbnail(PREVIEW_SIZE, Image.LANCZOS)
        img_array = np.array(img)
        blurred = cv2.GaussianBlur(img_array, (3, 3), 0)
        edges = cv2.Canny(blurred, 30, 100)

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        self._show_preview(Image.fromarray(edges))
        self.log(f"📸 文字预览已更新 — 检测到 {len(contours)} 段轮廓")

    def _show_preview(self, pil_img):
        self._preview_photo = ctk.CTkImage(
            light_image=pil_img, dark_image=pil_img,
            size=(pil_img.width, pil_img.height)
        )
        self.preview_label.configure(image=self._preview_photo, text="")

    # ═══════════════════════════════════════════
    #  绘制
    # ═══════════════════════════════════════════

    def _start_drawing(self):
        if self.is_drawing:
            return

        # 路线规划标签页有独立的绘制入口
        if self.feature_tabs.get() == "🗺 路线规划":
            self._route_draw_selected()
            return

        tab = self.tabview.get()
        if tab == "🖼 图片模式" and not self.image_path:
            self.log("⚠ 请先选择图片")
            return
        if tab == "✏ 文字模式" and not self.text_input.get("1.0", "end").strip():
            self.log("⚠ 请输入文字")
            return

        self.is_drawing = True
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.preview_btn.configure(state="disabled")
        self.progress_bar.set(0)

        self.drawing_thread = threading.Thread(
            target=self._drawing_worker, daemon=True
        )
        self.drawing_thread.start()

    def _stop_drawing(self):
        if self.is_drawing:
            self.stop_event.set()
            self.log("⏹ 正在停止...")

    def _drawing_worker(self):
        try:
            tab = self.tabview.get()
            ratio = self.ratio_var.get() / 100
            speed = SPEED_MAP[self.speed_var.get()]
            btn = self.button_var.get()
            wait = self.countdown_var.get()

            # 处理图片/文字
            if tab == "🖼 图片模式":
                self._log_safe("⚙ 处理图片中...")
                raw_contours = process_image(
                    self.image_path, canvas_ratio=ratio,
                    canny_low=self.canny_low_var.get(),
                    canny_high=self.canny_high_var.get()
                )
                min_dist = 1.0
            else:
                text = self.text_input.get("1.0", "end").strip()
                self._log_safe("⚙ 渲染文字中...")
                raw_contours = process_text(
                    text, font_path=self.font_path, canvas_ratio=ratio
                )
                min_dist = 1.5

            if self.stop_event.is_set():
                self._finish_drawing("⏹ 已取消")
                return

            self._log_safe("⚙ 优化路径中...")
            strokes = optimize_strokes(raw_contours, min_dist=min_dist)
            self._log_safe(f"✅ 优化后共 {len(strokes)} 段笔画")

            if self.stop_event.is_set():
                self._finish_drawing("⏹ 已取消")
                return

            # 倒计时
            for i in range(wait, 0, -1):
                if self.stop_event.is_set():
                    self._finish_drawing("⏹ 已取消")
                    return
                self._status_safe(f"⏳ 请切换到游戏窗口... {i}s")
                time.sleep(1)

            self._status_safe("🎨 绘制中...")
            self._log_safe("🎨 开始绘制！")

            # 执行绘制
            draw_strokes(
                strokes, move_speed=speed, button=btn,
                progress_callback=self._progress_safe,
                stop_event=self.stop_event
            )

            if self.stop_event.is_set():
                self._finish_drawing("⏹ 绘制已中断")
            else:
                self._finish_drawing("✅ 绘制完成！")

        except pyautogui.FailSafeException:
            self._finish_drawing("⚡ 紧急中止（鼠标移到左上角）")
        except Exception as e:
            self._finish_drawing(f"❌ 错误: {e}")

    def _finish_drawing(self, msg):
        self.is_drawing = False
        self._log_safe(msg)
        self._status_safe(msg)
        self.after(0, lambda: self.start_btn.configure(state="normal"))
        self.after(0, lambda: self.stop_btn.configure(state="disabled"))
        self.after(0, lambda: self.preview_btn.configure(state="normal"))

    # ═══════════════════════════════════════════
    #  线程安全的 UI 更新
    # ═══════════════════════════════════════════

    def _log_safe(self, msg):
        self.after(0, lambda: self.log(msg))

    def _status_safe(self, msg):
        self.after(0, lambda: self.status_label.configure(text=msg))

    def _progress_safe(self, current, total):
        val = current / total
        self.after(0, lambda: self.progress_bar.set(val))
        self.after(0, lambda: self.status_label.configure(
            text=f"🎨 绘制中 {current}/{total} ({val * 100:.0f}%)"
        ))

    # ═══════════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════════

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"> {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_closing(self):
        if self.is_drawing:
            self.stop_event.set()
            if self.drawing_thread:
                self.drawing_thread.join(timeout=3)
        self.destroy()


if __name__ == "__main__":
    app = AutoPainterApp()
    app.mainloop()
