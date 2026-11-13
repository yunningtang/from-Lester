"""主窗口：左侧 150px 导航栏 + 右侧内容区。"""
from tkinter import messagebox

import customtkinter as ctk

from . import theme
from .pages import LargeFilesPage, LogPage, OverviewPage, PlaceholderPage

# (key, 导航文字, 页面构造函数)；以后加功能只要在这里加一项
NAV = [
    ("overview", "概览", OverviewPage),
    ("large", "大文件", LargeFilesPage),
    ("duplicates", "重复文件", lambda m, a: PlaceholderPage(
        m, a, "重复文件", "先按大小分组，再比较文件开头的哈希，最后比较完整 SHA-256。"
                       "每组默认保留最早的一份，其余默认不勾选。")),
    ("organize", "文件整理", lambda m, a: PlaceholderPage(
        m, a, "文件整理", "把下载文件夹按类型（图片、文档、安装包、压缩包、视频）或按月份分到子文件夹。"
                       "先预览移动计划，确认后再移动，并记录日志以便撤销。")),
    ("temp", "临时文件", lambda m, a: PlaceholderPage(
        m, a, "临时文件", "清理 %TEMP%、Chrome / Edge 缓存、下载文件夹里的旧安装包。"
                       "这些默认勾选；正在被占用的文件自动跳过。")),
    ("memory", "内存占用", lambda m, a: PlaceholderPage(
        m, a, "内存占用", "用 psutil 列出占内存最多的程序，由你决定是否关闭。"
                       "不做“一键释放内存”，Windows 自己管理内存更好。")),
    (None, None, None),  # 分隔，下面的项目贴底
    ("log", "操作日志", LogPage),
    ("settings", "设置", lambda m, a: PlaceholderPage(
        m, a, "设置", "外观（跟随系统 / 浅色 / 深色）、自定义排除目录、日志保留天数。")),
]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        self.title("磁盘清理")
        self.geometry("980x640")
        self.minsize(820, 520)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=theme.SIDEBAR_WIDTH, corner_radius=0,
                                    fg_color=theme.SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.sidebar, text="磁盘清理", font=theme.font(17, "bold")).grid(
            row=0, column=0, pady=(20, 16))

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.buttons: dict[str, ctk.CTkButton] = {}
        self._factories = {}
        row = 1
        for key, label, factory in NAV:
            if key is None:
                self.sidebar.grid_rowconfigure(row, weight=1)
                row += 1
                continue
            btn = ctk.CTkButton(self.sidebar, text=label, anchor="w", height=36, corner_radius=8,
                                font=theme.font(14), fg_color="transparent",
                                text_color=("gray15", "gray85"), hover_color=theme.ROW_HOVER,
                                command=lambda k=key: self.show_page(k))
            btn.grid(row=row, column=0, sticky="ew", padx=10, pady=2)
            self.buttons[key] = btn
            self._factories[key] = factory
            row += 1
        self.sidebar.grid_rowconfigure(row, minsize=14)

        self.current: str | None = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_page("overview")

    def show_page(self, key: str):
        if key not in self.pages:  # 第一次打开时才创建页面
            page = self._factories[key](self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        for k, btn in self.buttons.items():
            btn.configure(fg_color=theme.CARD_BG if k == key else "transparent",
                          font=theme.font(14, "bold" if k == key else "normal"))
        self.pages[key].tkraise()
        self.current = key
        self.pages[key].on_show()

    def _on_close(self):
        if any(p.is_busy() for p in self.pages.values()):
            if not messagebox.askyesno("还在运行", "有任务正在进行，确定要退出吗？"):
                return
            for p in self.pages.values():
                cancel = getattr(p, "_cancel", None)
                if cancel is not None:
                    cancel.set()
        self.destroy()
