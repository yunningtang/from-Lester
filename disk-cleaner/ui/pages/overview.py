"""概览：各磁盘用量 + 功能入口卡片。"""
import os
import shutil

import customtkinter as ctk

from core.utils import human_size

from .. import theme
from .base import BasePage


def list_drives() -> list[str]:
    try:
        import psutil
        parts = psutil.disk_partitions(all=False)
        drives = [p.mountpoint for p in parts
                  if "cdrom" not in p.opts and p.fstype and not p.mountpoint.startswith(("/snap", "/boot"))]
        if drives:
            return drives
    except Exception:
        pass
    return [os.environ.get("SystemDrive", "C:") + "\\"] if os.name == "nt" else ["/"]


FEATURES = [
    ("large", "大文件", "找出占空间最多的文件，自己决定留不留"),
    ("duplicates", "重复文件", "内容完全一样的文件，只留一份"),
    ("organize", "文件整理", "把下载文件夹按类型分好"),
    ("temp", "临时文件", "%TEMP% 和浏览器缓存，通常可安全清理"),
]


class OverviewPage(BasePage):
    title = "概览"
    subtitle = "磁盘用量和可以清理的地方"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        body.grid_columnconfigure((0, 1), weight=1, uniform="c")
        self.body = body

        self.drive_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.drive_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12)
        self.drive_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="清理功能", font=theme.font(15, "bold"), anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(18, 6))
        for i, (key, name, desc) in enumerate(FEATURES):
            self._feature_card(body, key, name, desc).grid(
                row=2 + i // 2, column=i % 2, sticky="nsew", padx=12, pady=6)

        tip = ("系统文件的清理（Windows 更新缓存、旧系统还原点等）请用 Windows 自带的"
               "“存储感知”：设置 → 系统 → 存储。它比任何第三方工具都安全。")
        ctk.CTkLabel(body, text=tip, font=theme.font(12), text_color=theme.MUTED_TEXT,
                     anchor="w", justify="left", wraplength=620).grid(
            row=10, column=0, columnspan=2, sticky="ew", padx=12, pady=(16, 4))

    def _feature_card(self, parent, key, name, desc):
        card = ctk.CTkFrame(parent, fg_color=theme.CARD_BG, border_color=theme.CARD_BORDER,
                            border_width=1, corner_radius=10, cursor="hand2")
        ctk.CTkLabel(card, text=name, font=theme.font(15, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        ctk.CTkLabel(card, text=desc, font=theme.font(12), text_color=theme.MUTED_TEXT,
                     anchor="w", justify="left", wraplength=260).pack(fill="x", padx=16, pady=(0, 14))

        def go(_e=None):
            self.app.show_page(key)
        for w in [card, *card.winfo_children()]:
            w.bind("<Button-1>", go)
        return card

    def on_show(self):
        for w in self.drive_frame.winfo_children():
            w.destroy()
        for row, mount in enumerate(list_drives()):
            try:
                u = shutil.disk_usage(mount)
            except OSError:
                continue
            if u.total < 1024 ** 3:  # 忽略很小的分区（恢复分区等）
                continue
            pct = u.used / u.total * 100 if u.total else 0
            card = ctk.CTkFrame(self.drive_frame, fg_color=theme.CARD_BG,
                                border_color=theme.CARD_BORDER, border_width=1, corner_radius=10)
            card.grid(row=row, column=0, sticky="ew", pady=6)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=f"磁盘 {mount}", font=theme.font(15, "bold"), anchor="w").grid(
                row=0, column=0, sticky="w", padx=16, pady=(14, 0))
            ctk.CTkLabel(card, text=f"剩余 {human_size(u.free)}", font=theme.font(15, "bold"),
                         text_color=theme.usage_color(pct)
                         if pct >= 80 else None, anchor="e").grid(
                row=0, column=1, sticky="e", padx=16, pady=(14, 0))
            bar = ctk.CTkProgressBar(card, height=12, corner_radius=6,
                                     progress_color=theme.usage_color(pct))
            bar.set(pct / 100)
            bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=8)
            ctk.CTkLabel(card, text=f"已用 {human_size(u.used)} / 共 {human_size(u.total)}（{pct:.0f}%）",
                         font=theme.font(12), text_color=theme.MUTED_TEXT, anchor="w").grid(
                row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 12))
