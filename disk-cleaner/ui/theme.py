"""颜色和字体。颜色保持克制：只有磁盘快满和危险操作用颜色。"""
import sys

FONT_FAMILY = "Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC"

SIDEBAR_WIDTH = 150

# (浅色, 深色)
SIDEBAR_BG = ("#ECEEF1", "#1F2124")
CARD_BG = ("#FFFFFF", "#2A2C30")
CARD_BORDER = ("#DADDE2", "#3A3D42")
MUTED_TEXT = ("#6B7078", "#9AA0A8")
ROW_HOVER = ("#F2F4F7", "#33363B")

OK = ("#3B82F6", "#4C8DF6")      # 普通进度
WARN = ("#E0A100", "#E8B020")    # 超过 80%
DANGER = ("#D64545", "#E05A5A")  # 超过 90%


def usage_color(percent: float):
    if percent >= 90:
        return DANGER
    if percent >= 80:
        return WARN
    return OK


def font(size: int = 13, weight: str = "normal"):
    import customtkinter as ctk
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
