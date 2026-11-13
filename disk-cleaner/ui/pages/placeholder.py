import customtkinter as ctk

from .. import theme
from .base import BasePage


class PlaceholderPage(BasePage):
    def __init__(self, master, app, title: str, plan: str):
        self.title = title
        self.subtitle = "这个功能还在开发中"
        super().__init__(master, app)
        card = ctk.CTkFrame(self, fg_color=theme.CARD_BG, border_color=theme.CARD_BORDER,
                            border_width=1, corner_radius=10)
        card.grid(row=1, column=0, sticky="ew", padx=24, pady=8)
        ctk.CTkLabel(card, text="计划", font=theme.font(14, "bold"), anchor="w").pack(
            fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(card, text=plan, font=theme.font(13), text_color=theme.MUTED_TEXT,
                     anchor="w", justify="left", wraplength=560).pack(fill="x", padx=18, pady=(0, 16))
