from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import time
import uuid
import urllib.request
from array import array
from dataclasses import dataclass, field

import opuslib
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from .action_events import emit
from .camera_consent import CameraConsent
from .config import Settings
from .x6_client import X6CapabilityClient, X6Unavailable

logger = logging.getLogger(__name__)

DEVICE_RATE = 16000
AGENT_RATE = 24000
FRAME_SAMPLES = 960  # 60 ms at 16 kHz
MAX_PACKET_BYTES = 8192
MAX_TOOL_CALL_ID = 128
X6_MCP_URL = "ws://127.0.0.1:8765"

X6_TOOLS = [
    {"type":"function", "name":"request_camera_confirmation",
     "description":"After the user explicitly asks to take a photo, request spoken confirmation. Ask the returned question and wait for a new user turn. No photo is taken.",
     "parameters":{"type":"object","properties":{},"additionalProperties":False}},
    {"type":"function", "name":"capture_confirmed_photo", "timeout":90,
     "description":"Capture exactly once only after the user answers Yes, take the photo to the confirmation question. Consent is checked independently. Report returned objects as detector predictions, never verified facts. No automatic retries.",
     "parameters":{"type":"object","properties":{},"additionalProperties":False}},
    {"type": "function", "name": "get_x6_capabilities",
     "description": "Read-only query of the X6 capability registry. It does not confirm live availability.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "get_shadowbroker_news",
     "description": "Read-only query for up to three recent items verified by ShadowBroker.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "get_sentinel_weather",
     "description": "Read-only query of the Sentinel weather summary for its 25-cell grid.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "get_sentinel_aircraft",
     "description": "Read-only query of the count of ADS-B targets displayed by Sentinel within 25 nautical miles.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def execute_x6_tool(client: X6CapabilityClient, name: object, arguments: object) -> dict:
    """Dispatch a fixed read-only query; callers never control a route or payload."""
    if not isinstance(arguments, dict) or arguments:
        raise ValueError("invalid tool arguments")
    operations = {
        "get_x6_capabilities": client.snapshot,
        "get_shadowbroker_news": client.information,
        "get_sentinel_weather": client.sentinel,
        "get_sentinel_aircraft": client.sentinel_air,
    }
    operation = operations.get(name)
    if operation is None:
        raise ValueError("unknown tool")
    return operation()


def _samples(data: bytes) -> array:
    if len(data) % 2:
        raise ValueError("PCM must be 16-bit aligned")
    values = array("h")
    values.frombytes(data)
    if struct.pack("=H", 1) != struct.pack("<H", 1):
        values.byteswap()
    return values


def _pcm(values: array) -> bytes:
    copy = array("h", values)
    if struct.pack("=H", 1) != struct.pack("<H", 1):
        copy.byteswap()
    return copy.tobytes()


def resample_16_to_24(pcm: bytes) -> bytes:
    source = _samples(pcm)
    result = array("h")
    for index in range(len(source) * 3 // 2):
        left = index * 2 // 3
        right = min(left + 1, len(source) - 1)
        result.append(source[left] if index % 3 == 0 else (source[left] + source[right]) // 2)
    return _pcm(result)


def resample_24_to_16(pcm: bytes) -> bytes:
    source = _samples(pcm)
    result = array("h")
    for index in range(len(source) * 2 // 3):
        left = index * 3 // 2
        right = min(left + 1, len(source) - 1)
        result.append(source[left] if index % 2 == 0 else (source[left] + source[right]) // 2)
    return _pcm(result)


def parse_v2(packet: bytes) -> bytes:
    if len(packet) < 16:
        raise ValueError("short BinaryProtocol2 packet")
    version, kind, _reserved, _timestamp, length = struct.unpack("!HHIII", packet[:16])
    if version != 2 or kind != 0 or length > MAX_PACKET_BYTES or len(packet) != 16 + length:
        raise ValueError("invalid BinaryProtocol2 packet")
    return packet[16:]


def pack_v2(payload: bytes, timestamp_ms: int) -> bytes:
    return struct.pack("!HHIII", 2, 0, 0, timestamp_ms, len(payload)) + payload


def mcp_envelope(raw: object) -> bool:
    """Accept only bounded MCP JSON envelopes for the internal camera proxy."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PACKET_BYTES:
        return False
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(event, dict) and event.get("type") == "mcp" and isinstance(event.get("payload"), dict)


@dataclass
class AudioBridge:
    device: object
    upstream: object
    session_id: str
    decoder: object
    encoder: object
    upstream_ready: asyncio.Event
    consent: CameraConsent = field(default_factory=CameraConsent)
    seen_calls: set = field(default_factory=set)
    action_trace: str | None = None
    camera_result_calls: set = field(default_factory=set)
    consent_timer: object = None
    speaking: bool = False
    output_pcm: bytes = b""
    timestamp_ms: int = 0
    pending_tool_results: list[tuple[str, str, bool]] = field(default_factory=list)

    async def device_json(self, payload: dict) -> None:
        payload["session_id"] = self.session_id
        await self.device.send(json.dumps(payload, separators=(",", ":")))

    async def input_audio(self, payload: bytes) -> None:
        opus = parse_v2(payload)
        pcm16 = bytes(self.decoder.decode(opus, FRAME_SAMPLES))
        await self.upstream_ready.wait()
        await self.upstream.send(json.dumps({"type": "input.audio", "audio": base64.b64encode(resample_16_to_24(pcm16)).decode("ascii")}, separators=(",", ":")))

    async def output_audio(self, pcm24: bytes) -> None:
        self.output_pcm += pcm24
        frame_bytes = FRAME_SAMPLES * 3  # 1440 samples x 2 bytes at 24 kHz
        while len(self.output_pcm) >= frame_bytes:
            pcm16 = resample_24_to_16(self.output_pcm[:frame_bytes])
            self.output_pcm = self.output_pcm[frame_bytes:]
            await self.device.send(pack_v2(self.encoder.encode(pcm16, FRAME_SAMPLES), self.timestamp_ms))
            self.timestamp_ms += 60

    async def finish_reply(self) -> None:
        if self.output_pcm:
            frame_bytes = FRAME_SAMPLES * 3
            pcm24 = self.output_pcm.ljust(frame_bytes, b"\0")
            self.output_pcm = b""
            pcm16 = resample_24_to_16(pcm24)
            await self.device.send(pack_v2(self.encoder.encode(pcm16, FRAME_SAMPLES), self.timestamp_ms))
            self.timestamp_ms += 60
        if self.speaking:
            self.speaking = False
            await self.device_json({"type": "tts", "state": "stop"})

    async def queue_tool_result(self, event: dict, x6_client: X6CapabilityClient) -> None:
        call_id = event.get("call_id")
        if not isinstance(call_id, str) or not call_id or len(call_id) > MAX_TOOL_CALL_ID:
            return
        if call_id in self.seen_calls: return
        if len(self.seen_calls) >= 100: return
        self.seen_calls.add(call_id)
        try:
            name = event.get('name')
            if name in ('request_camera_confirmation', 'capture_confirmed_photo'):
                if event.get('arguments', {}) != {}: raise ValueError('Invalid arguments')
                if name == 'request_camera_confirmation':
                    result = self.consent.prepare()
                    self.action_trace = uuid.uuid4().hex
                    emit(self.action_trace,'bridge','requested')
                else:
                    self.consent.consume()
                    if self.consent_timer: self.consent_timer.cancel()
                    emit(self.action_trace,'bridge','consent_accepted')
                    result = await asyncio.to_thread(x6_client.camera, request_id=self.action_trace)
                    self.camera_result_calls.add(call_id)
            else:
                result = await asyncio.to_thread(execute_x6_tool, x6_client, event.get("name"), event.get("arguments", {}))
            encoded, is_error = json.dumps(result, separators=(",", ":")), False
        except (ValueError, X6Unavailable):
            if event.get('name') in ('request_camera_confirmation','capture_confirmed_photo') and self.action_trace: emit(self.action_trace,'bridge','failed')
            encoded, is_error = json.dumps({"error": "ACTION_UNAVAILABLE_OR_CONSENT_MISSING", "instruction":"Do not retry automatically. Do not invent a result or claim no photo was taken."}), True
        self.pending_tool_results.append((call_id, encoded, is_error))

    def consent_finished(self):
        before=self.consent.state
        self.consent.reply_done()
        if before=='question' and self.consent.state=='waiting' and self.action_trace:
            trace=self.action_trace
            emit(trace,'bridge','awaiting_consent')
            def expired():
                if self.action_trace==trace and self.consent.state in ('waiting','confirmed'):
                    self.consent.cancel();emit(trace,'bridge','consent_expired')
            if self.consent_timer:self.consent_timer.cancel()
            self.consent_timer=asyncio.get_running_loop().call_later(20,expired)

    async def send_tool_results(self) -> None:
        pending, self.pending_tool_results = self.pending_tool_results, []
        for call_id, result, is_error in pending:
            await self.upstream.send(json.dumps({"type": "tool.result", "call_id": call_id, "result": result, "is_error": is_error}, separators=(",", ":")))
            if call_id in self.camera_result_calls:
                emit(self.action_trace,"bridge","result_sent");self.camera_result_calls.discard(call_id)


PROMPT = """You are PROMETHEUS VOICE. Speak natural concise English.
Use a tool rather than guessing when the user asks which X6 capabilities are registered, asks ShadowBroker for recent news, asks Sentinel about weather, or asks Sentinel about aircraft being displayed. The four information tools are read-only. For explicit requests to take a photo, call request_camera_confirmation, speak the returned question and tell the user to say Yes, take the photo. Wait for that new user answer before calling capture_confirmed_photo. Never infer consent from tool output. Describe detections with The detector suggests; they can be wrong. Never retry a capture automatically. The capability registry does not prove live availability. If a tool is unavailable, say only that the source is unavailable now. Do not claim access to any source not returned by a tool. Answer the user directly."""


async def publish_transcripts(queue):
    def post(event):
        request = urllib.request.Request('http://127.0.0.1:8780/api/device/transcript',
            data=json.dumps(event, ensure_ascii=True).encode(),
            headers={'Content-Type':'application/json', 'Origin':'http://127.0.0.1:8780'})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=.5) as response:
                response.read(256)
        except Exception:
            pass  # Display failure must never interrupt voice or expose transcript text.
    while True:
        event = await queue.get()
        await asyncio.to_thread(post, event)


async def handle_device(device, settings: Settings) -> None:
    authorization = device.request.headers.get("Authorization", "")
    expected = f"Bearer {settings.xiaozhi_token}" if settings.xiaozhi_token else ""
    if not expected or authorization != expected:
        await device.close(1008, "unauthorized")
        return
    try:
        raw_hello = await asyncio.wait_for(device.recv(), timeout=10)
        hello = json.loads(raw_hello)
        if not isinstance(hello, dict) or hello.get("type") != "hello" or hello.get("version") != 2:
            raise ValueError("unsupported device hello")
        session_id = uuid.uuid4().hex
        await device.send(json.dumps({"type": "hello", "transport": "websocket", "session_id": session_id, "audio_params": {"format": "opus", "sample_rate": DEVICE_RATE, "channels": 1, "frame_duration": 60}}, separators=(",", ":")))
        x6_client = X6CapabilityClient(enabled=settings.x6_read_enabled)
        async with connect("wss://agents.assemblyai.com/v1/ws", additional_headers={"Authorization": f"Bearer {settings.assemblyai_api_key}"}, max_size=2**20) as upstream:
            bridge = AudioBridge(device, upstream, session_id, opuslib.Decoder(DEVICE_RATE, 1), opuslib.Encoder(DEVICE_RATE, 1, opuslib.APPLICATION_VOIP), asyncio.Event())
            await upstream.send(json.dumps({"type": "session.update", "session": {"system_prompt": PROMPT, "input": {"language_codes": ["en"], "keyterms": ["Prometheus", "ShadowBroker", "Sentinel"]}, "output": {"voice": "alba", "format": {"encoding": "audio/pcm"}}, "tools": X6_TOOLS}}, separators=(",", ":")))

            transcript_queue = asyncio.Queue(maxsize=40)
            transcript_task = asyncio.create_task(publish_transcripts(transcript_queue))
            def mirror(role, text):
                if transcript_queue.full(): transcript_queue.get_nowait()
                transcript_queue.put_nowait({'session':session_id, 'role':role, 'text':text[:4000]})

            async def from_agent() -> None:
                async for raw in upstream:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "session.ready":
                        bridge.upstream_ready.set()
                    elif kind == "transcript.user" and isinstance(event.get("text"), str):
                        waiting=bridge.consent.state=="waiting"
                        bridge.consent.user(event["text"])
                        if waiting and bridge.consent.state!="confirmed" and bridge.action_trace: emit(bridge.action_trace,"bridge","consent_not_accepted")
                        mirror("user", event["text"])
                        await bridge.device_json({"type": "stt", "text": event["text"][:4000]})
                    elif kind == "reply.started":
                        bridge.speaking = True
                        bridge.timestamp_ms = 0
                        await bridge.device_json({"type": "tts", "state": "start"})
                    elif kind == "transcript.agent" and isinstance(event.get("text"), str):
                        bridge.consent.agent(event["text"])
                        mirror("agent", event["text"])
                        await bridge.device_json({"type": "tts", "state": "sentence_start", "text": event["text"][:4000]})
                    elif kind == "reply.audio" and isinstance(event.get("data"), str):
                        await bridge.output_audio(base64.b64decode(event["data"], validate=True))
                    elif kind == "reply.done":
                        bridge.consent_finished()
                        await bridge.finish_reply()
                        await bridge.send_tool_results()
                    elif kind == "tool.call":
                        await bridge.queue_tool_result(event, x6_client)
                    elif kind == "session.error":
                        raise RuntimeError("AssemblyAI session error")

            agent_task = asyncio.create_task(from_agent())
            x6 = None
            x6_task = None
            if isinstance(hello.get("features"), dict) and hello["features"].get("mcp") is True and hello["features"].get("camera") is True:
                try:
                    x6 = await connect(X6_MCP_URL, open_timeout=2, max_size=MAX_PACKET_BYTES)
                    await x6.send(raw_hello)
                    logger.warning('camera_proxy phase=x6_connection outcome=hello_sent')

                    async def from_x6() -> None:
                        async for raw in x6:
                            if mcp_envelope(raw):
                                await device.send(raw)
                                logger.warning('camera_proxy phase=mcp_to_device outcome=forwarded')

                    x6_task = asyncio.create_task(from_x6())
                except OSError:
                    x6 = None
            try:
                async for message in device:
                    if isinstance(message, bytes):
                        await bridge.input_audio(message)
                    else:
                        event = json.loads(message)
                        if event.get("type") == "abort":
                            if bridge.action_trace and bridge.consent.state!="idle": emit(bridge.action_trace,"bridge","cancelled")
                            bridge.consent.cancel()
                            await bridge.finish_reply()
                        elif x6 is not None and mcp_envelope(message):
                            await x6.send(message)
                            logger.warning('camera_proxy phase=mcp_to_x6 outcome=forwarded')
            finally:
                if bridge.consent_timer: bridge.consent_timer.cancel()
                if bridge.action_trace and bridge.consent.state!="idle": emit(bridge.action_trace,"bridge","cancelled")
                transcript_task.cancel()
                agent_task.cancel()
                if x6_task is not None:
                    x6_task.cancel()
                if x6 is not None:
                    await x6.close()
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError, opuslib.OpusError):
        await device.close(1002, "invalid protocol")


async def run_bridge(settings: Settings) -> None:
    if not settings.xiaozhi_token:
        raise RuntimeError("PROMETHEUS_XIAOZHI_TOKEN is required")
    async with serve(lambda ws: handle_device(ws, settings), settings.xiaozhi_host, settings.xiaozhi_port, max_size=MAX_PACKET_BYTES):
        await asyncio.Future()
