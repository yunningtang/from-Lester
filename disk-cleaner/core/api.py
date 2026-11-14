"""界面和后端之间唯一的接口。

界面（webui/）通过 pywebview 调用这里的方法；开发时也可以用 devserver.py 在浏览器里调用。
这个类不依赖 pywebview，可以直接测试。

规则：
- 所有耗时的事（扫描、看文件夹、移到回收站）都在后台线程里做，界面用 state() 轮询进度。
- 删除一律走 cleaner.preflight → 用户确认 → cleaner.execute。plan() 只读，execute() 才动文件。
- 返回给界面的都是能转成 JSON 的普通数据。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid

from . import cleanables, cleaner, inspect as insp, space
from .cleaner import Entry
from .oplog import OpLog
from .prefs import Prefs

KIND = {"user": "user", "app": "app", "system": "sys", "cache": "cache", "free": "free"}
INFO = {
    "programs": "留白不删程序文件，删了程序会打不开。想卸载不用的程序，请到 Windows 设置 → 应用 → 已安装的应用。",
    "local": "程序自己的数据。里面能放心清的缓存，已经单独列在“可放心清理”里了；其余的留白不会动。",
    "roaming": "程序的设置、插件和账号信息。删了，程序可能要重新登录、重新设置。留白不会动。",
    "devtools": "开发工具下载的依赖和工具链。可以放心清的已经列在“可放心清理”里；其余的请用对应工具自己的清理命令。",
    "bin": "回收站里的还能找回。确认都不要了，在 Windows 回收站里点“清空回收站”，空间才会真正空出来。留白不替你清空，因为清空了就找不回来。",
}
INSPECTABLE = {"downloads", "desktop", "wechat", "qq", "videos", "pictures", "documents", "projects",
               "music", "onedrive"}


def _under(path: str, folder: str) -> bool:
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


class Api:
    def __init__(self, drive: str | None = None, log: OpLog | None = None, prefs: Prefs | None = None,
                 defs=None, caches=None):
        self.drive = drive or space.system_drive()
        self.log = log or OpLog()
        self.prefs = prefs or Prefs()
        self._defs, self._caches = defs, caches        # 测试时可以换成假的
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self._job_thread: threading.Thread | None = None
        self.window = None                              # pywebview 的窗口，由启动器设置
        self._maxed = False
        self._reset()

    # ------------------------------------------------------------ 状态
    def _reset(self):
        self._version = 0
        self._phase = ""
        self._error = ""
        self._report: space.SpaceReport | None = None
        self._partial: list[space.Category] = []
        self._cleanables: list[cleanables.Cleanable] = []
        self._inspections: dict[str, insp.Inspection] = {}
        self._suggest_keys: list[str] = []
        self._plans: dict[str, cleaner.Plan] = {}
        self._job: dict | None = None
        self._bin = space.recycle_bin_size(self.drive)
        try:
            u = shutil.disk_usage(self.drive)
            self._usage = (u.total, u.used, u.free)
        except OSError:
            self._usage = (0, 0, 0)

    def _bump(self):
        self._version += 1

    def state(self) -> dict:
        with self._lock:
            total, used, free = self._usage
            cats = self._report.categories if self._report else self._partial
            safe_total = sum(c.size for c in self._cleanables)
            blocks = []
            for c in cats:
                if c.size > 0:
                    blocks.append(self._block(c))
            for c in self._cleanables:
                if c.size > 0:
                    blocks.append({"key": "c:" + c.key, "name": c.name, "kind": "cache", "size": c.size,
                                   "note": c.cache.note if c.cache else "", "paths": []})
            if self._bin:
                blocks.append({"key": "bin", "name": "回收站", "kind": "bin", "size": self._bin,
                               "note": INFO["bin"], "paths": []})
            if self._report:
                for b in self._report.blocks(0):
                    if b.kind == "system":
                        blocks.append(self._block(b))
            else:
                rest = used - sum(b["size"] for b in blocks)
                if rest > 0:
                    blocks.append({"key": "pending", "name": "还在统计…", "kind": "sys", "size": rest,
                                   "note": "", "paths": []})
            suggest = []
            for k in self._suggest_keys:
                c = next((c for c in cats if c.key == k), None)
                if c is None or c.size <= 0:
                    continue
                ins = self._inspections.get(k)
                suggest.append({"key": k, "name": c.name, "size": c.size,
                                "maybe": ins.maybe_size if ins else None})
            return {
                "version": self._version,
                "drive": self.drive, "total": total, "used": used, "free": free, "bin": self._bin,
                "scanning": self._scan_thread is not None and self._scan_thread.is_alive(),
                "phase": self._phase, "error": self._error,
                "blocks": blocks,
                "cleanables": [{"key": c.key, "name": c.name, "size": c.size, "count": len(c.items),
                                "default": c.default, "note": c.cache.note if c.cache else "",
                                "group": c.cache.group if c.cache else ""}
                               for c in self._cleanables if c.size > 0],
                "safe_total": safe_total,
                "suggest": suggest,
                "job": dict(self._job) if self._job else None,
            }

    @staticmethod
    def _block(c: space.Category) -> dict:
        return {"key": c.key, "name": c.name, "kind": KIND.get(c.kind, "sys"), "size": c.size,
                "note": c.note or INFO.get(c.key, ""), "paths": list(c.paths)}

    # ------------------------------------------------------------ 扫描
    def scan(self) -> dict:
        """开始（或重新开始）扫描。已经在扫就什么都不做。"""
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                return {"started": False}
            if self._job and self._job.get("running"):
                return {"started": False, "why": "正在移到回收站，完成后再扫描"}
            self._cancel.clear()
            self._reset()
            self._phase = "正在找可以放心清理的缓存…"
            self._scan_thread = threading.Thread(target=self._scan_work, daemon=True)
            self._scan_thread.start()
            return {"started": True}

    def _scan_work(self):
        try:
            found = cleanables.find_all(self._caches, cancel=self._cancel)
            with self._lock:
                self._cleanables = found
                self._phase = "正在统计空间…"
                self._bump()
            subtract = [(p, s) for c in found for p, s in c.items]

            def on_cat(c):
                with self._lock:
                    self._partial.append(c)
                    self._phase = f"正在统计：{c.name}"
                    self._bump()
            rep = space.measure(self.drive, self._cancel, on_category=on_cat, subtract=subtract,
                                defs=self._defs)
            with self._lock:
                self._report = rep
                self._usage = (rep.total, rep.used, rep.free)
                self._bin = rep.recycle_bin
                users = sorted((c for c in rep.categories if c.key in INSPECTABLE and c.size > 0),
                               key=lambda c: -c.size)
                self._suggest_keys = [c.key for c in users[:3]]
                self._phase = "正在看最大的几块里有什么…"
                self._bump()
            # 先看最大的三块，算出“可能不再需要”的大小，给首页的建议用
            for k in list(self._suggest_keys):
                if self._cancel.is_set():
                    break
                self._inspect_now(k)
            with self._lock:
                self._phase = ""
                self._bump()
        except Exception as e:  # noqa: BLE001 - 扫描出错要告诉用户，不能悄悄停住
            with self._lock:
                self._error = f"扫描出错：{e}"
                self._phase = ""
                self._bump()

    def cancel(self) -> dict:
        self._cancel.set()
        return {"ok": True}

    # ------------------------------------------------------------ 看看里面
    def _category(self, key: str) -> space.Category | None:
        cats = self._report.categories if self._report else self._partial
        return next((c for c in cats if c.key == key), None)

    def _inspect_now(self, key: str) -> insp.Inspection | None:
        c = self._category(key)
        if c is None:
            return None
        skip = frozenset(p for cl in self._cleanables for p, _ in cl.items)
        ins = insp.inspect(key, c.paths, self._cancel, keep=frozenset(self.prefs.keep), skip=skip)
        with self._lock:
            self._inspections[key] = ins
            self._bump()
        return ins

    def inspect(self, key: str) -> dict:
        """一块墨的详情。你的文件给出建议；程序、系统、回收站只给说明。会花几秒，界面要显示“正在看”。"""
        if key.startswith("c:"):
            c = next((c for c in self._cleanables if "c:" + c.key == key), None)
            if not c:
                return {"key": key, "missing": True}
            return {"key": key, "name": c.name, "size": c.size, "kind": "cache",
                    "info": c.cache.note if c.cache else "", "groups": [], "paths": []}
        if key == "bin":
            return {"key": key, "name": "回收站", "size": self._bin, "kind": "bin", "info": INFO["bin"],
                    "groups": [], "paths": []}
        c = self._category(key)
        if c is None:
            sys_block = next((b for b in (self._report.blocks(0) if self._report else []) if b.key == key), None)
            if sys_block:
                return {"key": key, "name": sys_block.name, "size": sys_block.size, "kind": "sys",
                        "info": sys_block.note, "groups": [], "paths": []}
            return {"key": key, "missing": True}
        if key not in INSPECTABLE:
            return {"key": key, "name": c.name, "size": c.size, "kind": KIND.get(c.kind, "sys"),
                    "info": c.note or INFO.get(key, ""), "groups": [], "paths": c.paths}
        ins = self._inspections.get(key) or self._inspect_now(key)
        return self._detail(c, ins)

    def _detail(self, c: space.Category, ins: insp.Inspection) -> dict:
        titles = {"maybe": "可能不再需要", "mine": "你的文件", "keep": "最近还在用", "lock": "留白不会动"}
        groups = []
        for lvl in ("maybe", "mine", "keep", "lock"):
            items = [s for s in ins.items if s.lvl == lvl]
            if items:
                groups.append({"lvl": lvl, "title": titles[lvl], "size": sum(s.size for s in items),
                               "items": [{"id": s.id, "name": s.name, "path": s.path, "size": s.size,
                                          "why": s.why, "then": s.then, "dir": s.is_dir} for s in items]})
        return {"key": c.key, "name": c.name, "size": c.size, "kind": KIND.get(c.kind, "user"),
                "paths": c.paths, "maybe": ins.maybe_size, "groups": groups,
                "rest": {"count": ins.rest_count, "size": ins.rest_size}, "info": ""}

    def set_keep(self, item_id: str, on: bool = True) -> dict:
        s = self._find_suggestion(item_id)
        if not s:
            return {"ok": False}
        self.prefs.set_keep(s.path, on)
        if on:
            s.lvl, s.why, s.then = "keep", "你说过留着。", ""
        with self._lock:
            self._bump()
        return {"ok": True}

    def _find_suggestion(self, item_id: str):
        for ins in self._inspections.values():
            for s in ins.items:
                if s.id == item_id:
                    return s
        return None

    # ------------------------------------------------------------ 移到回收站
    def plan(self, kind: str, ids: list[str]) -> dict:
        """只读预检。kind = "caches"（ids 是缓存的 key）或 "files"（ids 是建议的 id）。"""
        if kind == "caches":
            sel = [c for c in self._cleanables if c.key in set(ids)]
            pl = cleanables.plan(sel)
            then = []
        else:
            sugs = [s for s in (self._find_suggestion(i) for i in ids) if s and s.lvl == "maybe"]
            # 第二道保险：一组重复文件不能全部移走，至少留一份
            chosen = {s.path for s in sugs}
            twins = [(s.path, "它的另一份也在这次要移走的里面，至少留一份") for s in sugs if s.twin_of in chosen]
            sugs = [s for s in sugs if s.twin_of not in chosen]
            pl = cleaner.preflight([Entry(s.path, s.size, s.stamp) for s in sugs])
            pl.refused = twins + pl.refused
            then = sorted({s.then for s in sugs if s.then})
        pid = uuid.uuid4().hex[:12]
        with self._lock:
            self._plans = {pid: pl}           # 只保留最新的一份，旧的确认作废
        return {"id": pid, "count": len(pl.go), "total": pl.total,
                "refused": [[p, why] for p, why in pl.refused[:20]], "refused_count": len(pl.refused),
                "warnings": pl.warnings, "then": then}

    def execute(self, plan_id: str) -> dict:
        with self._lock:
            pl = self._plans.pop(plan_id, None)
            if pl is None:
                return {"started": False, "why": "这次确认已经过期，请重新点一次"}
            if self._job and self._job.get("running"):
                return {"started": False, "why": "上一批还没移完"}
            self._job = {"running": True, "index": 0, "count": len(pl.go), "total": pl.total,
                         "moved": 0, "trashed": 0, "failed": [], "done": False}
            self._job_thread = threading.Thread(target=self._job_work, args=(pl,), daemon=True)
            self._job_thread.start()
            return {"started": True}

    def _job_work(self, pl: cleaner.Plan):
        def on_item(i, path):
            with self._lock:
                self._job["index"] = i
                self._bump()
        rep = cleaner.execute(pl, log=self.log, on_item=on_item)
        moved = set(rep.moved)
        with self._lock:
            # 移走的从缓存和建议里去掉；它们现在在回收站里，所以回收站变大，可用空间不变
            for c in self._cleanables:
                c.items = [(p, s) for p, s in c.items if p not in moved]
            for ins in self._inspections.values():
                ins.items = [s for s in ins.items if s.path not in moved]
            for cat in (self._report.categories if self._report else []):
                cat.size = max(0, cat.size - sum(e.size for e in pl.go if e.path in moved
                                                 and any(_under(e.path, p) for p in cat.paths)))
            self._bin = space.recycle_bin_size(self.drive) or self._bin + rep.trashed
            try:
                u = shutil.disk_usage(self.drive)
                self._usage = (u.total, u.used, u.free)
            except OSError:
                pass
            self._job.update(running=False, done=True, moved=len(rep.moved), trashed=rep.trashed,
                             failed=[[p, why] for p, why in (pl.refused + rep.failed)][:50],
                             log_unsaved=len(self.log.unsaved))
            self._bump()

    def clear_job(self) -> dict:
        with self._lock:
            if self._job and not self._job.get("running"):
                self._job = None
                self._bump()
        return {"ok": True}

    def history(self, limit: int = 300) -> dict:
        """最近的清理记录，新的在前。"""
        recs = self.log.read_all()[-limit:]
        return {"records": list(reversed(recs))}

    # ------------------------------------------------------------ 打开系统窗口（不改任何东西）
    def open_recycle_bin(self) -> dict:
        if os.name == "nt":
            subprocess.Popen(["explorer", "shell:RecycleBinFolder"])
        return {"ok": os.name == "nt"}

    def reveal(self, path: str) -> dict:
        if os.name == "nt" and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return {"ok": os.name == "nt"}

    def open_storage_settings(self) -> dict:
        if os.name == "nt":
            os.startfile("ms-settings:storagesense")  # noqa: S606
        return {"ok": os.name == "nt"}

    # ------------------------------------------------------------ 窗口
    def win_minimize(self):
        if self.window:
            self.window.minimize()

    def win_toggle_max(self):
        if self.window:
            (self.window.restore if self._maxed else self.window.maximize)()
            self._maxed = not self._maxed
        return {"maxed": self._maxed}

    def win_close(self):
        self._cancel.set()
        if self.window:
            self.window.destroy()

    def wait_idle(self, timeout: float = 30) -> bool:
        """测试用：等扫描和清理都结束。"""
        end = time.monotonic() + timeout
        for t in (self._scan_thread, self._job_thread):
            if t is not None:
                t.join(max(0, end - time.monotonic()))
        return not any(t is not None and t.is_alive() for t in (self._scan_thread, self._job_thread))
