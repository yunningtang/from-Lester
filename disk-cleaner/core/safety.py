"""受保护目录判断。所有扫描和删除都必须经过这里。

规则：
1. HARD：系统目录（Windows、Program Files 等），任何情况都不碰。
2. SOFT：AppData 等程序数据，默认不碰；只有 SAFE_CACHES 里列出的缓存目录内部可以清理。
3. KEEP：用户主目录、桌面、文档、下载等文件夹**本身**和它们的上级（如 C:\\Users）不能删，
   里面的文件可以。
4. CLOUD：OneDrive 里的文件不删，因为删除会同步到云端和其他设备。
5. 链接和目录联接本身不删，也不跟随。
6. SAFE_CACHES：已知可以放心清理的缓存。每个缓存目录在使用前都要通过 _sane_cache_root 检查，
   防止环境变量（比如 TEMP）被设成主目录或磁盘根目录时误清一大片。
新增受保护目录、新增可清理缓存，都只改这个文件。
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


def _strip(p: str) -> str:
    s = p.rstrip("\\/")
    if WINDOWS and len(s) == 2 and s[1] == ":":
        return s + "\\"          # "c:" 是“当前目录”，根目录要写成 "c:\"
    return s or os.sep


def _norm(p: Path | str) -> str:
    """解析链接后的真实路径（小写化，去掉结尾分隔符）。"""
    try:
        resolved = Path(p).resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(p))
    return _strip(os.path.normcase(str(resolved)))


def _lex(p: Path | str) -> str:
    """不解析链接的字面路径。保护判断时“字面”和“真实”两种路径都要查。"""
    return _strip(os.path.normcase(os.path.abspath(str(p))))


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


def _keep_list() -> list[str]:
    """这些文件夹本身（以及它们的上级）不能删；里面的文件可以。"""
    home = Path.home()
    names = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive",
             "Favorites", "Contacts", "Saved Games", "Searches", "Links", "3D Objects", "source"]
    items = [str(home)] + [str(home / n) for n in names]
    if WINDOWS:
        sd = (_env("SystemDrive") or "C:") + "\\"
        items += [sd + "Users", sd + "Users\\Public", _env("USERPROFILE"), _env("APPDATA"), _env("LOCALAPPDATA")]
    return [_norm(p) for p in items if p]


def _cloud_list() -> list[str]:
    items = [_env("OneDrive"), _env("OneDriveConsumer"), _env("OneDriveCommercial")]
    try:
        items += [e.path for e in os.scandir(Path.home()) if e.is_dir() and e.name.lower().startswith("onedrive")]
    except OSError:
        pass
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
            SafeCache("crashdumps", "崩溃转储", (_local("CrashDumps"),)),
            SafeCache("wer", "错误报告", (_local("Microsoft", "Windows", "WER", "ReportArchive"),
                                         _local("Microsoft", "Windows", "WER", "ReportQueue"))),
        ]
    else:
        caches = [
            SafeCache("pip", "pip 缓存", (_home(".cache", "pip"),)),
            SafeCache("npm", "npm 缓存", (_home(".npm", "_cacache"),)),
            SafeCache("uv", "uv 缓存", (_home(".cache", "uv"),)),
            SafeCache("chrome", "Chrome 缓存", (_home(".cache", "google-chrome", "*", "Cache"),)),
        ]
    # 只认名字像安装包的；直接从下载里运行的便携程序（比如 xxx.exe）不算。默认不勾选。
    caches.append(SafeCache("installers", "下载里的旧安装包", (_home("Downloads"),),
                            patterns=("*.msi", "*setup*.exe", "*install*.exe", "*installer*.exe",
                                      "*.dmg", "*.pkg"),
                            min_age_days=30, default=False))
    return [c for c in caches if all(c.roots)]


SAFE_CACHES: list[SafeCache] = _build_safe_caches()

_HARD = _hard_list()
_SOFT = _soft_list()
_KEEP = _keep_list()
_CLOUD = _cloud_list()
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


def is_link(path: Path | str) -> bool:
    """符号链接或目录联接（junction）。"""
    p = str(path)
    if os.path.islink(p):
        return True
    isj = getattr(os.path, "isjunction", None)  # Python 3.12+
    if isj and isj(p):
        return True
    if WINDOWS:
        try:
            import stat as _st
            attrs = getattr(os.lstat(p), "st_file_attributes", 0)
            return bool(attrs & _st.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return False
    return False


def _sane_cache_root(root: str, cache: SafeCache) -> bool:
    """缓存目录必须“像个缓存目录”：不能是磁盘根目录、主目录、系统目录，
    也不能是任何重要文件夹的上级；清理全部内容（patterns 为 *）时，也不能就是重要文件夹本身。"""
    r = _norm(root)
    if is_drive_root(r) or is_hard_protected(r) or any(_inside(r, c) for c in _CLOUD):
        return False
    for k in _KEEP:
        if _inside(k, r, strict=True):        # r 是重要文件夹的上级
            return False
        if r == k and cache.patterns == ("*",):  # 要清空整个重要文件夹
            return False
    if cache.key == "temp" and os.path.basename(r).lower() not in ("temp", "tmp"):
        return False
    return True


def safe_cache_roots(cache: SafeCache) -> list[str]:
    out = []
    for pattern in cache.roots:
        for p in glob.glob(pattern) if any(ch in pattern for ch in "*?[") else [pattern]:
            if os.path.isdir(p) and not is_link(p) and _sane_cache_root(p, cache):
                out.append(_norm(p))
    return out


_roots_memo: tuple[float, list[str]] = (0.0, [])


def _all_safe_roots() -> list[str]:
    """所有可清理缓存目录。一次清理会检查成千上万个文件，结果缓存 2 秒，避免反复扫目录。"""
    import time
    global _roots_memo
    now = time.monotonic()
    if now - _roots_memo[0] > 2:
        roots: list[str] = []
        for c in SAFE_CACHES:
            roots += safe_cache_roots(c)
        _roots_memo = (now, roots)
    return list(_EXTRA_SAFE) + _roots_memo[1]


def is_in_safe_cache(path: Path | str) -> bool:
    """path 在某个可清理缓存目录 *里面*（不是缓存目录本身）。"""
    target = _norm(path)
    return any(_inside(target, r, strict=True) for r in _all_safe_roots())


def is_drive_root(path: Path | str) -> bool:
    p = Path(_norm(path))
    return p.parent == p or str(p) == os.sep


def is_hard_protected(path: Path | str) -> bool:
    targets = {_norm(path), _lex(path)}
    return any(_inside(t, b) for t in targets for b in _HARD + _EXTRA)


def is_protected(path: Path | str) -> bool:
    """扫描时用：系统目录和程序数据目录都返回 True。字面路径和真实路径都查。"""
    targets = {_norm(path), _lex(path)}
    return is_hard_protected(path) or any(_inside(t, b) for t in targets for b in _SOFT)


def is_keep_root(path: Path | str) -> bool:
    """是重要文件夹本身，或者是它们的上级。"""
    targets = {_norm(path), _lex(path)}
    return any(t == k or _inside(k, t, strict=True) for t in targets for k in _KEEP)


def is_in_cloud(path: Path | str) -> bool:
    targets = {_norm(path), _lex(path)}
    return any(_inside(t, c) for t in targets for c in _CLOUD)


def can_delete(path: Path | str) -> tuple[bool, str]:
    """删除前的最终检查。返回 (是否允许, 原因)。原因会直接显示给用户，要说人话。"""
    p = str(path)
    if not os.path.lexists(p):
        return False, "文件已经不在了"
    if is_link(p):
        return False, "这是一个快捷链接，不是真正的文件"
    if is_drive_root(p):
        return False, "不能删除整个磁盘"
    if is_hard_protected(p):
        return False, "系统文件，留白不会动它"
    if is_keep_root(p):
        return False, "这是你的个人文件夹本身，只能删里面的文件"
    if is_in_cloud(p):
        return False, "OneDrive 里的文件删了会同步删掉云端的那份，留白不处理"
    # 字面路径和真实路径都要在可清理缓存里，才能删程序数据目录里的东西
    if is_protected(p) and not (is_in_safe_cache(p) and _in_safe_lex(p)):
        return False, "程序数据，不在可放心清理的名单里"
    return True, ""


def _in_safe_lex(path: Path | str) -> bool:
    target = _lex(path)
    return any(_inside(target, r, strict=True) for r in _all_safe_roots())
