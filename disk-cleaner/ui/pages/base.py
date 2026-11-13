import customtkinter as ctk

from .. import theme


class BasePage(ctk.CTkFrame):
    """所有页面的基类：带标题和副标题，切换到本页时调用 on_show()。"""

    title = ""
    subtitle = ""

    def __init__(self, master, app, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        ctk.CTkLabel(header, text=self.title, font=theme.font(22, "bold"), anchor="w").pack(fill="x")
        if self.subtitle:
            ctk.CTkLabel(header, text=self.subtitle, font=theme.font(13),
                         text_color=theme.MUTED_TEXT, anchor="w").pack(fill="x", pady=(2, 0))

    def on_show(self):
        pass

    def is_busy(self) -> bool:
        """有后台任务在跑时返回 True（关闭窗口前会询问）。"""
        return False
