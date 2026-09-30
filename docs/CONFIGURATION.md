# Configuration

Copy `.env.example` to `.env`, set file mode 600 and edit it locally. The application uses a minimal `KEY=value` reader, not a full dotenv implementation. Values should not be surrounded by quotes.

| Setting | Purpose |
| --- | --- |
| `ASSEMBLYAI_API_KEY` | Server-side Voice Agent credential |
| `PROMETHEUS_VOICE_HOST` | Web host; must remain `127.0.0.1` |
| `PROMETHEUS_VOICE_PORT` | Web port; default 8780 |
| `PROMETHEUS_XIAOZHI_HOST` | Optional bridge bind address |
| `PROMETHEUS_XIAOZHI_PORT` | Optional bridge port; default 8766 |
| `PROMETHEUS_XIAOZHI_TOKEN` | Device bearer credential chosen by the operator |
| `PROMETHEUS_XIAOZHI_PUBLIC_HOST` | Hostname/address the device uses to reach the bridge |
| `PROMETHEUS_OTA_HOST` | Optional bootstrap bind address |
| `PROMETHEUS_OTA_PORT` | Bootstrap port; default 8001 |
| `PROMETHEUS_X6_READ_ENABLED` | Enables optional X6 operations; see distinction below |

## Optional X6 integration

The current web server reads `PROMETHEUS_X6_READ_ENABLED=1` from the **process environment**. The optional device bridge reads it from **`.env`**. Set both when using both entry points:

```sh
PROMETHEUS_X6_READ_ENABLED=1 .venv/bin/python -m prometheus_voice.server
```

Keep the compatible X6 service on the same machine, at `ws://127.0.0.1:8765`. The destination is fixed deliberately. This release does not discover arbitrary hosts or remotely run commands.

## Optional Zhengchen bridge

After configuring a compatible device, a nonempty device token and an appropriate LAN bind address:

```sh
.venv/bin/python -m prometheus_voice.xiaozhi_server
```

For the optional bootstrap service:

```sh
.venv/bin/python -m prometheus_voice.xiaozhi_ota
```

Read the LAN restrictions in `SECURITY.md` first. Firmware and core installation are external to this repository. Device transcript and action-event forwarding currently expect the web application at loopback port 8780; keep that port when using the bridge.
