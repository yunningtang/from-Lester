"""留白：入口。

优先用 pywebview 打开新界面（webui/）；没装 pywebview 时退回旧的 CustomTkinter 界面。
"""
import os
import sys


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def run_web():
    import webview  # pywebview

    from core.api import Api
    api = Api()
    window = webview.create_window(
        "留白", resource("webui", "index.html"), js_api=api,
        width=1200, height=760, min_size=(960, 620),
        frameless=True, easy_drag=False, background_color="#FCFBF8",
    )
    api.window = window
    webview.start()


def run_tk():
    import ctypes
    if sys.platform == "win32":
        try:  # 高分屏下字体清晰
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    from ui.app import App
    App().mainloop()


def main():
    if "--tk" not in sys.argv:
        try:
            run_web()
            return
        except ImportError:
            pass
    run_tk()


if __name__ == "__main__":
    main()
