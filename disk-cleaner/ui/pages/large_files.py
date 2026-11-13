"""大文件页面：扫描（后台线程）→ 勾选 → 确认 → 移到回收站。"""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.cleaner import move_to_trash
from core.oplog import open_in_explorer
from core.safety import is_protected
from core.scanner import FileEntry, scan_large_files
from core.utils import format_time, human_size

from .. import theme
from .base import BasePage

SIZE_OPTIONS = {"50 MB": 50, "100 MB": 100, "500 MB": 500, "1 GB": 1024}
MAX_ROWS = 300  # 界面最多显示的行数，太多会卡


class LargeFilesPage(BasePage):
    title = "大文件"
    subtitle = "找出占空间最多的文件。默认都不勾选，请自己判断哪些可以删。"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(3, weight=1)
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._rows: list[tuple[FileEntry, ctk.BooleanVar, ctk.CTkFrame]] = []

        # 第 1 行：路径 + 大小 + 扫描按钮
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(4, 6))
        bar.grid_columnconfigure(0, weight=1)
        self.path_var = ctk.StringVar(value=str(Path.home() / "Downloads"))
        ctk.CTkEntry(bar, textvariable=self.path_var, font=theme.font(13), height=34).grid(
            row=0, column=0, sticky="ew")
        ctk.CTkButton(bar, text="浏览…", width=70, height=34, font=theme.font(13),
                      fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
                      command=self._browse).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkLabel(bar, text="大于", font=theme.font(13)).grid(row=0, column=2, padx=(14, 4))
        self.size_var = ctk.StringVar(value="100 MB")
        ctk.CTkOptionMenu(bar, values=list(SIZE_OPTIONS), variable=self.size_var, width=90,
                          height=34, font=theme.font(13), text_color="white").grid(row=0, column=3)
        self.scan_btn = ctk.CTkButton(bar, text="开始扫描", width=100, height=34,
                                      font=theme.font(13, "bold"), command=self._toggle_scan)
        self.scan_btn.grid(row=0, column=4, padx=(10, 0))

        # 第 2 行：进度
        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 6))
        prog.grid_columnconfigure(0, weight=1)
        # 进度条只在扫描时显示
        self.progress = ctk.CTkProgressBar(prog, mode="indeterminate", height=6)
        self.status = ctk.CTkLabel(prog, text="选择一个文件夹，然后点“开始扫描”。扫描只读，不会改动任何文件。",
                                   font=theme.font(12), text_color=theme.MUTED_TEXT, anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # 第 3 行：结果列表
        self.list = ctk.CTkScrollableFrame(self, fg_color=theme.CARD_BG, border_color=theme.CARD_BORDER,
                                           border_width=1, corner_radius=10)
        self.list.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.list.grid_columnconfigure(0, weight=1)
        self.empty = ctk.CTkLabel(self.list, text="还没有结果", font=theme.font(13),
                                  text_color=theme.MUTED_TEXT)
        self.empty.grid(row=0, column=0, pady=40)

        # 第 4 行：底部操作栏
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 18))
        foot.grid_columnconfigure(1, weight=1)
        self.all_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(foot, text="全选", variable=self.all_var, font=theme.font(13),
                        command=self._toggle_all, width=60).grid(row=0, column=0)
        self.sel_label = ctk.CTkLabel(foot, text="已选 0 项，共 0 B", font=theme.font(13), anchor="w")
        self.sel_label.grid(row=0, column=1, sticky="w", padx=12)
        self.trash_btn = ctk.CTkButton(foot, text="移到回收站", width=130, height=36,
                                       font=theme.font(13, "bold"), state="disabled",
                                       fg_color=theme.DANGER, hover_color=("#B83A3A", "#C24A4A"),
                                       command=self._trash_selected)
        self.trash_btn.grid(row=0, column=2)

    # ---------- 扫描 ----------
    def is_busy(self):
        return self._worker is not None and self._worker.is_alive()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.path_var.get() or str(Path.home()))
        if d:
            self.path_var.set(os.path.normpath(d))

    def _toggle_scan(self):
        if self.is_busy():
            self._cancel.set()
            self.scan_btn.configure(text="正在取消…", state="disabled")
            return
        root = self.path_var.get().strip()
        if not os.path.isdir(root):
            messagebox.showwarning("路径无效", f"找不到文件夹：\n{root}")
            return
        if is_protected(root):
            messagebox.showwarning("受保护的目录", "这是系统目录，为了安全不扫描。")
            return
        self._clear_rows()
        self._cancel.clear()
        min_size = SIZE_OPTIONS[self.size_var.get()] * 1024 * 1024
        self.scan_btn.configure(text="取消")
        self.trash_btn.configure(state="disabled")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.start()
        self._set_status("正在扫描…")

        def work():
            try:
                res = scan_large_files(root, min_size, limit=MAX_ROWS, cancel=self._cancel,
                                       on_progress=lambda p: self._queue.put(
                                           ("progress", (p.files, p.current))))
                self._queue.put(("done", res))
            except Exception as e:  # noqa: BLE001
                self._queue.put(("error", str(e)))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self.after(100, self._poll)

    def _poll(self):
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if kind == "progress":
                    files, current = data
                    self._set_status(f"已扫描 {files:,} 个文件 · {self._short(current, 70)}")
                elif kind == "done":
                    self._scan_finished(data)
                    return
                elif kind == "error":
                    self._scan_stopped()
                    self._set_status(f"扫描出错：{data}")
                    return
                elif kind == "trashed":
                    self._trash_finished(data)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _scan_stopped(self):
        self.progress.stop()
        self.progress.grid_remove()
        self.scan_btn.configure(text="开始扫描", state="normal")

    def _scan_finished(self, res):
        self._scan_stopped()
        head = "已取消。" if res.cancelled else "扫描完成。"
        total = sum(f.size for f in res.files)
        msg = (f"{head}共 {res.progress.files:,} 个文件，用时 {res.seconds:.1f} 秒；"
               f"找到 {len(res.files)} 个大文件，合计 {human_size(total)}")
        if res.skipped:
            msg += f"；跳过 {len(res.skipped)} 个系统或无权限目录"
        self._set_status(msg)
        self._show_rows(res.files)

    # ---------- 列表 ----------
    def _clear_rows(self):
        for _, _, frame in self._rows:
            frame.destroy()
        self._rows.clear()
        self.all_var.set(False)
        self.empty.grid(row=0, column=0, pady=40)
        self._update_selection()

    def _show_rows(self, files: list[FileEntry]):
        self._clear_rows()
        if not files:
            self.empty.configure(text="没有找到这么大的文件")
            return
        self.empty.grid_forget()
        for i, f in enumerate(files):
            var = ctk.BooleanVar(value=False)  # 大文件有风险，默认不勾选
            row = ctk.CTkFrame(self.list, fg_color="transparent", corner_radius=6)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=1)
            row.grid_columnconfigure(2, weight=1)
            ctk.CTkCheckBox(row, text="", variable=var, width=24,
                            command=self._update_selection).grid(row=0, column=0, rowspan=2, padx=(8, 4))
            ctk.CTkLabel(row, text=human_size(f.size), font=theme.font(13, "bold"), width=80,
                         anchor="e").grid(row=0, column=1, rowspan=2, padx=(0, 12))
            ctk.CTkLabel(row, text=os.path.basename(f.path), font=theme.font(13), anchor="w").grid(
                row=0, column=2, sticky="ew")
            ctk.CTkLabel(row, text=f"{self._short(os.path.dirname(f.path), 60)}  ·  修改于 {format_time(f.mtime)}",
                         font=theme.font(11), text_color=theme.MUTED_TEXT, anchor="w").grid(
                row=1, column=2, sticky="ew")
            if os.name == "nt":
                ctk.CTkButton(row, text="定位", width=48, height=26, font=theme.font(12),
                              fg_color="transparent", text_color=theme.MUTED_TEXT,
                              hover_color=theme.ROW_HOVER,
                              command=lambda p=f.path: open_in_explorer(p)).grid(
                    row=0, column=3, rowspan=2, padx=6)
            self._rows.append((f, var, row))
        self._update_selection()

    def _selected(self) -> list[FileEntry]:
        return [f for f, var, _ in self._rows if var.get()]

    def _toggle_all(self):
        v = self.all_var.get()
        for _, var, _ in self._rows:
            var.set(v)
        self._update_selection()

    def _update_selection(self):
        sel = self._selected()
        self.sel_label.configure(text=f"已选 {len(sel)} 项，共 {human_size(sum(f.size for f in sel))}")
        busy = self.is_busy()
        self.trash_btn.configure(state="normal" if sel and not busy else "disabled")

    # ---------- 移到回收站 ----------
    def _trash_selected(self):
        sel = self._selected()
        if not sel:
            return
        preview = "\n".join(self._short(f.path, 80) for f in sel[:8])
        if len(sel) > 8:
            preview += f"\n……等共 {len(sel)} 个文件"
        if not messagebox.askyesno(
                "确认移到回收站",
                f"将把 {len(sel)} 个文件（共 {human_size(sum(f.size for f in sel))}）移到回收站：\n\n"
                f"{preview}\n\n可以从回收站恢复。确定吗？",
                icon="warning", default="no"):
            return
        self.trash_btn.configure(state="disabled", text="正在移动…")
        self.scan_btn.configure(state="disabled")
        paths = [f.path for f in sel]

        def work():
            self._queue.put(("trashed", move_to_trash(paths)))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self.after(100, self._poll)

    def _trash_finished(self, report):
        self.trash_btn.configure(text="移到回收站")
        self.scan_btn.configure(state="normal")
        moved = set(report.moved)
        remaining = [f for f, _, _ in self._rows if f.path not in moved]
        self._show_rows(remaining)
        msg = f"已把 {len(report.moved)} 个文件移到回收站，释放 {human_size(report.freed)}。"
        if report.failed:
            msg += f" {len(report.failed)} 个失败（详见操作日志）。"
            messagebox.showwarning("部分文件未移动",
                                   "\n".join(f"{self._short(p, 60)}：{r}" for p, r in report.failed[:10]))
        self._set_status(msg)

    # ---------- 工具 ----------
    def _set_status(self, text):
        self.status.configure(text=text)

    @staticmethod
    def _short(text: str, n: int) -> str:
        return text if len(text) <= n else text[: n // 2 - 1] + "…" + text[-(n // 2):]
