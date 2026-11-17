#!/usr/bin/env python3
"""Open Games 静态服务端

只依赖 Python 标准库，用于在飞牛 fnOS 上托管「游戏选择面板 + 单文件网页游戏」。

    server.py --port 8468 --root ../www
"""

import argparse
import gzip
import hashlib
import json
import os
import posixpath
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
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

# ---------- 大游戏资源包（放不进安装包的那些） ----------
# 清单在 www/extras.json；下载地址指向 GitHub Release 的资源包。
EXTRAS_FILE = "extras.json"
EXTRAS_TARGET_PREFIX = "games/"
EXTRAS_STATE = {}
EXTRAS_LOCK = threading.Lock()
EXTRAS_CHUNK = 1 << 20


def _extras_manifest(root):
    path = os.path.join(root, EXTRAS_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _extras_entry(root, key):
    """把清单里的一条记录校验成可以放心下载解压的形状。"""
    if not key or "/" in key or "\\" in key or key.startswith("."):
        return None
    raw = _extras_manifest(root).get(key)
    if not isinstance(raw, dict):
        return None
    url = raw.get("url")
    target = raw.get("target")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    if not isinstance(target, str) or not target.replace("\\", "/").startswith(EXTRAS_TARGET_PREFIX):
        return None
    parts = target.replace("\\", "/").split("/")
    if ".." in parts or ".installed.json" in parts:
        return None
    try:
        size = int(raw.get("bytes") or 0)
    except (TypeError, ValueError):
        size = 0
    digest = raw.get("sha256")
    rev = raw.get("rev")
    mirrors = raw.get("mirrors")
    if not isinstance(mirrors, list):
        mirrors = []
    return {
        "key": key,
        "title": raw.get("title") or key,
        "url": url,
        "mirrors": [m for m in mirrors if isinstance(m, str) and m.startswith(("http://", "https://"))],
        "target": os.path.join(*parts),
        "bytes": max(0, size),
        "sha256": digest.strip().lower() if isinstance(digest, str) else "",
        "rev": rev.strip() if isinstance(rev, str) else "",
    }


def _extras_marker(root, entry):
    """上次安装时写下的标记：用来判断装的是不是当前这一版资源包。"""
    path = os.path.join(root, entry["target"], ".installed.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _extras_installed(root, entry):
    return os.path.isfile(os.path.join(root, entry["target"], "index.html"))


def _extras_stale(root, entry):
    """已安装、但装的是旧资源包 —— 通常是远端换了包并改了 rev。"""
    if not _extras_installed(root, entry) or not entry["rev"]:
        return False
    return str(_extras_marker(root, entry).get("rev") or "") != entry["rev"]


def _extras_state(key):
    with EXTRAS_LOCK:
        return dict(EXTRAS_STATE.get(key) or {})


def _extras_patch(key, **fields):
    with EXTRAS_LOCK:
        state = EXTRAS_STATE.setdefault(key, {})
        state.update(fields)
        state["updatedAt"] = int(time.time())


def _extras_status(root, entry):
    state = _extras_state(entry["key"])
    total = entry["bytes"] or int(state.get("total") or 0)
    downloading = bool(state.get("downloading"))
    error = state.get("error") or ""
    received = int(state.get("received") or 0)
    installed = _extras_installed(root, entry)
    stale = _extras_stale(root, entry)
    # 空闲且未安装时不要把上一轮的进度当成当前进度显示
    if not downloading and not error and not installed:
        received = 0
    return {
        "key": entry["key"],
        "title": entry["title"],
        "installed": installed,
        "stale": stale,
        "rev": entry["rev"],
        "downloading": downloading,
        "received": received,
        "total": total,
        "error": error,
        "url": entry["url"],
        "updatedAt": int(state.get("updatedAt") or 0),
    }


def _extras_cache_dir(root):
    # 解压与下载的中间文件放在 www 之外，避免被当成静态资源访问
    pkgvar = os.environ.get("TRIM_PKGVAR")
    base = pkgvar if pkgvar and os.path.isdir(pkgvar) else os.path.join(root, os.pardir, ".extras-cache")
    return os.path.abspath(base)


def _safe_extract(zip_path, dest):
    dest_abs = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name or name.endswith("/"):
                continue
            target = os.path.abspath(os.path.join(dest_abs, name))
            if target != dest_abs and not target.startswith(dest_abs + os.sep):
                raise ValueError("压缩包条目越界：%s" % name)
        zf.extractall(dest_abs)
    # 若压缩包套了一层同名目录，取那一层，避免变成 games/x/x/index.html
    items = [i for i in os.listdir(dest_abs) if not i.startswith(".")]
    if len(items) == 1:
        single = os.path.join(dest_abs, items[0])
        if os.path.isdir(single) and os.path.isfile(os.path.join(single, "index.html")):
            return single
    return dest_abs


def _extras_download(key, entry, part):
    """按 url + mirrors 的顺序下载，任何一个成功就返回字节数；
    全失败时把每次尝试的错误拼起来，前端据此给出可操作的提示。"""
    urls = [entry["url"]] + [m for m in entry["mirrors"] if m != entry["url"]]
    failures = []
    for url in urls:
        received = 0
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Open-Games/" + VERSION,
                "Accept": "application/zip,application/octet-stream,*/*",
            })
            with urllib.request.urlopen(request, timeout=45) as response, open(part, "wb") as fh:
                header_total = int(response.headers.get("Content-Length") or 0)
                _extras_patch(key, total=entry["bytes"] or header_total, source=url)
                while True:
                    chunk = response.read(EXTRAS_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    _extras_patch(key, received=received)
            if entry["bytes"] and received != entry["bytes"]:
                raise ValueError("大小不符（%d / %d 字节）" % (received, entry["bytes"]))
            if entry["sha256"]:
                digest = hashlib.sha256()
                with open(part, "rb") as fh:
                    for chunk in iter(lambda: fh.read(EXTRAS_CHUNK), b""):
                        digest.update(chunk)
                if digest.hexdigest() != entry["sha256"]:
                    raise ValueError("sha256 校验不通过（远端文件不是这一版）")
            return received
        except urllib.error.HTTPError as exc:
            failures.append("%s → HTTP %d %s" % (url, exc.code, exc.reason))
        except Exception as exc:  # 超时、DNS、TLS、磁盘都记下来继续试下一个地址
            failures.append("%s → %s" % (url, exc))
        try:
            os.remove(part)
        except OSError:
            pass
    raise RuntimeError("；".join(failures))


def _extras_worker(root, entry):
    key = entry["key"]
    cache = _extras_cache_dir(root)
    work = os.path.join(cache, key)
    part = os.path.join(cache, key + ".zip.part")
    zip_path = os.path.join(cache, key + ".zip")
    extract_dir = os.path.join(work, "unpacked")
    target_abs = os.path.join(root, entry["target"])

    try:
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, exist_ok=True)
        _extras_patch(key, downloading=True, received=0, total=entry["bytes"], error="",
                      phase="download")

        received = _extras_download(key, entry, part)

        os.replace(part, zip_path)
        _extras_patch(key, phase="extract")
        source = _safe_extract(zip_path, extract_dir)

        if os.path.isdir(target_abs):
            shutil.rmtree(target_abs)
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        shutil.move(source, target_abs)

        with open(os.path.join(target_abs, ".installed.json"), "w", encoding="utf-8") as fh:
            json.dump({"url": entry["url"], "rev": entry["rev"], "bytes": received,
                       "sha256": entry["sha256"], "installedAt": int(time.time())}, fh)

        shutil.rmtree(work, ignore_errors=True)
        try:
            os.remove(zip_path)
        except OSError:
            pass
        _extras_patch(key, downloading=False, received=received, total=received,
                      phase="done", error="")
        sys.stdout.write("%s - extras %s installed (%d bytes)\n"
                         % (time.strftime("%Y-%m-%d %H:%M:%S"), key, received))
        sys.stdout.flush()
    except PermissionError as exc:
        _extras_patch(key, downloading=False, phase="error",
                      error="无法写入 %s（%s）：请确认应用目录对运行账号可写"
                            % (entry["target"], exc.strerror or "permission denied"))
        sys.stdout.write("%s - extras %s permission denied\n"
                         % (time.strftime("%Y-%m-%d %H:%M:%S"), key))
        sys.stdout.flush()
        try:
            os.remove(part)
        except OSError:
            pass
    except Exception as exc:  # 网络/磁盘/校验失败都记在状态里，由前端展示
        _extras_patch(key, downloading=False, phase="error", error=str(exc)[:300])
        sys.stdout.write("%s - extras %s failed: %s\n"
                         % (time.strftime("%Y-%m-%d %H:%M:%S"), key, exc))
        sys.stdout.flush()
        try:
            os.remove(part)
        except OSError:
            pass


