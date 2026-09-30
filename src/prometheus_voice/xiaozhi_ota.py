from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Settings, load_settings


def create_server(settings: Settings) -> ThreadingHTTPServer:
    if not settings.xiaozhi_token or not settings.xiaozhi_public_host:
        raise RuntimeError("PROMETHEUS_XIAOZHI_TOKEN and PROMETHEUS_XIAOZHI_PUBLIC_HOST are required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "PrometheusVoiceOTA/1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _reply(self, status: int, value: dict) -> None:
            payload = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            self._reply(200, {"status": "prometheus voice ota online"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 65536:
                self._reply(413, {"error": "request too large"})
                return
            self.rfile.read(length)
            self._reply(200, {
                "server_time": {"timestamp": int(time.time()), "timezone_offset": -10800},
                "firmware": {"version": "2.2.6", "url": ""},
                "websocket": {
                    "url": f"ws://{settings.xiaozhi_public_host}:{settings.xiaozhi_port}",
                    "token": settings.xiaozhi_token,
                    "version": 2,
                },
            })

    return ThreadingHTTPServer((settings.ota_host, settings.ota_port), Handler)


def main() -> None:
    server = create_server(load_settings())
    server.serve_forever()


if __name__ == "__main__":
    main()
