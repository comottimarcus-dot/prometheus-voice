"""Deterministic policy evaluation. A decision is not an execution permit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .intent import IntentEnvelope, IntentValidationError


class DecisionKind(StrEnum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class PolicyDecision:
    decision: DecisionKind
    reason_code: str
    explanation: str
    risk: str
    policy_version: str = "1"


def evaluate_payload(payload: object, *, now: datetime) -> PolicyDecision:
    try:
        intent = IntentEnvelope.from_payload(payload)
    except IntentValidationError:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "INVALID_INTENT", "The request contract is invalid.", "unknown")
    return evaluate(intent, now=now)


def evaluate(intent: IntentEnvelope, *, now: datetime) -> PolicyDecision:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "INVALID_CLOCK", "A timezone-aware policy clock is required.", "unknown")
    elapsed_ms = (now - intent.created_at).total_seconds() * 1000
    if elapsed_ms < 0 or elapsed_ms >= intent.timeout_ms:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "REQUEST_OUTSIDE_WINDOW", "The request is expired or future-dated.", "unknown")
    if intent.operation in {"external.send", "system.delete", "system.execute"}:
        return PolicyDecision(DecisionKind.DENY, "PROHIBITED_OPERATION", "External and destructive actions are disabled.", "high")
    schemas = {
        "capabilities.list": set(),
        "math.calculate": {"operator", "a", "b"},
        "demo.simulate": {"scenario"},
    }
    if intent.operation not in schemas:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "UNKNOWN_OPERATION", "No policy exists for this operation.", "unknown")
    parameters = intent.parameters
    valid = set(parameters) == schemas[intent.operation]
    if valid and intent.operation == "math.calculate":
        valid = (parameters["operator"] in ("add", "subtract", "multiply")
                 and type(parameters["a"]) in (int, float)
                 and type(parameters["b"]) in (int, float))
    if valid and intent.operation == "demo.simulate":
        valid = parameters["scenario"] == "executor_fallback"
    if not valid:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "INVALID_PARAMETERS", "Parameters do not match the operation contract.", "unknown")
    if not intent.local_only:
        return PolicyDecision(DecisionKind.DENY, "LOCAL_ONLY_REQUIRED", "This policy permits only local processing.", "high")
    if intent.confidence is None or intent.confidence < 0.8:
        return PolicyDecision(DecisionKind.FAIL_CLOSED, "INTENT_UNCERTAIN", "Clarify the intent before requesting an action.", "unknown")
    if intent.operation == "demo.simulate":
        return PolicyDecision(DecisionKind.CONFIRM, "SIMULATION_REQUIRES_CONFIRMATION", "Confirm the explicitly simulated fallback demonstration.", "medium")
    return PolicyDecision(DecisionKind.ALLOW, "SAFE_LOCAL_OPERATION", "The bounded local operation is permitted by policy.", "low")
