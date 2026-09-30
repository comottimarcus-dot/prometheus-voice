# PROMETHEUS VOICE

**Your voice. Action you can verify.**

## Concept

PROMETHEUS VOICE connects spoken requests to bounded tools, physical devices, and visible results. It addresses a practical gap in voice assistants: a fluent answer alone does not show whether a tool was used, whether the user authorized an action, or where a result came from.

Built with AssemblyAI, the prototype supports English voice interaction through a browser and a Zhengchen ESP32-S3 device. It connects to PROMETHEUS X6 through its WebSocket interface, while keeping explicit boundaries between conversation, information retrieval, and actions requiring confirmation.

## Demonstrated workflows

- **Consent before camera capture:** the user requests a photo, the assistant asks permission, and an explicit spoken confirmation authorizes a single capture. Object detection returns to the same conversation, phrased as a prediction.
- **Connected observations:** Sentinel provides a filtered ADS-B aircraft display count and weather telemetry. Reports describe the scope of the available data; missing or outdated data should not be presented as current observations.
- **Human-reviewed local calculation:** the interface presents a plan and policy decision before execution, then displays the calculation result and its verification evidence.
- **Source-based briefing:** ShadowBroker provides a short news briefing with source attribution.
- **Capability registry:** Voice can read X6 registrations while distinguishing registration from verified availability.

## Intended users and value

The initial audience is builders and operators of small connected systems who need a spoken interface without losing visibility or control. A single conversational entry point can make device information easier to access, while explicit confirmation and visible results help users understand what actually happened.

## What makes the prototype distinct

The demonstration combines real physical hardware, spoken consent, connected telemetry, and an inspectable local action workflow. Its focus is accountable interaction with tools rather than unrestricted general conversation.

## Current scope

This is a local prototype, not a publicly hosted production service. General distributed execution from Voice is not demonstrated. Camera predictions can be incorrect, and each tool has its own evidence and freshness limits. Existing X6, Sentinel, and device components are integrated into the Voice experience; the submission should clearly distinguish pre-existing components from work completed for the hackathon.

## Next steps

Improve repeatable setup and integration tests, expand explicit health reporting, and evaluate additional bounded actions while preserving user confirmation where required.
