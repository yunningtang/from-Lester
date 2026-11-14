"""受保护目录判断。所有扫描和删除都必须经过这里。

三层规则：
1. HARD：系统目录（Windows、Program Files 等），任何情况都不碰。
2. SOFT：AppData 等程序数据，默认不碰；只有下面 SAFE_CACHES 里列出的缓存目录内部可以清理。
3. SAFE_CACHES：已知可以放心清理的缓存。新增可清理缓存、受保护目录都只改这个文件。
"""
from __future__ import annotations

import glob
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

WINDOWS = os.name == "nt"


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _norm(p: Path | str) -> str:
    try:
        resolved = Path(p).resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(p))
    return os.path.normcase(str(resolved)).rstrip("\\/") or os.sep


def _hard_list() -> list[str]:
    if WINDOWS:
        sd = (_env("SystemDrive") or "C:") + "\\"
        items = [
            _env("SystemRoot") or sd + "Windows",
            _env("ProgramFiles") or sd + "Program Files",
            _env("ProgramFiles(x86)") or sd + "Program Files (x86)",
            _env("ProgramW6432"),
            _env("ProgramData") or sd + "ProgramData",
            sd + "$Recycle.Bin", sd + "System Volume Information", sd + "Recovery", sd + "Boot",
            sd + "pagefile.sys", sd + "hiberfil.sys", sd + "swapfile.sys",
        ]
    else:  # 方便在 macOS / Linux 上开发测试
        items = ["/System", "/Library", "/bin", "/sbin", "/usr", "/etc", "/var", "/boot",
                 "/dev", "/proc", "/sys", "/lib", "/lib64", "/opt", "/Applications"]
    return [_norm(p) for p in items if p]


def _soft_list() -> list[str]:
    if WINDOWS:
        items = [_env("APPDATA"), _env("LOCALAPPDATA")]
    else:
        items = [str(Path.home() / ".config"), str(Path.home() / ".local")]
    return [_norm(p) for p in items if p]


@dataclass(frozen=True)
class SafeCache:
    key: str
    name: str
    roots: tuple[str, ...]          # 目录（可带通配符）；清理时移走这些目录里面的内容，目录本身保留
    patterns: tuple[str, ...] = ("*",)  # 只清理名字匹配的子项
    min_age_days: float = 0         # 只清理多少天没改过的
    default: bool = True            # 默认是否勾选


def _home(*parts) -> str:
    return str(Path.home().joinpath(*parts))


def _local(*parts) -> str:
    return os.path.join(_env("LOCALAPPDATA"), *parts) if _env("LOCALAPPDATA") else ""


def _chromium(base: str) -> tuple[str, ...]:
    return tuple(os.path.join(base, "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")) if base else ()


def _build_safe_caches() -> list[SafeCache]:
    tmp = tempfile.gettempdir()
    if WINDOWS:
        caches = [
            SafeCache("temp", "临时文件", (tmp,), min_age_days=1),
            SafeCache("chrome", "Chrome 缓存", _chromium(_local("Google", "Chrome"))),
            SafeCache("edge", "Edge 缓存", _chromium(_local("Microsoft", "Edge"))),
            SafeCache("npm", "npm 缓存", (_local("npm-cache", "_cacache"),)),
            SafeCache("pip", "pip 缓存", (_local("pip", "Cache"),)),
            SafeCache("uv", "uv 缓存", (_local("uv", "cache"),)),
            SafeCache("yarn", "Yarn 缓存", (_local("Yarn", "Cache"),)),
            SafeCache("thumbs", "崩溃转储", (_local("CrashDumps"),)),
        ]
    else:
        caches = [
            SafeCache("pip", "pip 缓存", (_home(".cache", "pip"),)),
            SafeCache("npm", "npm 缓存", (_home(".npm", "_cacache"),)),
            SafeCache("uv", "uv 缓存", (_home(".cache", "uv"),)),
            SafeCache("chrome", "Chrome 缓存", (_home(".cache", "google-chrome", "*", "Cache"),)),
        ]
    caches.append(SafeCache("installers", "下载里的旧安装包", (_home("Downloads"),),
                            patterns=("*.exe", "*.msi", "*.dmg", "*.pkg"), min_age_days=30))
    return [c for c in caches if all(c.roots)]


SAFE_CACHES: list[SafeCache] = _build_safe_caches()

_HARD = _hard_list()
_SOFT = _soft_list()
_EXTRA: list[str] = []
_EXTRA_SAFE: list[str] = []


def add_protected(path: Path | str) -> None:
    """额外加入受保护路径（设置页或测试用），视为 HARD。"""
    _EXTRA.append(_norm(path))


def add_safe_root(path: Path | str) -> None:
    """测试用：把一个目录当作可清理缓存。"""
    _EXTRA_SAFE.append(_norm(path))


def _inside(target: str, base: str, strict: bool = False) -> bool:
    if target == base:
        return not strict
    return target.startswith(base.rstrip(os.sep) + os.sep)


def safe_cache_roots(cache: SafeCache) -> list[str]:
    out = []
    for pattern in cache.roots:
        for p in glob.glob(pattern) if any(ch in pattern for ch in "*?[") else [pattern]:
            if os.path.isdir(p) and not os.path.islink(p):
                out.append(_norm(p))
    return out


def is_in_safe_cache(path: Path | str) -> bool:
    """path 在某个可清理缓存目录 *里面*（不是缓存目录本身）。"""
    target = _norm(path)
    roots = list(_EXTRA_SAFE)
    for c in SAFE_CACHES:
        roots += safe_cache_roots(c)
    return any(_inside(target, r, strict=True) for r in roots)


def is_drive_root(path: Path | str) -> bool:
    p = Path(_norm(path))
    return p.parent == p


def is_hard_protected(path: Path | str) -> bool:
    target = _norm(path)
    return any(_inside(target, b) for b in _HARD + _EXTRA)


def is_protected(path: Path | str) -> bool:
    """扫描时用：系统目录和程序数据目录都返回 True。"""
    target = _norm(path)
    return is_hard_protected(target) or any(_inside(target, b) for b in _SOFT)


def can_delete(path: Path | str) -> tuple[bool, str]:
    """删除前的最终检查。返回 (是否允许, 原因)。"""
    if is_drive_root(path):
        return False, "不能删除磁盘根目录"
    if is_hard_protected(path):
        return False, "系统受保护目录"
    if is_protected(path) and not is_in_safe_cache(path):
        return False, "程序数据目录（不在可清理缓存名单里）"
    if not os.path.lexists(path):
        return False, "文件已不存在"
    return True, ""
