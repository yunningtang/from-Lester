"""颜色和字体：墨黑、石灰、米色。颜色克制，只有危险操作用一点红。"""
import sys
from pathlib import Path

if sys.platform == "win32":
    FONT_FAMILY = "Microsoft YaHei UI"
    LIGHT_FAMILY = "Microsoft YaHei UI Light"  # 大数字用细字重
else:
    FONT_FAMILY = "Noto Sans CJK SC"
    LIGHT_FAMILY = FONT_FAMILY

THEME_FILE = str(Path(__file__).with_name("stone_theme.json"))
SIDEBAR_WIDTH = 150

# (浅色, 深色)
BG = ("#EFEBE3", "#1B1A18")
INK = ("#2A2825", "#E9E4DA")
INK_TEXT = ("#F4F1EA", "#1B1A18")    # 放在墨色上的字
MUTED_TEXT = ("#8C877F", "#8E8A82")
LINE = ("#D6D0C5", "#3A3834")
SIDEBAR_BG = ("#E7E2D8", "#211F1D")
CARD_BG = ("#F7F4EE", "#25231F")
CARD_BORDER = LINE
ROW_HOVER = ("#E3DED4", "#2E2C29")
DANGER = ("#A8483C", "#C7685B")
WARN = ("#B0832A", "#C99A45")
OK = INK

# 石头地图：每类空间一种颜色（浅色模式, 深色模式）
PEBBLE = {
    "user":   {"fill": ("#2A2825", "#D9D3C7"), "text": ("#F1EDE5", "#1B1A18")},  # 你的文件
    "app":    {"fill": ("#76726B", "#8B877F"), "text": ("#F1EDE5", "#1B1A18")},  # 程序和应用数据
    "cache":  {"fill": ("#CFC9BE", "#4A4743"), "text": ("#2A2825", "#E9E4DA")},  # 缓存，可清理
    "system": {"fill": ("#E2DDD3", "#33312D"), "text": ("#6F6B64", "#A39E95")},  # 系统和其他
    "free":   {"fill": ("#EFEBE3", "#1B1A18"), "text": ("#5E5A54", "#B5B0A6"),
               "line": ("#C9C3B8", "#45423D")},                                  # 可用空间（等高线）
}
PEBBLE_HOVER_OUTLINE = ("#2A2825", "#F1EDE5")

KIND_NAMES = {"user": "你的文件", "app": "程序和应用数据", "cache": "缓存，可清理",
              "system": "系统和其他", "free": "可用"}


def pick(pair):
    """按当前外观模式取 (浅色, 深色) 里的一个，给 tk.Canvas 这类不认元组的控件用。"""
    import customtkinter as ctk
    return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]


def usage_color(percent: float):
    if percent >= 90:
        return DANGER
    if percent >= 80:
        return WARN
    return OK


def font(size: int = 13, weight: str = "normal", light: bool = False):
    import customtkinter as ctk
    return ctk.CTkFont(family=LIGHT_FAMILY if light else FONT_FAMILY, size=size, weight=weight)
