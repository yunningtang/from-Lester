"""图形界面入口：python main.py"""
import ctypes
import sys

from ui.app import App


def main():
    if sys.platform == "win32":
        try:  # 高分屏下字体清晰
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
