"""可以放心清理的项目：只在 safety.SAFE_CACHES 名单里找，清理时移到回收站。"""
from __future__ import annotations

import fnmatch
import os
import threading
import time
from dataclasses import dataclass, field

from .cleaner import TrashReport, move_to_trash
from .fs import folder_size, is_link_or_junction
from .oplog import OpLog
from .safety import SAFE_CACHES, SafeCache, safe_cache_roots


@dataclass
class Cleanable:
    key: str
    name: str
    default: bool
    items: list[tuple[str, int]] = field(default_factory=list)  # (路径, 大小)

    @property
    def size(self) -> int:
        return sum(s for _, s in self.items)


def find_one(cache: SafeCache, cancel: threading.Event | None = None) -> Cleanable:
    c = Cleanable(cache.key, cache.name, cache.default)
    cutoff = time.time() - cache.min_age_days * 86400
    for root in safe_cache_roots(cache):
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            if cancel is not None and cancel.is_set():
                return c
            try:
                if is_link_or_junction(e):
                    continue
                if not any(fnmatch.fnmatch(e.name.lower(), p.lower()) for p in cache.patterns):
                    continue
                if cache.min_age_days and e.stat(follow_symlinks=False).st_mtime > cutoff:
                    continue
                size = folder_size(e.path, cancel) if e.is_dir(follow_symlinks=False) \
                    else e.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if size > 0:
                c.items.append((e.path, size))
    return c


def find_all(caches: list[SafeCache] | None = None,
             cancel: threading.Event | None = None) -> list[Cleanable]:
    out = [find_one(c, cancel) for c in (caches if caches is not None else SAFE_CACHES)]
    return sorted((c for c in out if c.size > 0), key=lambda c: -c.size)


def clean(items: list[Cleanable], log: OpLog | None = None) -> TrashReport:
    """把这些项目里的文件移到回收站（每个文件仍会经过 safety.can_delete 检查）。"""
    return move_to_trash([p for c in items for p, _ in c.items], log=log)
