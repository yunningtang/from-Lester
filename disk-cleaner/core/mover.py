"""移动文件：整理、挪到别的盘、撤销，都走这里。

和删除一样分两步：
1. plan_moves(...)  → MovePlan：每一项从哪到哪、哪些不能移（附原因）。只读。
2. execute_moves(plan) → MoveReport：每一项移动前再查一次，然后移动，并写进记录（带批次号）。
3. undo(batch) 按记录把这一批原样挪回去。

怎么移：
- 同一个盘：直接改名，瞬间完成，不会出现“一半”的情况。
- 跨盘：先复制到目标位置的临时名字，边复制边算哈希，复制完再把副本完整读一遍比对；
  一致了才改成正式名字，最后才删掉原来那份。任何一步出错，原文件都不动，临时副本清掉。

这里是除了 recycle.py 之外唯一会让文件离开原处的地方。删除原文件只发生在“副本已经逐字节核对一致”之后。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable

from . import recycle
from .fs import folder_size, stamp
from .oplog import OpLog
from .safety import _lex, _norm, can_delete, is_hard_protected, is_in_cloud, is_link, is_protected

PART = ".liubai-part"          # 跨盘复制时的临时后缀
FREE_MARGIN = 1024 ** 3         # 目标盘至少留 1 G，避免把别的盘塞满


@dataclass
class Move:
    src: str
    dst: str
    size: int = 0
    stamp: tuple | None = None   # 文件的 (大小, 修改时间)；文件夹为 None
    is_dir: bool = False


@dataclass
class MovePlan:
    go: list[Move] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    label: str = "move"           # move 整理/挪走 / undo 撤销

    @property
    def total(self) -> int:
        return sum(m.size for m in self.go)


@dataclass
class MoveReport:
    batch: str = ""
    moved: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    size: int = 0
    cancelled: bool = False


# ---------------------------------------------------------------- 检查

def can_move(src: str) -> tuple[bool, str]:
    """能不能把它从原处拿走。规则和删除一样严格（系统、程序数据、OneDrive、个人文件夹本身都不行）。"""
    ok, why = can_delete(src)
    if not ok:
        return ok, why.replace("移到回收站", "移动")
    if is_protected(src):          # 删除允许清缓存目录里的东西，移动不需要
        return False, "程序数据，留白不移动它"
    return True, ""


def check_dest(dst: str) -> tuple[bool, str]:
    """目标位置是否合适：不能在系统或程序目录、不能在 OneDrive、不能已经有同名文件。"""
    parent = os.path.dirname(os.path.abspath(dst))
    if is_hard_protected(parent) or is_protected(parent):
        return False, "目标位置是系统或程序目录"
    if is_in_cloud(parent):
        return False, "目标位置在 OneDrive 里，会上传到云端，留白不这样做"
    if os.path.lexists(dst):
        return False, "目标位置已经有同名的文件"
    probe = parent
    while not os.path.exists(probe):
        nxt = os.path.dirname(probe)
        if nxt == probe:
            return False, "目标盘不存在"
        probe = nxt
    if is_link(probe):
        return False, "目标位置是一个快捷链接"
    if recycle.drive_type(probe) == 4:
        return False, "目标是网络盘，断网就打不开，留白不往那里挪"
    return True, ""


def unique_dest(dst: str, taken: set[str]) -> str:
    """目标已有同名文件时，改成“名字 (2).扩展名”。taken 是这一批已经占用的目标。"""
    root, ext = os.path.splitext(dst)
    cand, n = dst, 2
    while os.path.lexists(cand) or _lex(cand) in taken:
        cand = f"{root} ({n}){ext}"
        n += 1
    taken.add(_lex(cand))
    return cand


def _volume(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.exists(p):
        nxt = os.path.dirname(p)
        if nxt == p:
            break
        p = nxt
    return recycle._volume_root(p) if os.name == "nt" else str(os.stat(p).st_dev)


def same_volume(src: str, dst: str) -> bool:
    try:
        return _volume(src) == _volume(dst)
    except OSError:
        return False


def plan_moves(pairs: list[tuple[str, str]], sizes: dict[str, int] | None = None,
               stamps: dict[str, tuple] | None = None, label: str = "move") -> MovePlan:
    """pairs：(原路径, 想去的路径)。同名会自动改名。只读。"""
    sizes, stamps = sizes or {}, stamps or {}
    plan = MovePlan(label=label)
    taken: set[str] = set()
    seen: list[str] = []
    need: dict[str, int] = {}
    for src, want in sorted(pairs, key=lambda x: len(_lex(x[0]))):
        k = _lex(src)
        if k in seen or any(k.startswith(s.rstrip(os.sep) + os.sep) for s in seen):
            continue                                   # 自己或上级已经在这一批里（会跟着一起移）
        ok, why = can_move(src)
        if ok and stamps.get(src) is not None and stamp(src) != stamps[src]:
            ok, why = False, "扫描之后这个文件被改动过，为了稳妥这次不动它"
        if ok and _norm(os.path.dirname(want)).startswith(_norm(src) + os.sep):
            ok, why = False, "不能把文件夹挪进它自己里面"
        dst = unique_dest(want, taken) if ok else want
        if ok:
            ok, why = check_dest(dst)
        if not ok:
            plan.refused.append((src, why))
            continue
        is_dir = os.path.isdir(src) and not is_link(src)
        size = sizes.get(src) or (folder_size(src) if is_dir else (stamp(src) or (0,))[0])
        m = Move(src, dst, size, None if is_dir else stamp(src), is_dir)
        if not same_volume(src, dst):
            vol = _volume(dst)
            need[vol] = need.get(vol, 0) + size
            try:
                probe = dst
                while not os.path.exists(probe):
                    probe = os.path.dirname(probe)
                free = shutil.disk_usage(probe).free
            except OSError:
                free = 0
            if need[vol] + FREE_MARGIN > free:
                need[vol] -= size
                plan.refused.append((src, "目标盘的空间不够了"))
                continue
        plan.go.append(m)
        seen.append(k)                                 # 只有真的要移的，才算“已在这一批里”
    if any(not same_volume(m.src, m.dst) for m in plan.go):
        plan.warnings.append("挪到别的盘要复制一遍，大文件会慢一些。复制完核对无误，才会删掉原来那份。")
    return plan


# ---------------------------------------------------------------- 执行

def _copy_file_verified(src: str, dst_tmp: str, cancel: threading.Event | None) -> None:
    h_src = hashlib.sha256()
    with open(src, "rb") as fi, open(dst_tmp, "wb") as fo:
        while True:
            if cancel is not None and cancel.is_set():
                raise OSError(0, "已取消")
            b = fi.read(4 << 20)
            if not b:
                break
            h_src.update(b)
            fo.write(b)
        fo.flush()
        os.fsync(fo.fileno())
    shutil.copystat(src, dst_tmp)
    h_dst = hashlib.sha256()
    with open(dst_tmp, "rb") as f:
        for b in iter(lambda: f.read(4 << 20), b""):
            h_dst.update(b)
    if h_src.digest() != h_dst.digest():
        raise OSError(0, "复制后核对不一致")


def _copy_tree_verified(src: str, dst_tmp: str, cancel: threading.Event | None) -> None:
    os.makedirs(dst_tmp)
    for root, dirs, files in os.walk(src, followlinks=False):
        rel = os.path.relpath(root, src)
        target = os.path.join(dst_tmp, rel) if rel != "." else dst_tmp
        for d in dirs:
            full = os.path.join(root, d)
            if os.path.islink(full) or is_link(full):
                raise OSError(0, "文件夹里有快捷链接，留白不跨盘移动这种文件夹")
            os.makedirs(os.path.join(target, d), exist_ok=True)
        for f in files:
            full = os.path.join(root, f)
            if os.path.islink(full):
                raise OSError(0, "文件夹里有快捷链接，留白不跨盘移动这种文件夹")
            _copy_file_verified(full, os.path.join(target, f), cancel)
    shutil.copystat(src, dst_tmp)


def _discard_partial(path: str) -> None:
    """清掉我们自己复制了一半的临时副本（只会是带 .liubai-part 后缀的）。"""
    if not path.endswith(PART) or not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            os.remove(path)
        except OSError:
            pass


def _remove_source_after_verified_copy(src: str, is_dir: bool) -> None:
    """副本已经逐字节核对一致，并且已经放到正式位置，才删除原来那份。"""
    if is_dir:
        shutil.rmtree(src)
    else:
        os.remove(src)


def _make_parents(path: str) -> list[str]:
    """建好目标的上级文件夹，返回这次新建的（撤销时只清这些，而且只在它们空了的时候）。"""
    made, p = [], os.path.dirname(os.path.abspath(path))
    while not os.path.exists(p):
        made.append(p)
        nxt = os.path.dirname(p)
        if nxt == p:
            break
        p = nxt
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return made


def _remove_empty_dirs_we_made(dirs: list[str]) -> None:
    """撤销后，把当初为了放文件而新建、现在已经空了的文件夹删掉。不空的一律不动。"""
    for d in sorted(set(dirs), key=len, reverse=True):
        try:
            if os.path.isdir(d) and not is_link(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def move_one(m: Move, cancel: threading.Event | None = None) -> list[str]:
    """移动一项，返回为它新建的文件夹。"""
    made = _make_parents(m.dst)
    if same_volume(m.src, m.dst):
        os.rename(m.src, m.dst)                        # 同一个盘：改名，原子操作
        return made
    tmp = m.dst + PART
    if os.path.lexists(tmp):
        raise OSError(0, "目标位置有一份没复制完的临时文件，请先检查")
    try:
        (_copy_tree_verified if m.is_dir else _copy_file_verified)(m.src, tmp, cancel)
        os.rename(tmp, m.dst)
    except BaseException:
        _discard_partial(tmp)
        raise
    _remove_source_after_verified_copy(m.src, m.is_dir)
    return made


def execute_moves(plan: MovePlan, log: OpLog | None = None,
                  on_item: Callable[[int, str], None] | None = None,
                  cancel: threading.Event | None = None, batch: str | None = None) -> MoveReport:
    log = log or OpLog()
    rep = MoveReport(batch=batch or uuid.uuid4().hex[:10])
    for i, m in enumerate(plan.go):
        if cancel is not None and cancel.is_set():
            rep.cancelled = True
            break
        if on_item:
            on_item(i, m.src)
        ok, why = can_move(m.src)
        if ok and m.stamp is not None and stamp(m.src) != m.stamp:
            ok, why = False, "确认之后这个文件被改动过，这次不动它"
        if ok:
            ok, why = check_dest(m.dst)
        made: list[str] = []
        if ok:
            try:
                made = move_one(m, cancel)
            except Exception as e:  # noqa: BLE001 - 一项失败不影响其他项
                ok, why = False, str(e) or e.__class__.__name__
        if ok:
            rep.moved.append((m.src, m.dst))
            rep.size += m.size
        else:
            rep.failed.append((m.src, why))
        log.write(plan.label, m.src, m.size, ok, why, dst=m.dst, batch=rep.batch, made=made)
    return rep


# ---------------------------------------------------------------- 撤销

def batch_records(log: OpLog, batch: str) -> list[dict]:
    return [r for r in log.read_all() if r.get("batch") == batch and r.get("action") == "move" and r.get("ok")]


def undoable(log: OpLog, batch: str) -> bool:
    recs = batch_records(log, batch)
    if not recs:
        return False
    done = {r.get("path") for r in log.read_all() if r.get("action") == "undo" and r.get("undo_of") == batch and r.get("ok")}
    return any(r["path"] not in done for r in recs)


def plan_undo(log: OpLog, batch: str) -> MovePlan:
    """把这一批挪回原处。原处已经有了新文件的，那一项就不挪（不会覆盖任何东西）。"""
    done = {r.get("path") for r in log.read_all() if r.get("action") == "undo" and r.get("undo_of") == batch and r.get("ok")}
    plan = MovePlan(label="undo")
    for r in reversed(batch_records(log, batch)):
        orig, now_at = r["path"], r.get("dst", "")
        if orig in done:
            continue
        if not now_at or not os.path.lexists(now_at):
            plan.refused.append((orig, "已经不在挪过去的位置了"))
            continue
        if os.path.lexists(orig):
            plan.refused.append((orig, "原来的位置现在有了别的文件，不覆盖"))
            continue
        is_dir = os.path.isdir(now_at)
        plan.go.append(Move(now_at, orig, r.get("size", 0), None, is_dir))
    return plan


def execute_undo(plan: MovePlan, batch: str, log: OpLog | None = None,
                 on_item: Callable[[int, str], None] | None = None) -> MoveReport:
    log = log or OpLog()
    rep = MoveReport(batch=batch)
    for i, m in enumerate(plan.go):
        if on_item:
            on_item(i, m.src)
        ok, why = True, ""
        if os.path.lexists(m.dst):
            ok, why = False, "原来的位置现在有了别的文件，不覆盖"
        if ok and is_link(m.src):
            ok, why = False, "这是一个快捷链接"
        if ok:
            try:
                move_one(m)
            except Exception as e:  # noqa: BLE001
                ok, why = False, str(e) or e.__class__.__name__
        (rep.moved.append((m.src, m.dst)) if ok else rep.failed.append((m.dst, why)))
        if ok:
            rep.size += m.size
        log.write("undo", m.dst, m.size, ok, why, dst=m.src, undo_of=batch)
    made = [d for r in batch_records(log, batch) for d in (r.get("made") or [])]
    _remove_empty_dirs_we_made(made)
    return rep
