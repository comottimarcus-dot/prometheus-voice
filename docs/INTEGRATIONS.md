# Integration boundaries

The application supplies the Voice side of these contracts. It does not bundle the X6 core or device firmware. Missing or invalid responses produce an unavailable result rather than a fabricated answer.

## AssemblyAI

The backend mints browser credentials through `https://agents.assemblyai.com/v1/token`. Browser voice and the optional bridge connect to `wss://agents.assemblyai.com/v1/ws`. The bridge converts device Opus audio to the PCM stream expected by the voice session and converts replies for device playback.

## X6 WebSocket

All routes use the fixed loopback X6 endpoint on port 8765. Requests carry a type and request ID. Replies must match that request ID and the schema enforced in `src/prometheus_voice/x6_client.py`.

| Path | Request type | Role |
| --- | --- | --- |
| `/capabilities` | `x6_capabilities` | Registered capabilities, never implied health |
| `/information` | `x6_information` | Up to three attributed ShadowBroker headlines |
| `/sentinel` | `x6_sentinel` | 25-cell weather telemetry with source-age checks |
| `/sentinel-air` | `x6_sentinel_air` | Filtered aircraft display count with fetch-age checks |
| `/camera-capture` | `x6_camera_capture` | One explicitly confirmed photo and detector result |
| `/camera-preview` | `{ "action": "read" }` or `{ "action": "clear" }` | Short-lived JPEG preview |

The validators and synthetic test fixtures are the executable contract. AIR accepts a 25-nautical-mile display range and a maximum of 40 displayed targets, reporting when the cap is reached. Fetch age does not establish the age of an individual aircraft observation. Weather `waiting` means a second distinct sample is needed to assess movement.

## Camera and device conversation

The Zhengchen device connects to the dedicated Voice bridge. When its hello announces MCP and camera support, the bridge opens a separate X6 connection and forwards only JSON MCP envelopes on that route. Device conversation audio stays on the AssemblyAI path.

For the spoken camera route, `CameraConsent` requires an explicit photo request, the permission question and the fresh phrase “Yes, take the photo” within its confirmation window. Consuming consent resets the state. Tool arguments alone cannot grant consent. A failed capture does not authorize an automatic retry.

The detector returns object labels and counts. The application labels these as predictions, not verified identification. It does not use face recognition in this contract.

## Local execution

The arithmetic executor is local to Voice. The intent schema, policy, capability selection, plan validation, replay protection and evidence ledger are implemented in this repository. They do not authorize arbitrary X6 commands.

## Reproducibility

Run the offline smoke test and unit suites without live services. To reproduce the hardware demonstration, provide compatible services for the routes above and the external firmware/detector stack. This repository alone cannot reproduce the physical deployment.
