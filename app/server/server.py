#!/usr/bin/env python3
"""Open Games 静态服务端

只依赖 Python 标准库，用于在飞牛 fnOS 上托管「游戏选择面板 + 单文件网页游戏」。

    server.py --port 8468 --root ../www
"""

import argparse
import gzip
import json
import os
import posixpath
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}

COMPRESSIBLE = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".md"}
GZIP_MIN_SIZE = 1024
GZIP_CACHE = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenGames/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # 由 run() 注入
    root = "."
    path_prefixes = ()

    # ---------- 日志 ----------
    def log_message(self, fmt, *args):
        # 只记录错误，避免轮询类请求刷满日志
        if str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stdout.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))
            sys.stdout.flush()

    # ---------- 路由 ----------
    def do_GET(self):
        self._handle(head=False)

    def do_HEAD(self):
        self._handle(head=True)

    def _handle(self, head):
        raw_path = urllib.parse.urlsplit(self.path).path or "/"
        path = urllib.parse.unquote(raw_path)
        path = posixpath.normpath(path)

        if path in ("/healthz", "/health"):
            body = json.dumps({"status": "ok", "app": "Open-Games", "version": VERSION}).encode()
            return self._send(head, HTTPStatus.OK, body, "application/json; charset=utf-8")

        for prefix in self.path_prefixes:
            if path == prefix:
                path = "/"
                break
            if path.startswith(prefix + "/"):
                path = path[len(prefix):]
                break

        target = self._resolve(path)
        if target is None:
            return self._not_found(head)

        if os.path.isdir(target):
            if not raw_path.endswith("/"):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", raw_path + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            index = os.path.join(target, "index.html")
            if os.path.isfile(index):
                target = index
            else:
                return self._not_found(head)

        if not os.path.isfile(target):
            return self._not_found(head)

        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")

        try:
            with open(target, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            return self._send(head, HTTPStatus.INTERNAL_SERVER_ERROR, str(exc).encode(),
                              "text/plain; charset=utf-8")

        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if accepts_gzip and ext in COMPRESSIBLE and len(data) >= GZIP_MIN_SIZE:
            cached = GZIP_CACHE.get(target)
            if cached is None or cached[0] != len(data):
                cached = (len(data), gzip.compress(data, 5))
                GZIP_CACHE[target] = cached
            data = cached[1]
            self._send(head, HTTPStatus.OK, data, ctype, encoding="gzip")
            return

        self._send(head, HTTPStatus.OK, data, ctype)

    def _not_found(self, head):
        body = (
            "<!doctype html><meta charset=utf-8><title>404 · Open Games</title>"
            "<body style=\"background:#080b10;color:#8d9bae;font-family:system-ui,sans-serif;"
            "display:grid;place-items:center;height:100vh;margin:0\">"
            "<div style=\"text-align:center\"><h1 style=\"color:#e8eef6;margin:0 0 8px;"
            "font-size:44px\">404</h1><p style=\"margin:0\">页面不存在 · "
            "<a style=\"color:#5ec8ff;text-decoration:none\" href=\"/\">返回游戏库</a></p></div>"
        )
        return self._send(head, HTTPStatus.NOT_FOUND, body.encode(), "text/html; charset=utf-8")

    def _resolve(self, path):
        """把 URL 路径安全地映射到 root 下的真实文件。"""
        rel = path.lstrip("/")
        target = os.path.normpath(os.path.join(self.root, rel))
        root = os.path.normpath(self.root)
        if target != root and not target.startswith(root + os.sep):
            return None
        return target

    def _send(self, head, status, body, ctype, encoding=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        # 游戏为单文件页面，面板封面更新不频繁；短缓存避免升级后看到旧内容
        self.send_header("Cache-Control", "no-cache" if ctype.startswith("text/html") else "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # 端口探活、浏览器中途关闭页面会触发连接重置，不必写日志
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open Games static server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRIM_SERVICE_PORT") or 8468))
    parser.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "www"))
    parser.add_argument("--prefix", action="append", default=[])
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.stderr.write("web root not found: %s\n" % root)
        return 1

    prefixes = {"", "/Open-Games", "/open-games", "/opengames", "/app/Open-Games"}
    prefixes.update(p.rstrip("/") for p in args.prefix)
    Handler.root = root
    Handler.path_prefixes = tuple(sorted((p for p in prefixes if p), key=len, reverse=True))

    httpd = Server((args.host, args.port), Handler)
    sys.stdout.write("Open-Games %s serving %s on http://%s:%d\n" % (VERSION, root, args.host, args.port))
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
