"""Local-only HTTP entry for the minimal Economy-guy GUI.

This is a trusted local host, not a production web service. It binds to
127.0.0.1, accepts a fixed actor/workbook from the command line, and never
accepts user_id, approved or confirmed from the browser.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .gui_host import GuiError, GuiHost


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, host, token, html):
        self.host = host
        self.token = token
        self.html = html
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "EconomyGuyGui/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("gui: " + (fmt % args) + "\n")

    def _json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message, code="error"):
        self._json(status, {"ok": False, "error": message, "code": code})

    def _authorized(self):
        return secrets.compare_digest(
            self.headers.get("X-GUI-Token", ""), self.server.token
        )

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 200_000:
            raise GuiError("请求体为空或过大。")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise GuiError("请求不是合法 JSON。") from None
        if not isinstance(value, dict):
            raise GuiError("请求必须是对象。")
        return value

    def _dispatch(self, name, value):
        host = self.server.host
        try:
            if not isinstance(value.get('context'), dict):
                raise GuiError('缺少当前会话修订，请刷新页面。')
            if name == "message":
                return host.send(value.get("text", ""), context=value.get("context"))
            if name == "switch":
                return host.switch(str(value.get("chat_id", "")), context=value.get("context"))
            if name == "new":
                return host.new(context=value.get("context"))
            if name == "preview_confirm":
                return host.confirm_preview(str(value.get("preview_id", "")), context=value.get('context'))
            if name == "preview_cancel":
                return host.cancel_preview(str(value.get('preview_id','')), context=value.get('context'))
            if name == "pause":
                return host.pause(context=value.get("context"))
            if name == "cancel":
                return host.cancel(context=value.get("context"))
            if name == "resume":
                return host.resume(value.get("id", ""), value.get("revision", 0),
                                   context=value.get("context"))
            if name == "inspect":
                return host.inspect(context=value.get("context"))
            if name == "acknowledge":
                return host.acknowledge_display(str(value.get("trace", "")),
                                                context=value.get("context"))
            if name == 'task_details':
                return host.task_details(str(value.get('company_id','')),str(value.get('task_id','')),context=value.get('context'))
            if name == 'task_open':
                return host.open_task(str(value.get('company_id','')),str(value.get('task_id','')),context=value.get('context'))
            if name == 'profile':
                return host.switch_profile(str(value.get('profile_name','')),context=value.get('context'))
            raise GuiError("未知操作。")
        except GuiError as error:
            self._error(409, str(error), "conflict")
        except (OSError, ValueError) as error:
            self._error(400, str(error), "bad_request")
        except Exception:
            # Keep the client honest: an unexpected exception is never a
            # successful business result.
            self._error(500, "本机宿主处理失败；未确认任何业务成功。", "host_failure")

    def do_GET(self):
        # The page carries the per-process token; the initial browser
        # navigation cannot set X-GUI-Token. JSON endpoints still require it.
        if self.path in {"/", "/index.html"}:
            body = self.server.html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/snapshot":
            if not self._authorized():
                self._error(403, "本机界面令牌无效。", "forbidden")
                return
            try:
                self._json(200, {"ok": True, "snapshot": self.server.host.snapshot()})
            except GuiError as error:
                self._error(409, str(error), "conflict")
            except (OSError, ValueError) as error:
                self._error(400, str(error), "bad_request")
            except Exception:
                self._error(500, "读取会话状态失败。", "host_failure")
            return
        self._error(404, "未找到。", "not_found")

    def do_POST(self):
        if not self._authorized():
            self._error(403, "本机界面令牌无效。", "forbidden")
            return
        route = self.path.removeprefix("/api/")
        if route not in {"message", "switch", "new", "preview_confirm", "preview_cancel",
                         "pause", "cancel", "resume", "inspect", "acknowledge", "task_details", "task_open", "profile"}:
            self._error(404, "未找到。", "not_found")
            return
        try:
            value = self._read_json()
        except GuiError as error:
            self._error(400, str(error), "bad_request")
            return
        result = self._dispatch(route, value)
        if result is not None:
            self._json(200, {"ok": True, "snapshot": result})


def build_html(path, token, user, workbook):
    template = Path(path).read_text(encoding="utf-8")
    return (template.replace("__GUI_TOKEN__", token)
                    .replace("__GUI_USER__", user)
                    .replace("__GUI_WORKBOOK__", str(workbook)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Economy-guy 最小本机 GUI")
    parser.add_argument("--db", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data" / "finance.db",
                        help="已初始化的账簿 SQLite")
    parser.add_argument("--user", default="U001", help="受信宿主绑定的模拟账号")
    parser.add_argument("--session", type=Path, default=None,
                        help="会话库；默认沿用本机 conversations.sqlite3")
    parser.add_argument("--profile", default=None,
                        help="已有本地模型 Profile 名称；不读取明文密钥")
    parser.add_argument("--profiles-file", type=Path, default=None,
                        help="可选的模型 Profile 模板路径")
    parser.add_argument("--profiles-local", type=Path, default=None,
                        help="可选的本地 Profile JSON 路径；不回显内容")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--trace", type=Path, default=None)
    parser.add_argument("--open", action="store_true", help="启动后打开默认浏览器")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print("账簿不存在：" + str(args.db), file=sys.stderr)
        return 2
    try:
        host = GuiHost(args.db, args.user, session_path=args.session,
                       mode="live", profile=args.profile, trace_path=args.trace,
                       profiles_file=args.profiles_file, profiles_local=args.profiles_local)
    except Exception as error:
        print("无法启动 GUI：" + str(error), file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(24)
    html_path = Path(__file__).resolve().parents[1] / "gui" / "index.html"
    if not html_path.is_file():
        print("缺少界面文件：" + str(html_path), file=sys.stderr)
        return 2
    html = build_html(html_path, token, args.user, host.db_path)
    try:
        server = GuiServer((args.host, args.port), host, token, html)
    except OSError as error:
        print("无法监听本机端口：" + str(error), file=sys.stderr)
        return 2
    url = "http://%s:%d/" % (args.host, args.port)
    print("Economy-guy GUI:", url)
    print("账号/账簿：%s / %s" % (args.user, host.db_path))
    print("本机受信宿主；浏览器不能传 user_id/approved/confirmed。按 Ctrl+C 停止。")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
