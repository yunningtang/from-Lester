"""石头地图控件：每块石头代表一类空间，面积和大小成比例。"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import zlib
from typing import Callable

from core.space import Category
from core.utils import human_size

from . import theme
from .pebble_layout import area, bbox, centroid, inset, inner_box, layout, rounded

GAP = 5          # 石头之间缝隙的一半
CONTOUR_STEP = 9  # 可用空间等高线间距


class PebbleMap(tk.Canvas):
    def __init__(self, master, on_click: Callable[[Category], None] | None = None, **kw):
        super().__init__(master, highlightthickness=0, bd=0, **kw)
        self.blocks: list[Category] = []
        self.on_click = on_click
        self._tags: dict[str, Category] = {}
        self._hover: str | None = None
        self._redraw_job = None
        self.f_big = tkfont.Font(family=theme.FONT_FAMILY, size=13)
        self.f_mid = tkfont.Font(family=theme.FONT_FAMILY, size=11)
        self.f_small = tkfont.Font(family=theme.FONT_FAMILY, size=10)
        self.bind("<Configure>", lambda e: self._schedule())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._on_press)

    def set_blocks(self, blocks: list[Category]):
        self.blocks = blocks
        self._schedule()

    def _schedule(self):
        if self._redraw_job:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(30, self.redraw)

    def redraw(self):
        self._redraw_job = None
        self.delete("all")
        self._tags.clear()
        self._hover = None
        self.configure(bg=theme.pick(theme.BG))
        w, h = self.winfo_width(), self.winfo_height()
        if w < 50 or h < 50 or not self.blocks:
            return
        # 种子由块的名字决定：同一台电脑每次形状一样，不会每次刷新都乱跳
        seed = zlib.crc32("|".join(b.key for b in self.blocks).encode())
        polys = layout([(b.key, b.size) for b in self.blocks],
                       [(0, 0), (w, 0), (w, h), (0, h)], seed=seed)
        for b in self.blocks:
            poly = polys.get(b.key)
            if poly:
                self._draw_block(b, poly)

    def _draw_block(self, b: Category, poly):
        shape = inset(poly, GAP)
        if not shape:
            return
        style = theme.PEBBLE[b.kind]
        r = min(26.0, 0.32 * area(shape) ** 0.5)
        tag = f"b_{b.key}"
        self._tags[tag] = b
        if b.kind == "free":
            # 可用空间画成一圈圈等高线，像沙地上耙出的纹路
            line = theme.pick(style["line"])
            self.create_polygon(*_flat(rounded(shape, r)), fill=theme.pick(style["fill"]),
                                outline=line, width=1, tags=(tag, "shape"))
            # 中间留出放文字的地方
            need_w = max(self.f_big.measure(b.name), self.f_small.measure(human_size(b.size))) + 40
            d = CONTOUR_STEP
            while True:
                ring = inset(shape, d)
                if not ring:
                    break
                rw, rh = _size(ring)
                if rw < need_w or rh < 64:
                    break
                self.create_polygon(*_flat(rounded(ring, max(3.0, r - d * 0.6))), fill="",
                                    outline=line, width=1, tags=(tag,))
                d += CONTOUR_STEP
        else:
            self.create_polygon(*_flat(rounded(shape, r)), fill=theme.pick(style["fill"]),
                                outline="", tags=(tag, "shape"))
        self._label(b, shape, tag, theme.pick(style["text"]))

    def _label(self, b: Category, shape, tag, color):
        cx, cy = centroid(shape)
        bw, bh = inner_box(shape)
        size = human_size(b.size)
        bw, bh = bw / 0.7 * 0.8 - 14, bh / 0.7 - 12  # 石头是圆角的，文字两边多留点
        if bh >= 44 and self.f_small.measure(size) <= bw:
            f = self.f_big if self.f_big.measure(b.name) <= bw else self.f_mid
            name = self._fit(b.name, f, bw)
            if name:
                self.create_text(cx, cy - 9, text=name, fill=color, font=f, tags=(tag,))
                self.create_text(cx, cy + 11, text=size, fill=color, font=self.f_small, tags=(tag,))
                return
        if bh >= 18 and self.f_small.measure(size) <= bw:
            self.create_text(cx, cy, text=size, fill=color, font=self.f_small, tags=(tag,))
        elif bw >= 10 and bh >= 10:
            self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=color, outline="", tags=(tag,))

    @staticmethod
    def _fit(text, font, width):
        """放得下就原样返回，放不下就截断加省略号，太窄（少于 3 个字）返回 None。"""
        if font.measure(text) <= width:
            return text
        for n in range(len(text) - 1, 2, -1):
            t = text[:n] + "…"
            if font.measure(t) <= width:
                return t
        return None

    # ---------- 悬停提示 ----------
    def _tag_at(self, x, y):
        for item in reversed(self.find_overlapping(x, y, x, y)):
            for t in self.gettags(item):
                if t.startswith("b_"):
                    return t
        return None

    def _on_motion(self, e):
        self._set_hover(self._tag_at(e.x, e.y), e.x, e.y)

    def _on_press(self, e):
        t = self._tag_at(e.x, e.y)
        if t and self.on_click:
            self.on_click(self._tags[t])

    def _set_hover(self, tag, x=0, y=0):
        self.delete("tip")
        if self._hover and self._hover != tag:
            for item in self.find_withtag(self._hover):
                if "shape" in self.gettags(item):
                    self.itemconfigure(item, outline="" if self._tags[self._hover].kind != "free"
                                       else theme.pick(theme.PEBBLE["free"]["line"]), width=1)
        self._hover = tag
        if not tag:
            return
        b = self._tags[tag]
        for item in self.find_withtag(tag):
            if "shape" in self.gettags(item):
                self.itemconfigure(item, outline=theme.pick(theme.PEBBLE_HOVER_OUTLINE), width=2)
        lines = [f"{b.name}  {human_size(b.size)}",
                 theme.KIND_NAMES.get(b.kind, "") if b.kind != "free" else ""]
        if b.note:
            lines.append(b.note)
        if b.paths:
            lines.append(b.paths[0] + (f" 等 {len(b.paths)} 处" if len(b.paths) > 1 else ""))
        text = "\n".join(line for line in lines if line)
        tid = self.create_text(0, 0, text=text, anchor="nw", fill=theme.pick(theme.INK_TEXT),
                               font=(theme.FONT_FAMILY, 10), tags=("tip",))
        x0, y0, x1, y1 = self.bbox(tid)
        tw, th = x1 - x0 + 16, y1 - y0 + 12
        px = min(x + 14, self.winfo_width() - tw - 4)
        py = y + 18 if y + 18 + th < self.winfo_height() else y - th - 8
        self.coords(tid, px + 8, py + 6)
        bg = self.create_rectangle(px, py, px + tw, py + th, fill=theme.pick(theme.INK),
                                   outline="", tags=("tip",))
        self.tag_lower(bg, tid)


def _flat(pts):
    return [c for p in pts for c in p]


def _size(poly):
    x0, y0, x1, y1 = bbox(poly)
    return x1 - x0, y1 - y0
