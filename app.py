from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


def _load_env_file(path: Path) -> None:
    """llm.env 같은 KEY=VALUE 파일을 읽어 환경변수로 올린다.
    이미 셸에서 지정한 값은 덮어쓰지 않는다(셸 우선)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# LLM 설정 자동 로드 (chatbot import 전에 환경변수를 먼저 세팅)
_load_env_file(ROOT / "llm.env")

from chatbot import ChatbotPipeline  # noqa: E402
from prompt_builder import build_system_prompt  # noqa: E402

PIPELINE = ChatbotPipeline()
DEFAULT_STYLE_INTENSITY = 5
APP_VERSION = "chunbae-nonstream-20260617"


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/":
            self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send_json({"mode": PIPELINE.mode(), "version": APP_VERSION})
            return
        if path == "/api/prompt":
            self._send_json({"prompt": build_system_prompt(DEFAULT_STYLE_INTENSITY)})
            return
        file_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if WEB_ROOT.resolve() in file_path.parents and file_path.exists():
            self._send_file(file_path, _content_type(file_path))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path not in {"/api/chat", "/api/chat/stream"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            message = str(payload.get("message", ""))
            history = payload.get("history", [])
            if self.path == "/api/chat/stream":
                self._send_event_stream(PIPELINE.stream_reply(message, intensity=DEFAULT_STYLE_INTENSITY, history=history))
                return
            self._send_json(PIPELINE.reply(message, intensity=DEFAULT_STYLE_INTENSITY, history=history))
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=400)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_event_stream(self, events) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for event in events:
            data = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
            self.wfile.write(data)
            self.wfile.flush()


def _content_type(path: Path) -> str:
    return {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")


def main() -> None:
    parser = argparse.ArgumentParser(description="박춘배 챗봇 서버")
    # Render 등 호스트는 0.0.0.0 바인딩과 $PORT 환경변수를 요구한다. 로컬도 그대로 동작한다.
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"serving http://{args.host}:{args.port}  (mode: {PIPELINE.mode()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
