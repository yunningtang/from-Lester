"""操作日志：显示移到回收站的记录。"""
import os

import customtkinter as ctk

from core.oplog import OpLog
from core.utils import human_size

from .. import theme
from .base import BasePage


class LogPage(BasePage):
    title = "操作日志"
    subtitle = "所有移到回收站的文件都在这里，可从 Windows 回收站恢复"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 8))
        self.summary = ctk.CTkLabel(bar, text="", font=theme.font(13), anchor="w")
        self.summary.pack(side="left")
        ctk.CTkButton(bar, text="打开日志文件夹", width=120, font=theme.font(13),
                      fg_color="transparent", border_width=1, text_color=("gray10", "gray90"),
                      command=self._open_dir).pack(side="right")
        self.box = ctk.CTkTextbox(self, font=theme.font(12), wrap="none")
        self.box.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))

    def _open_dir(self):
        d = OpLog().dir
        d.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(d)  # noqa: S606 - 只是打开文件夹

    def on_show(self):
        recs = OpLog().read_all()
        ok = [r for r in recs if r.get("ok")]
        self.summary.configure(
            text=f"共 {len(ok)} 个文件移到回收站，合计 {human_size(sum(r.get('size', 0) for r in ok))}"
                 + (f"；{len(recs) - len(ok)} 个失败" if len(recs) > len(ok) else ""))
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        if not recs:
            self.box.insert("end", "还没有任何操作。")
        for r in reversed(recs[-1000:]):
            status = "已移到回收站" if r.get("ok") else f"失败：{r.get('error', '')}"
            self.box.insert("end", f"{r.get('time', '').replace('T', ' ')}  {human_size(r.get('size', 0)):>9}  "
                                   f"{status}  {r.get('path', '')}\n")
        self.box.configure(state="disabled")
