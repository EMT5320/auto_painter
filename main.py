"""
main.py
杀戮尖塔2 自动绘画程序
使用 Canny 边缘检测 + 最近邻路径优化 + 鼠标模拟右键绘制

使用方法：
  python main.py

依赖安装：
  pip install -r requirements.txt
"""

import sys
import os

from image_processor import process_image, process_text
from path_optimizer import optimize_strokes
from mouse_controller import countdown, draw_strokes


def print_banner():
    print("""
╔══════════════════════════════════════════════╗
║       🎨  自动绘画程序  Auto Painter          ║
║       适用于 杀戮尖塔2 地图画布               ║
╚══════════════════════════════════════════════╝
  ⚡ 鼠标移到屏幕左上角可紧急中止
  📐 绘制范围：以屏幕中心为基准，占屏幕60%
""")


def ask_speed():
    """询问绘制速度"""
    print("🚀 绘制速度：")
    print("  1. 慢速（效果好，游戏稳定）")
    print("  2. 中速（推荐）")
    print("  3. 快速（可能有丢失）")
    choice = input("  选择 [1/2/3，默认2]: ").strip() or "2"
    speeds = {"1": 0.001, "2": 0.0004, "3": 0.00008}
    return speeds.get(choice, 0.002)


def ask_countdown():
    """询问倒计时秒数"""
    val = input("⏳ 启动后等待几秒切换窗口？[默认5]: ").strip()
    try:
        return max(1, int(val))
    except ValueError:
        return 5


def ask_canvas_ratio():
    """询问画布比例"""
    val = input("📐 画布占屏幕比例(50-70%)？[默认60]: ").strip()
    try:
        r = int(val)
        return max(50, min(70, r)) / 100
    except ValueError:
        return 0.6


def ask_button():
    """询问使用哪个鼠标键绘制"""
    print("🖱  绘制按键：")
    print("  1. 右键（默认）")
    print("  2. 左键")
    choice = input("  选择 [1/2，默认1]: ").strip() or "1"
    return 'left' if choice == "2" else 'right'


def mode_image():
    """图片模式"""
    path = input("\n📁 请输入图片路径（支持 jpg/png/bmp）：").strip().strip('"')
    if not os.path.exists(path):
        print(f"❌ 文件不存在：{path}")
        return

    print("\n🔧 Canny 参数（影响边缘细节，默认值适合大多数图片）")
    low  = input("  低阈值 [默认50]: ").strip()
    high = input("  高阈值 [默认150]: ").strip()
    canny_low  = int(low)  if low.isdigit()  else 50
    canny_high = int(high) if high.isdigit() else 150

    ratio = ask_canvas_ratio()
    btn   = ask_button()
    speed = ask_speed()
    wait  = ask_countdown()

    print("\n⚙  处理图片中...")
    raw_contours = process_image(path, canvas_ratio=ratio,
                                 canny_low=canny_low, canny_high=canny_high)

    print("⚙  优化路径中...")
    strokes = optimize_strokes(raw_contours, min_dist=2.0)
    print(f"✅ 优化后共 {len(strokes)} 段笔画")

    countdown(wait)
    draw_strokes(strokes, move_speed=speed, button=btn)


def mode_text():
    """文字模式"""
    print("\n✏  请输入要绘制的文字（直接回车结束，连续输入多行后空行结束）：")
    lines = []
    while True:
        line = input()
        if line == "":          # 空行 = 结束
            break
        lines.append(line)
    if not lines:
        print("❌ 未输入任何文字")
        return
    text = "\n".join(lines)

    font_path = input("\n🔤 字体文件路径（留空自动选择系统字体）：").strip().strip('"') or None
    if font_path and not os.path.exists(font_path):
        print("⚠  字体路径无效，将使用自动字体")
        font_path = None

    ratio = ask_canvas_ratio()
    btn   = ask_button()
    speed = ask_speed()
    wait  = ask_countdown()

    print("\n⚙  渲染文字中...")
    raw_contours = process_text(text, font_path=font_path, canvas_ratio=ratio)

    print("⚙  优化路径中...")
    strokes = optimize_strokes(raw_contours, min_dist=1.5)
    print(f"✅ 优化后共 {len(strokes)} 段笔画")

    countdown(wait)
    draw_strokes(strokes, move_speed=speed, button=btn)


def main():
    print_banner()

    while True:
        print("=" * 48)
        print("请选择模式：")
        print("  1. 🖼  图片绘制")
        print("  2. ✏  文字绘制")
        print("  0. 退出")
        print("=" * 48)
        choice = input("输入选项：").strip()

        if choice == "1":
            mode_image()
        elif choice == "2":
            mode_text()
        elif choice == "0":
            print("👋 再见！")
            sys.exit(0)
        else:
            print("❌ 无效选项，请重新输入\n")


if __name__ == "__main__":
    main()
