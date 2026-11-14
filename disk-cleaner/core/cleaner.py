"""唯一的删除入口：移到回收站。禁止在别处永久删除文件。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterable

from send2trash import send2trash

from .fs import folder_size
from .oplog import OpLog
from .safety import can_delete


@dataclass
class TrashReport:
    moved: list[str] = field(default_factory=list)
    freed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def move_to_trash(
    paths: Iterable[str],
    log: OpLog | None = None,
    on_item: Callable[[int, str], None] | None = None,
) -> TrashReport:
    """把文件移到回收站。每个文件先做安全检查，并写日志。"""
    log = log or OpLog()
    report = TrashReport()
    for i, p in enumerate(paths):
        if on_item:
            on_item(i, p)
        ok, reason = can_delete(p)
        size = 0
        if ok:
            try:
                size = folder_size(p)  # 文件或文件夹的大小
                send2trash(p)
            except Exception as e:  # noqa: BLE001 - 记录任何失败
                ok, reason = False, str(e)
        if ok:
            report.moved.append(p)
            report.freed += size
        else:
            report.failed.append((p, reason))
        log.write("trash", p, size, ok, reason)
    return report
