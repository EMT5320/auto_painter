"""
build_exe.py
使用 PyInstaller 将 Auto Painter GUI 打包为单文件 .exe
用法: python build_exe.py
"""

import subprocess
import sys
import os

def main():
    # 确保 pyinstaller 已安装
    try:
        import PyInstaller
    except ImportError:
        print("正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(script_dir, "gui_app.py")

    # 查找 customtkinter 路径（PyInstaller 需要手动收集）
    import customtkinter
    ctk_path = os.path.dirname(customtkinter.__file__)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",                   # 无控制台窗口
        "--name", "AutoPainter",
        "--add-data", f"{ctk_path};customtkinter/",
        "--hidden-import", "customtkinter",
        "--hidden-import", "PIL",
        "--hidden-import", "cv2",
        "--hidden-import", "numpy",
        "--hidden-import", "pyautogui",
        "--hidden-import", "windnd",
        main_script,
    ]

    print("=" * 50)
    print("开始打包 Auto Painter...")
    print("=" * 50)
    print(f"命令: {' '.join(cmd)}\n")

    subprocess.check_call(cmd, cwd=script_dir)

    print("\n" + "=" * 50)
    print("✅ 打包完成！")
    print(f"   输出: {os.path.join(script_dir, 'dist', 'AutoPainter.exe')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
