"""格式化等小工具。"""
from __future__ import annotations

import datetime as _dt

_UNITS = ["B", "KB", "MB", "GB", "TB"]


def human_size(n: int | float) -> str:
    """把字节数转成 1.2 GB 这样的文字。"""
    n = float(n)
    for unit in _UNITS:
        if abs(n) < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_size(text: str) -> int:
    """把 '100MB'、'1.5 GB'、'500' (默认 MB) 转成字节数。"""
    t = text.strip().upper().replace(" ", "")
    if not t:
        raise ValueError("空的大小")
    for i, unit in reversed(list(enumerate(_UNITS))):
        for suffix in (unit, unit[0] if unit != "B" else None):
            if suffix and t.endswith(suffix) and t[: -len(suffix)]:
                try:
                    return int(float(t[: -len(suffix)]) * 1024 ** i)
                except ValueError:
                    pass
    return int(float(t) * 1024 ** 2)


def format_time(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
