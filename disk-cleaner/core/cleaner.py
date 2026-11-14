"""唯一的删除入口：先预检，再移到回收站。禁止在别处删除文件。

流程分两步，界面必须按这个顺序走：

1. preflight(条目)  → Plan：哪些能移、哪些不能移（附原因）、要提醒用户什么。
   界面把 Plan 原样展示给用户确认。预检只读，不动任何文件。
2. execute(plan)    → TrashReport：对每一项**再检查一次**（安全规则、文件有没有变、
   能不能确定进回收站），然后移到回收站，并写日志。

注意：移到回收站**不会**马上腾出空间，回收站清空后才会。界面上不能说“已释放”。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import recycle
from .fs import folder_size, stamp
from .oplog import OpLog
from .safety import _lex, can_delete


@dataclass
class Entry:
    path: str
    size: int = 0                                  # 扫描时的大小（字节）
    stamp: tuple[int, float] | None = None         # 扫描时的 (大小, 修改时间)；文件夹为 None


@dataclass
class Plan:
    go: list[Entry] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)   # (路径, 原因)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(e.size for e in self.go)


@dataclass
class TrashReport:
    moved: list[str] = field(default_factory=list)
    trashed: int = 0                               # 移进回收站的字节数（不是“已释放”）
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def freed(self) -> int:  # 兼容旧代码；含义是“移进回收站的大小”
        return self.trashed


def _as_entry(x) -> Entry:
    if isinstance(x, Entry):
        return x
    if isinstance(x, tuple):
        return Entry(*x)
    return Entry(str(x))


def _dedupe(entries: list[Entry]) -> list[Entry]:
    """去掉重复的，以及已经被上级文件夹包含的（上级移走了，下级自然跟着走）。"""
    seen: list[str] = []
    out: list[Entry] = []
    for e in sorted(entries, key=lambda e: len(_lex(e.path))):
        k = _lex(e.path)
        if k in seen or any(k.startswith(s.rstrip(os.sep) + os.sep) for s in seen):
            continue
        seen.append(k)
        out.append(e)
    return out


def _changed(e: Entry) -> str:
    if e.stamp is None:
        return ""
    now = stamp(e.path)
    if now is None:
        return "文件已经不在了"
    if now != e.stamp:
        return "扫描之后这个文件被改动过，为了稳妥这次不动它，请重新扫描"
    return ""


def preflight(items: Iterable) -> Plan:
    """只读预检。items 可以是路径、Entry 或 (路径, 大小, 指纹)。"""
    plan = Plan()
    entries = _dedupe([_as_entry(x) for x in items])
    for e in entries:
        ok, why = can_delete(e.path)
        if ok:
            why = _changed(e)
            ok = not why
        if ok:
            if not e.size:
                e.size = folder_size(e.path)
            ok, why = recycle.check_recyclable(e.path, e.size)
        (plan.go.append(e) if ok else plan.refused.append((e.path, why)))

    # 回收站会不会被挤满：满了以后 Windows 会永久删掉回收站里最早的文件来腾地方
    by_volume: dict[str, int] = {}
    for e in plan.go:
        v = recycle._volume_root(e.path)
        by_volume[v] = by_volume.get(v, 0) + e.size
    for v, add in by_volume.items():
        cap, used = recycle.bin_capacity(v), recycle.bin_used(v)
        if cap and used + add > cap:
            plan.warnings.append("回收站快满了。放进这些以后，Windows 会把回收站里最早删的一些文件"
                                 "永久清掉来腾地方。如果回收站里有想找回的，先去恢复。")
    if plan.go:
        plan.warnings.append("移到回收站后空间还不会变多，清空回收站以后才会真正空出来。")
    return plan


def execute(plan: Plan, log: OpLog | None = None,
            on_item: Callable[[int, str], None] | None = None,
            cancel: threading.Event | None = None) -> TrashReport:
    """按预检的结果执行。每一项移动前再查一遍，任何一项出错都不影响其他项。"""
    log = log or OpLog()
    report = TrashReport()
    for i, e in enumerate(plan.go):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        if on_item:
            on_item(i, e.path)
        ok, why = can_delete(e.path)
        if ok:
            why = _changed(e)
            ok = not why
        if ok:
            ok, why = recycle.check_recyclable(e.path, e.size)
        if ok:
            try:
                recycle.recycle(e.path)
            except Exception as ex:  # noqa: BLE001 - 一项失败不影响其他项
                ok, why = False, str(ex) or ex.__class__.__name__
        if ok:
            report.moved.append(e.path)
            report.trashed += e.size
        else:
            report.failed.append((e.path, why))
        log.write("trash", e.path, e.size, ok, why)
    return report


def move_to_trash(items: Iterable, log: OpLog | None = None,
                  on_item: Callable[[int, str], None] | None = None) -> TrashReport:
    """预检 + 执行一步完成（命令行和测试用）。界面请分开调用，先给用户看预检结果。"""
    log = log or OpLog()
    plan = preflight(items)
    report = execute(plan, log=log, on_item=on_item)
    report.failed = plan.refused + report.failed
    for p, why in plan.refused:
        log.write("trash", p, 0, False, why)
    return report
