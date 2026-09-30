"""Minimal loopback HTTP service. Run from the repository with python -m prometheus_voice.server."""
from __future__ import annotations

import json
import os
from pathlib import Path
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .action_timeline import ActionTimeline
from .device_transcript import DeviceTranscript
from .config import load_settings
from .token_broker import AssemblyAIVoiceTokenBroker
from .evidence import EvidenceLedger
from .workflow import GovernedWorkflow, WorkflowError
from .x6_client import X6CapabilityClient, X6Unavailable


def create_server(broker, host: str = "127.0.0.1", port: int = 8780, *, workflow=None, x6_client=None):
    if host != "127.0.0.1":
        raise ValueError("server requires IPv4 loopback")

    device_transcript = DeviceTranscript()
    action_timeline = ActionTimeline()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PrometheusVoice"
        sys_version = ""

        def log_message(self, format, *args):
            # Request paths and exception details must never enter logs.
            pass

        def respond(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self' wss://agents.assemblyai.com; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "microphone=(self), camera=()")
            self.end_headers()
            self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            self.respond(code, {"error": "request rejected"})

        def do_POST(self):
            authority = f"127.0.0.1:{self.server.server_port}"
            if (self.headers.get_all("Host") != [authority]
                    or self.headers.get_all("Origin") != [f"http://{authority}"]
                    or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin")):
                self.respond(403, {"error": "request rejected"})
                return
            routes = {"/api/action-events":"events", "/api/governed/plan": "prepare", "/api/governed/execute": "execute", "/api/camera/capture": "camera", "/api/device/transcript": "transcript", "/api/camera/preview/clear": "clear"}
            if self.path not in routes:
                self.respond(404, {"error": "not found"})
                return
            if workflow is None and self.path not in ('/api/action-events', '/api/camera/capture', '/api/device/transcript', '/api/camera/preview/clear'):
                self.respond(503, {"error": "workflow unavailable"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                    or not lengths[0].isascii() or not lengths[0].isdigit()
                    or len(lengths[0]) > 5 or not 1 <= int(lengths[0]) <= 8192):
                self.respond(413, {"error": "invalid request size"})
                return
            if self.headers.get_all("Content-Type") != ["application/json"]:
                self.respond(415, {"error": "JSON required"})
                return
            self.connection.settimeout(3)
            try:
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise ValueError
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError, OSError):
                self.respond(400, {"error": "invalid JSON request"})
                return
            try:
                if self.path == '/api/action-events':
                    try: action_timeline.publish(payload)
                    except (ValueError, TypeError):
                        self.respond(400, {'error':'invalid event'}); return
                    self.respond(200, {'status':'ok'}); return
                if self.path == '/api/camera/preview/clear':
                    if payload != {} or x6_client is None:
                        self.respond(400, {'error':'invalid request'}); return
                    x6_client.camera_preview(clear=True)
                    self.respond(200, {'status':'cleared'}); return
                if self.path == '/api/device/transcript':
                    try:
                        device_transcript.publish(payload)
                    except ValueError:
                        self.respond(400, {'error':'invalid transcript'}); return
                    self.respond(200, {'status':'ok'}); return
                if self.path == '/api/camera/capture':
                    if payload != {} or x6_client is None:
                        self.respond(400, {'error':'invalid camera request'}); return
                    result = x6_client.camera()
                else:
                    result = getattr(workflow, routes[self.path])(payload)
            except WorkflowError as exc:
                self.respond(exc.status, {"error": exc.code})
                return
            except Exception:
                # HTTP boundary: never reflect internal exception details.
                self.respond(500, {"error": "workflow unavailable"})
                return
            self.respond(200, result)

        def do_GET(self):
            authority = f"127.0.0.1:{self.server.server_port}"
            # Reject cross-site browser requests and DNS rebinding hosts.
            if (self.headers.get_all("Host") != [authority]
                    or self.headers.get("Origin") not in (None, f"http://{authority}")
                    or self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin")):
                self.respond(403, {"error": "request rejected"})
                return
            if self.path == "/api/device/transcript":
                self.respond(200, device_transcript.snapshot()); return
            if self.path == '/api/camera/preview':
                try:
                    if x6_client is None: raise ValueError()
                    photo=x6_client.camera_preview()
                    self.respond(200 if photo else 204, photo or b'', 'image/jpeg'); return
                except Exception:
                    self.respond(503, {'error':'preview unavailable'}); return
            if self.path == '/api/action-events':
                self.respond(200, action_timeline.snapshot()); return
            assets = {
                '/action-timeline.js': ('action-timeline.js', 'text/javascript; charset=utf-8'),
                '/camera-preview.js': ('camera-preview.js', 'text/javascript; charset=utf-8'),
                "/device-transcript.js": ("device-transcript.js", "text/javascript; charset=utf-8"),
                "/x6.js": ("x6.js", "text/javascript; charset=utf-8"),
                "/news.js": ("news.js", "text/javascript; charset=utf-8"),
                "/sentinel.js": ("sentinel.js", "text/javascript; charset=utf-8"),
                "/camera.js": ("camera.js", "text/javascript; charset=utf-8"),
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.css": ("app.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/voice-session.js": ("voice-session.js", "text/javascript; charset=utf-8"),
                "/voice-audio.js": ("voice-audio.js", "text/javascript; charset=utf-8"),
                "/pcm-worklet.js": ("pcm-worklet.js", "text/javascript; charset=utf-8"),
                "/governed.js": ("governed.js", "text/javascript; charset=utf-8"),
            }
            if self.path in assets:
                filename, content_type = assets[self.path]
                try:
                    body = files("prometheus_voice").joinpath("static", filename).read_bytes()
                except (OSError, ModuleNotFoundError):
                    self.respond(503, {"error": "interface unavailable"})
                    return
                self.respond(200, body, content_type)
            elif self.path in ("/api/x6/capabilities", "/api/x6/information", "/api/x6/sentinel", "/api/x6/sentinel-air"):
                if x6_client is None:
                    self.respond(503, {"error": "X6_NOT_ENABLED"})
                    return
                try:
                    result = (x6_client.sentinel_air() if self.path.endswith('/sentinel-air') else
                              x6_client.sentinel() if self.path.endswith('/sentinel') else
                              x6_client.information() if self.path.endswith('/information')
                              else x6_client.snapshot())
                except X6Unavailable as exc:
                    code = str(exc)
                    self.respond(503, {"error": code if code in {
                        "X6_NOT_ENABLED", "X6_QUERY_BUSY", "X6_QUERY_UNAVAILABLE"
                    } else "X6_QUERY_UNAVAILABLE"})
                    return
                except Exception:
                    self.respond(503, {"error": "X6_QUERY_UNAVAILABLE"})
                    return
                self.respond(200, result)
            elif self.path == "/health":
                self.respond(200, {"status": "ok"})
            elif self.path == "/api/voice-token":
                try:
                    token = broker.mint(max_session_duration_seconds=150)
                    if not isinstance(token, str) or not token:
                        raise ValueError("invalid token")
                except Exception:
                    self.respond(502, {"error": "voice token unavailable"})
                    return
                self.respond(200, {"token": token})
            else:
                self.respond(404, {"error": "not found"})

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            # Avoid traceback logging, including upstream response content.
            pass

    return Server((host, port), Handler)


def main():
    try:
        settings = load_settings()
        Path("evidence").mkdir(mode=0o700, exist_ok=True)
        workflow = GovernedWorkflow(EvidenceLedger("evidence/execution.jsonl"))
        server = create_server(AssemblyAIVoiceTokenBroker(settings.assemblyai_api_key),
                               settings.host, settings.port, workflow=workflow,
                               x6_client=X6CapabilityClient(enabled=os.environ.get("PROMETHEUS_X6_READ_ENABLED") == "1"))
    except Exception:
        raise SystemExit("server startup failed") from None
    with server:
        print(f"PROMETHEUS VOICE listening on http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