def _extras_start(root, entry):
    with EXTRAS_LOCK:
        state = EXTRAS_STATE.setdefault(entry["key"], {})
        if state.get("downloading"):
            return False
        state.update({"downloading": True, "error": "", "received": 0, "phase": "start"})
        state["updatedAt"] = int(time.time())
    thread = threading.Thread(target=_extras_worker, args=(root, entry), daemon=True)
    thread.start()
    return True


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

    def do_POST(self):
        self._drain_body()
        raw_path = urllib.parse.urlsplit(self.path).path or "/"
        path = self._strip_prefix(posixpath.normpath(urllib.parse.unquote(raw_path)))
        parts = [p for p in path.split("/") if p]
        # POST /api/extras/<key>/install —— 触发一次后台下载 + 解压
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "extras" and parts[3] == "install":
            entry = _extras_entry(self.root, parts[2])
            if entry is None:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown extra"})
            if _extras_installed(self.root, entry):
                return self._json(HTTPStatus.OK, dict(_extras_status(self.root, entry), started=False))
            started = _extras_start(self.root, entry)
            return self._json(HTTPStatus.ACCEPTED,
                              dict(_extras_status(self.root, entry), started=started))
        self._json(HTTPStatus.NOT_FOUND, {"error": "no such endpoint"})

    def _drain_body(self):
        """POST 的请求体必须读完，否则 keep-alive 连接上残留的字节
        会被当成下一个请求行（游戏用 sendBeacon 打点就会触发）。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            # 不解析 chunked：直接断开，交给浏览器重连
            self.close_connection = True
            return
        remaining = max(0, length)
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _strip_prefix(self, path):
        for prefix in self.path_prefixes:
            if path == prefix:
                return "/"
            if path.startswith(prefix + "/"):
                return path[len(prefix):]
        return path

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle(self, head):
        raw_path = urllib.parse.urlsplit(self.path).path or "/"
        path = urllib.parse.unquote(raw_path)
        path = posixpath.normpath(path)

        if path in ("/healthz", "/health"):
            body = json.dumps({"status": "ok", "app": "Open-Games", "version": VERSION}).encode()
            return self._send(head, HTTPStatus.OK, body, "application/json; charset=utf-8")

        path = self._strip_prefix(path)

        parts = [p for p in path.split("/") if p]
        # GET /api/extras —— 清单 + 每个资源包当前状态
        if parts and parts[0] == "api" and len(parts) >= 2 and parts[1] == "extras":
            if len(parts) == 2:
                payload = []
                for key in _extras_manifest(self.root):
                    entry = _extras_entry(self.root, key)
                    if entry:
                        payload.append(_extras_status(self.root, entry))
                return self._json(HTTPStatus.OK, {"items": payload})
            if len(parts) == 3:
                entry = _extras_entry(self.root, parts[2])
                if entry is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown extra"})
                return self._json(HTTPStatus.OK, _extras_status(self.root, entry))
            if len(parts) == 4 and parts[3] == "status":
                entry = _extras_entry(self.root, parts[2])
                if entry is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown extra"})
                return self._json(HTTPStatus.OK, _extras_status(self.root, entry))
            return self._json(HTTPStatus.NOT_FOUND, {"error": "no such endpoint"})

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
