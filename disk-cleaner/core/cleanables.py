"""可以放心清理的项目：只在 safety.SAFE_CACHES 名单里找，清理时移到回收站。"""
from __future__ import annotations

import fnmatch
import os
import threading
import time
from dataclasses import dataclass, field

from .cleaner import Entry, Plan, TrashReport, execute, preflight
from .fs import folder_size, is_link_or_junction
from .oplog import OpLog
from .safety import SAFE_CACHES, SafeCache, _norm, is_link, safe_cache_roots


@dataclass
class Cleanable:
    key: str
    name: str
    default: bool
    cache: SafeCache | None = None
    items: list[tuple[str, int]] = field(default_factory=list)  # (路径, 大小)

    @property
    def size(self) -> int:
        return sum(s for _, s in self.items)


def find_one(cache: SafeCache, cancel: threading.Event | None = None) -> Cleanable:
    c = Cleanable(cache.key, cache.name, cache.default, cache)
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
                if not _matches(cache, e.name, e.stat(follow_symlinks=False).st_mtime, cutoff):
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


def _matches(cache: SafeCache, name: str, mtime: float, cutoff: float) -> bool:
    if not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in cache.patterns):
        return False
    return not (cache.min_age_days and mtime > cutoff)


def still_matches(cache: SafeCache, path: str) -> bool:
    """清理前再确认一次：还在缓存目录里、还符合名字和时间条件、不是链接。"""
    if not os.path.lexists(path) or is_link(path):
        return False
    if _norm(os.path.dirname(os.path.abspath(path))) not in set(safe_cache_roots(cache)):
        return False
    try:
        mtime = os.stat(path, follow_symlinks=False).st_mtime
    except OSError:
        return False
    return _matches(cache, os.path.basename(path), mtime, time.time() - cache.min_age_days * 86400)


def plan(items: list[Cleanable]) -> Plan:
    """给界面确认用的预检结果。"""
    entries, gone = [], []
    for c in items:
        for p, size in c.items:
            if c.cache is None or still_matches(c.cache, p):
                entries.append(Entry(p, size))
            else:
                gone.append((p, "扫描之后有变化（被用过或已经没了），这次不动它"))
    pl = preflight(entries)
    pl.refused = gone + pl.refused
    return pl


def clean(items: list[Cleanable], log: OpLog | None = None) -> TrashReport:
    """预检 + 移到回收站（每一项移动前还会再查一次）。"""
    pl = plan(items)
    report = execute(pl, log=log)
    report.failed = pl.refused + report.failed
    return report
