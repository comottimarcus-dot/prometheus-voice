"""Build immutable proposals for future execution adapters. Never dispatch work."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .capabilities import CapabilityRegistry, ExecutionMode, Selection, select_executor
from .intent import IntentEnvelope


class PlanStatus(StrEnum):
    PROPOSED = "PROPOSED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    BLOCKED = "BLOCKED"


class PlanningError(ValueError):
    """Invalid planning context, with no caller content in the error message."""


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    operation: str
    dependencies: tuple[str, ...]
    executor_id: str
    mode: ExecutionMode
    timeout_ms: int
    fallback_candidates: tuple[str, ...]
    fallback_rule: str
    success_criteria: tuple[str, ...]
    expected_evidence: tuple[str, ...]


@dataclass(frozen=True)
class GovernedPlan:
    fingerprint: str
    request_id: str
    trace_id: str
    created_at: datetime
    expires_at: datetime
    status: PlanStatus
    objective: str
    selection: Selection
    steps: tuple[PlanStep, ...]
    intent: IntentEnvelope = field(repr=False)
    version: int = 1


_OBJECTIVES = {
    "math.calculate": ("Calculate a bounded arithmetic result.", ("FINITE_NUMERIC_RESULT", "MATCHES_REQUESTED_OPERATOR")),
    "capabilities.list": ("Inspect declared capabilities without contacting private infrastructure.", ("PUBLIC_CAPABILITY_METADATA_ONLY",)),
    "demo.simulate": ("Demonstrate executor fallback with explicitly simulated capabilities.", ("RESULT_MARKED_SIMULATED", "FALLBACK_TRANSITIONS_RECORDED")),
}


def build_plan(
    intent: IntentEnvelope,
    registry: CapabilityRegistry,
    *,
    now: datetime,
    allow_simulated: bool = False,
    available_requirements: frozenset[str] = frozenset(),
) -> GovernedPlan:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise PlanningError("planning clock requires a timezone")
    try:
        expires_at = intent.created_at + timedelta(milliseconds=intent.timeout_ms)
    except OverflowError:
        raise PlanningError("request deadline is outside the supported range") from None
    selection = select_executor(intent, registry, now=now, allow_simulated=allow_simulated,
                                available_requirements=available_requirements)
    steps: tuple[PlanStep, ...] = ()
    status = PlanStatus.BLOCKED
    objective = "No execution proposed."
    if selection.proposed_executor_id is not None:
        executor = next(entry for entry in registry.entries if entry.executor_id == selection.proposed_executor_id)
        # A plan cannot outlive the health observation used to select its primary.
        try:
            expires_at = min(expires_at, executor.checked_at + timedelta(seconds=30))
        except OverflowError:
            raise PlanningError("health deadline is outside the supported range") from None
        budget_ms = int((expires_at - now).total_seconds() * 1000)
        if budget_ms <= executor.estimated_latency_ms:
            raise PlanningError("insufficient remaining health or request budget")
        objective, criteria = _OBJECTIVES[intent.operation]
        if executor.mode == ExecutionMode.SIMULATED:
            objective = "SIMULATED: " + objective
            criteria += ("RESULT_MARKED_SIMULATED",) if "RESULT_MARKED_SIMULATED" not in criteria else ()
        status = (PlanStatus.AWAITING_CONFIRMATION if selection.status == "REQUIRES_CONFIRMATION"
                  else PlanStatus.PROPOSED)
        steps = (PlanStep(
            "step-1", intent.operation, (), executor.executor_id, executor.mode, budget_ms,
            selection.alternatives, "REPLAN_AND_REAUTHORIZE_BEFORE_RETRY",
            criteria, ("POLICY_DECISION", "EXECUTOR_MODE", "START_END_TIMESTAMPS", "RESULT_STATUS"),
        ),)

    # Change detection only: not a signature, approval, secret, or replay defense.
    canonical = {
        "version": 1, "request_id": intent.request_id, "trace_id": intent.trace_id,
        "intent_created_at": intent.created_at.isoformat(), "operation": intent.operation,
        "parameters": dict(intent.parameters), "confidence": intent.confidence,
        "local_only": intent.local_only, "timeout_ms": intent.timeout_ms,
        "created_at": now.isoformat(), "expires_at": expires_at.isoformat(),
        "status": status, "selection": asdict(selection), "steps": [asdict(step) for step in steps],
    }
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                             allow_nan=False).encode("utf-8")).hexdigest()
    return GovernedPlan(fingerprint, intent.request_id, intent.trace_id, now, expires_at,
                        status, objective, selection, steps, intent)


def plan_summary(plan: GovernedPlan) -> dict[str, object]:
    """Public inspection view; raw intent parameters are excluded by default."""
    return {
        "version": plan.version, "fingerprint": plan.fingerprint,
        "request_id": plan.request_id, "trace_id": plan.trace_id,
        "created_at": plan.created_at.isoformat(), "expires_at": plan.expires_at.isoformat(),
        "status": plan.status.value, "objective": plan.objective,
        "selection": asdict(plan.selection), "steps": [asdict(step) for step in plan.steps],
        "execution_started": False,
    }
