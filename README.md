# PROMETHEUS VOICE

**Your voice. Action you can verify.**

An English voice prototype built with AssemblyAI that connects spoken requests to bounded tools and physical devices. Users confirm camera captures, query connected observations, and inspect the outcome of a local calculation.

[Watch the recorded demo](media/prometheus-voice-demo.mp4) · [Presentation PDF](docs/PRESENTATION.pdf) · [Editable slides](docs/PRESENTATION.pptx) · [Project concept](docs/CONCEPT.md)

[Integration contract](docs/INTEGRATIONS.md) · [Configuration](docs/CONFIGURATION.md)

## What works

| Workflow | Behavior | Requirements |
| --- | --- | --- |
| Browser conversation | English speech, replies, interruption and session controls | AssemblyAI Voice Agent access |
| Local calculation | Review a plan, execute bounded arithmetic, inspect a hash-linked evidence receipt | This repository |
| X6 registry | Read capability names and provider counts, with availability marked unknown | Compatible X6 core |
| Sentinel AIR / WX | Report filtered aircraft targets and weather freshness | X6 and Sentinel telemetry |
| ShadowBroker briefing | Return up to three sourced headlines | X6 and ShadowBroker |
| Zhengchen camera | Request a photo, obtain spoken confirmation, return detector predictions | X6, compatible ESP32-S3 firmware and detector |

The demo shows real hardware and a real local calculation. This repository contains the Voice application, its bridge and tests. The pre-existing X6 core, device firmware, detector, Sentinel and ShadowBroker services are separate dependencies and are **not included**. General distributed execution from Voice remains planned.

## Quick start (Linux)

Python 3.12 or newer is required. The local evidence ledger uses Unix file locking. Install the `libopus0` system package if using the optional device bridge.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Set `ASSEMBLYAI_API_KEY` in `.env` to your own credential, then run:

```sh
.venv/bin/python -m prometheus_voice.server
```

Open **http://127.0.0.1:8780/**. The server deliberately accepts only IPv4 loopback. This is a local prototype, not a public internet deployment.

Browser voice sessions require access to the AssemblyAI Voice Agent service used by the code (`agents.assemblyai.com`). An ordinary speech API account may require additional product access. Sessions are metered. **Validate connection** requests a temporary credential without starting the microphone. **Start voice session** sends microphone audio to AssemblyAI.

X6 integration is disabled by default. Missing hardware does not prevent running the local calculation or offline tests.

## Try the core without credentials or hardware

```sh
PYTHONPATH=src .venv/bin/python -m prometheus_voice.smoke_execution
```

Expected output includes `RESULT=42`, `REPLAY=BLOCKED` and `SMOKE=GREEN`. No network request or photo capture occurs.

## Demonstration script

1. On a configured Zhengchen device, ask **“Can you take a picture?”**
2. Wait for its permission question, then say **“Yes, take the photo.”**
3. Ask **“How many aircraft is Sentinel displaying?”** and **“What is Sentinel reporting about the weather?”**
4. In **Governed action**, review `19 + 23`, execute the calculation and inspect `42` and the evidence status.

Camera predictions can be wrong. The spoken result deliberately says **“The detector suggests…”**. A registry entry is not a live health check. Aircraft counts describe the filtered display, not every aircraft in a region.

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -v
node --test tests/*.mjs
```

Node.js is needed only for the JavaScript tests. Tests use synthetic inputs and local test servers. CI runs the same suites without credentials or hardware.

## Privacy and evidence

Permanent AssemblyAI credentials stay in the backend. The browser receives temporary tokens. Provider data handling depends on your account settings.

The application does not persist conversation audio or transcripts. The device transcript buffer expires after three minutes without new text. The compatible X6 deployment keeps the latest authorized photo in memory for a short preview window; it is not included in this repository. The camera action timeline is a short-lived diagnostic view.

The local calculation ledger stores bounded execution metadata in `evidence/execution.jsonl`, with restrictive file permissions. Hash chaining checks record consistency; it does not independently prove physical events or make predictions correct. Camera predictions and telemetry have different assurance limits from the calculation ledger.

Do not commit `.env`, recordings, runtime evidence, personal photos or deployment backups. See [SECURITY.md](SECURITY.md) and [configuration](docs/CONFIGURATION.md).

## Hackathon scope

The Voice application, browser controls, bridge, tool handoffs and confirmation experience connect pre-existing infrastructure into this prototype. The presentation distinguishes the Voice work from the external X6 and device components. The demonstration video includes edited pauses and synchronized camera angles.

Created by **Marcus Comotti** for the AssemblyAI Voice Agent Hackathon. Project website: [jarvisprometheus.space](https://www.jarvisprometheus.space).

## License

MIT for the code in this repository. External services, firmware and libraries retain their respective licenses and terms. The included demo media and presentation are project materials by Marcus Comotti.
