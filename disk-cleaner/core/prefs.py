"""用户的选择：说过“留着”的文件，以后不再提醒。存在 %LOCALAPPDATA%\\Liubai\\prefs.json。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def default_path() -> Path:
    if getattr(sys, "frozen", False) or os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Liubai" / "prefs.json"
    return Path(__file__).resolve().parent.parent / "logs" / "prefs.json"


class Prefs:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.keep: set[str] = set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.keep = set(data.get("keep", []))
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"keep": sorted(self.keep)}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)   # 先写临时文件再替换，断电也不会写坏
        except OSError:
            pass

    def set_keep(self, path: str, on: bool) -> None:
        (self.keep.add if on else self.keep.discard)(path)
        self.save()
