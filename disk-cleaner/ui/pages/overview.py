"""概览：左边是能清理多少和可放心清理的列表，右边是石头地图。"""
from __future__ import annotations

import queue
import threading
from tkinter import messagebox

import customtkinter as ctk

from core import cleanables, cleaner, space
from core.space import Category, SpaceReport
from core.utils import human_size

from .. import confirm, theme
from ..pebble_map import PebbleMap
from .base import BasePage

LEFT_WIDTH = 360


def split_size(n: int) -> tuple[str, str]:
    """1234567890 → ('1.1', 'GB')；大数字和单位分开排版。"""
    num, unit = human_size(n).split(" ")
    if unit == "GB" and float(num) >= 100:
        num = f"{float(num):.0f}"
    return num, unit


class OverviewPage(BasePage):
    title = ""

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=0, minsize=LEFT_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._started = False
        self.report: SpaceReport | None = None
        self.partial: list[Category] = []
        self.items: list[cleanables.Cleanable] = []
        self.vars: dict[str, ctk.BooleanVar] = {}
        self.drive = space.system_drive()

        left = ctk.CTkFrame(self, fg_color="transparent", width=LEFT_WIDTH)
        left.grid(row=1, column=0, sticky="nsew", padx=(28, 8), pady=(22, 22))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(5, weight=1)

        # 大数字
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        self.big = ctk.CTkLabel(top, text="—", font=theme.font(64, light=True), anchor="sw")
        self.big.pack(side="left")
        self.unit = ctk.CTkLabel(top, text="", font=theme.font(18, light=True), anchor="sw")
        self.unit.pack(side="left", anchor="s", pady=(0, 12), padx=(4, 12))
        self.caption = ctk.CTkLabel(top, text="", font=theme.font(12), text_color=theme.MUTED_TEXT,
                                    anchor="w", justify="left")
        self.caption.pack(side="left", anchor="s", pady=(0, 14))

        self.headline = ctk.CTkLabel(left, text="正在统计空间…", font=theme.font(17, "bold"),
                                     anchor="w", justify="left", wraplength=LEFT_WIDTH)
        self.headline.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        self.explain = ctk.CTkLabel(left, text="", font=theme.font(12), text_color=theme.MUTED_TEXT,
                                    anchor="w", justify="left", wraplength=LEFT_WIDTH)
        self.explain.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        # 列表头
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=3, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="●", font=theme.font(12), width=14).grid(row=0, column=0)
        ctk.CTkLabel(head, text="可放心清理", font=theme.font(13, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(6, 0))
        self.sel_label = ctk.CTkLabel(head, text="", font=theme.font(12), anchor="e")
        self.sel_label.grid(row=0, column=2, sticky="e")
        self.all_link = ctk.CTkLabel(head, text="全选", font=ctk.CTkFont(
            family=theme.FONT_FAMILY, size=12, underline=True), cursor="hand2")
        self.all_link.grid(row=0, column=3, padx=(8, 0))
        self.all_link.bind("<Button-1>", lambda e: self._select_all())
        ctk.CTkFrame(left, height=1, fg_color=theme.LINE).grid(row=4, column=0, sticky="ew", pady=(6, 0))

        self.list = ctk.CTkFrame(left, fg_color="transparent", corner_radius=0)
        self.list.grid(row=5, column=0, sticky="new")
        self.list.grid_columnconfigure(0, weight=1)

        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        self.clean_btn = ctk.CTkButton(btns, text="移到回收站", height=38, font=theme.font(13, "bold"),
                                       state="disabled", command=self._clean)
        self.clean_btn.pack(side="left")
        self.rescan_btn = ctk.CTkButton(btns, text="重新扫描", height=38, width=96,
                                        font=theme.font(13), fg_color="transparent", border_width=1,
                                        text_color=theme.INK, hover_color=theme.ROW_HOVER,
                                        command=self.rescan)
        self.rescan_btn.pack(side="left", padx=(10, 0))
        self.status = ctk.CTkLabel(left, text="", font=theme.font(11), text_color=theme.MUTED_TEXT,
                                   anchor="w")
        self.status.grid(row=7, column=0, sticky="ew", pady=(6, 0))

        self.map = PebbleMap(self, on_click=self._open_block)
        self.map.grid(row=1, column=1, sticky="nsew", padx=(8, 22), pady=(18, 22))

    # ---------- 扫描 ----------
    def on_show(self):
        if not self._started:
            self._started = True
            self.rescan()
        else:
            self.map.redraw()

    def is_busy(self):
        return self._worker is not None and self._worker.is_alive()

    def rescan(self):
        if self.is_busy():
            return
        self._cancel.clear()
        self.report = None
        self.partial = []
        self.items = []
        self._render_list()
        self.headline.configure(text="正在统计空间…")
        self.explain.configure(text="只读取文件大小，不会改动任何文件。第一次可能要一两分钟。")
        self.rescan_btn.configure(state="disabled")
        self.clean_btn.configure(state="disabled")
        try:
            u = space.shutil.disk_usage(self.drive)
            self._usage = (u.used, u.free)
        except OSError:
            self._usage = (0, 0)
        self._update_numbers()

        def work():
            try:
                self._queue.put(("status", "正在查找可清理的缓存…"))
                items = cleanables.find_all(cancel=self._cancel)
                self._queue.put(("cleanables", items))
                subtract = [(p, s) for c in items for p, s in c.items]
                rep = space.measure(self.drive, self._cancel, subtract=subtract,
                                    on_category=lambda c: self._queue.put(("category", c)))
                self._queue.put(("done", rep))
            except Exception as e:  # noqa: BLE001
                self._queue.put(("error", str(e)))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self.after(80, self._poll)

    def _poll(self):
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if kind == "status":
                    self.status.configure(text=data)
                elif kind == "cleanables":
                    self.items = data
                    self._render_list()
                    self._update_numbers()
                elif kind == "category":
                    self.partial.append(data)
                    self.status.configure(text=f"已统计：{data.name}  {human_size(data.size)}")
                    self._update_map()
                elif kind == "done":
                    self.report = data
                    self._finish()
                    return
                elif kind == "error":
                    self.status.configure(text=f"统计出错：{data}")
                    self.rescan_btn.configure(state="normal")
                    return
                elif kind == "planned":
                    self._planned(data)
                    return
                elif kind == "cleaned":
                    self._clean_finished(data)
                    return
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _finish(self):
        self.rescan_btn.configure(state="normal")
        self.status.configure(text=f"磁盘 {self.drive} · 共 {human_size(self.report.total)}")
        self._update_map()
        self._update_numbers()
        user = sorted((c for c in self.report.categories if c.size > 0), key=lambda c: -c.size)[:3]
        if user:
            parts = [f"{c.name}（{human_size(c.size)}）" for c in user]
            joined = "、".join(parts[:-1]) + ("和" if len(parts) > 1 else "") + parts[-1]
            self.explain.configure(text=f"空间主要用在{joined}。点地图上的石头可以查看里面的大文件。")

    def _update_map(self):
        used, free = self._usage
        safe_total = sum(c.size for c in self.items)
        if self.report:
            blocks = self.report.blocks(safe_total)
        else:
            blocks = [c for c in self.partial if c.size > 0]
            if safe_total:
                blocks.append(Category("safe", "可放心清理", "cache", size=safe_total))
            rest = used - sum(b.size for b in blocks)
            if rest > 0:
                blocks.append(Category("pending", "还在统计…", "system", size=rest))
            blocks.append(Category("free", "可用", "free", size=free))
        self.map.set_blocks(blocks)

    # ---------- 左侧数字和列表 ----------
    def _selected(self) -> list[cleanables.Cleanable]:
        return [c for c in self.items if self.vars.get(c.key) and self.vars[c.key].get()]

    def _update_numbers(self):
        used, free = self._usage
        sel = sum(c.size for c in self._selected())
        safe_total = sum(c.size for c in self.items)
        num, unit = split_size(free + sel)
        self.big.configure(text=num)
        self.unit.configure(text=unit)
        self.caption.configure(text=f"清理所选后可用\n（现在 {human_size(free)}）")
        if self.items:
            self.headline.configure(text=f"可以放心清理 {human_size(safe_total)}。")
        elif self.report or self.partial:
            self.headline.configure(text="没有找到需要清理的缓存。")
        self.sel_label.configure(text=f"已选 {human_size(sel)} / {human_size(safe_total)}")
        n = len(self._selected())
        self.clean_btn.configure(text=f"移到回收站（{n} 项）" if n else "移到回收站",
                                 state="normal" if n and not self.is_busy() else "disabled")

    def _render_list(self):
        for w in self.list.winfo_children():
            w.destroy()
        self.vars = {}
        if not self.items:
            ctk.CTkLabel(self.list, text="正在查找…" if self.is_busy() else "没有可清理的项目",
                         font=theme.font(12), text_color=theme.MUTED_TEXT, anchor="w").grid(
                row=0, column=0, sticky="ew", pady=10)
            return
        for i, c in enumerate(self.items):
            var = ctk.BooleanVar(value=c.default)
            self.vars[c.key] = var
            row = ctk.CTkFrame(self.list, fg_color="transparent")
            row.grid(row=2 * i, column=0, sticky="ew")
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkCheckBox(row, text=c.name, variable=var, font=theme.font(13),
                            checkbox_width=18, checkbox_height=18,
                            command=self._update_numbers).grid(row=0, column=0, sticky="w", pady=8)
            ctk.CTkLabel(row, text=human_size(c.size), font=theme.font(13), anchor="e").grid(
                row=0, column=1, sticky="e", padx=(8, 4))
            ctk.CTkFrame(self.list, height=1, fg_color=theme.LINE).grid(row=2 * i + 1, column=0, sticky="ew")

    def _select_all(self):
        on = not all(v.get() for v in self.vars.values())
        for v in self.vars.values():
            v.set(on)
        self._update_numbers()

    # ---------- 清理 ----------
    def _clean(self):
        """先在后台预检，再把结果给用户确认，确认后再在后台执行。"""
        sel = self._selected()
        if not sel:
            return
        self.clean_btn.configure(state="disabled", text="正在检查…")
        self.rescan_btn.configure(state="disabled")
        self.status.configure(text="正在检查每一项能不能安全地移到回收站…")
        n = sum(len(c.items) for c in sel)

        def work():
            try:
                self._queue.put(("planned", (cleanables.plan(sel), n)))
            except Exception as e:  # noqa: BLE001
                self._queue.put(("error", str(e)))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self.after(80, self._poll)

    def _planned(self, data):
        if self._worker:
            self._worker.join(timeout=2)
        plan, n = data
        if not confirm.ask(plan, f"{len(plan.go)} 项缓存"):
            self.status.configure(text="已取消，没有移动任何文件。")
            self.rescan_btn.configure(state="normal")
            self._update_numbers()
            return
        self.clean_btn.configure(state="disabled", text="正在移动…")
        self.status.configure(text="正在移到回收站…")

        def work():
            rep = cleaner.execute(plan)
            rep.failed = plan.refused + rep.failed
            self._queue.put(("cleaned", rep))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self.after(80, self._poll)

    def _clean_finished(self, rep):
        messagebox.showinfo("完成", confirm.summary(rep))
        self.rescan()

    def _open_block(self, b: Category):
        if b.paths and b.kind == "user":
            page = self.app.show_page("large")
            page.path_var.set(b.paths[0])
