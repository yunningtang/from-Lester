"""开发用：在浏览器里打开界面，后端就是真正的 core.api.Api。

    python devserver.py            # 然后打开 http://127.0.0.1:8765

只监听本机。界面里的“移到回收站”会真的移动文件，请在测试用的文件夹里试
（比如设置 HOME / USERPROFILE 指向一个假的主目录）。
"""
from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.api import Api

WEB = Path(__file__).resolve().parent / "webui"
api = Api()
ALLOWED = {"state", "scan", "cancel", "inspect", "set_keep", "plan", "execute", "clear_job",
           "history", "open_recycle_bin", "reveal", "open_storage_settings", "win_minimize", "win_toggle_max", "win_close"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def log_message(self, *a):
        pass

    def do_POST(self):
        name = self.path.rsplit("/", 1)[-1]
        if not self.path.startswith("/api/") or name not in ALLOWED:
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        args = json.loads(self.rfile.read(n) or b"[]")
        try:
            out = getattr(api, name)(*args)
            body = json.dumps(out, ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"http://127.0.0.1:{port}  (Ctrl+C 退出)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
