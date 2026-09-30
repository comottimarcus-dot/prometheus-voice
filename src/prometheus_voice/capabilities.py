"""Public capability discovery and explainable selection; never executes work."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .intent import IntentEnvelope
from .policy import DecisionKind, PolicyDecision, evaluate


class RegistryError(ValueError):
    """Invalid registry metadata; messages exclude supplied values."""


class ExecutionMode(StrEnum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class Health(StrEnum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Capability:
    executor_id: str
    operations: tuple[str, ...]
    hardware: str
    mode: ExecutionMode
    availability: Availability
    health: Health
    checked_at: datetime
    local: bool
    trusted: bool
    estimated_latency_ms: int
    cost_units: int
    requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        def identifier(value: object) -> bool:
            return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is not None

        if not identifier(self.executor_id) or not identifier(self.hardware):
            raise RegistryError("invalid executor metadata")
        for values in (self.operations, self.requirements):
            if type(values) is not tuple or len(values) > 16 or not all(identifier(v) for v in values):
                raise RegistryError("invalid capability identifiers")
            if len(set(values)) != len(values):
                raise RegistryError("duplicate capability identifier")
        if not self.operations:
            raise RegistryError("executor must declare an operation")
        if not isinstance(self.mode, ExecutionMode) or not isinstance(self.availability, Availability) or not isinstance(self.health, Health):
            raise RegistryError("invalid capability state")
        if not isinstance(self.checked_at, datetime) or self.checked_at.utcoffset() is None:
            raise RegistryError("health timestamp requires a timezone")
        if type(self.local) is not bool or type(self.trusted) is not bool:
            raise RegistryError("invalid privacy or trust metadata")
        if type(self.estimated_latency_ms) is not int or not 1 <= self.estimated_latency_ms <= 30000:
            raise RegistryError("invalid latency estimate")
        if type(self.cost_units) is not int or not 0 <= self.cost_units <= 1000000:
            raise RegistryError("invalid relative cost")


@dataclass(frozen=True)
class CapabilityRegistry:
    entries: tuple[Capability, ...]

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or len(self.entries) > 64 or not all(isinstance(e, Capability) for e in self.entries):
            raise RegistryError("invalid registry entries")
        if len({entry.executor_id for entry in self.entries}) != len(self.entries):
            raise RegistryError("duplicate executor identifier")


@dataclass(frozen=True)
class CandidateAssessment:
    executor_id: str
    mode: ExecutionMode
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    policy: PolicyDecision
    status: str
    reason_code: str
    explanation: str
    proposed_executor_id: str | None
    alternatives: tuple[str, ...]
    assessments: tuple[CandidateAssessment, ...]


def select_executor(
    intent: IntentEnvelope,
    registry: CapabilityRegistry,
    *,
    now: datetime,
    allow_simulated: bool = False,
    available_requirements: frozenset[str] = frozenset(),
) -> Selection:
    """Reevaluate policy and propose an executor. No approval or dispatch occurs."""
    if type(allow_simulated) is not bool or type(available_requirements) is not frozenset:
        raise RegistryError("invalid selection options")
    if not all(isinstance(item, str) for item in available_requirements):
        raise RegistryError("invalid available requirements")
    policy = evaluate(intent, now=now)
    if policy.decision in (DecisionKind.DENY, DecisionKind.FAIL_CLOSED):
        return Selection(policy, "BLOCKED", policy.reason_code, policy.explanation, None, (), ())

    remaining_ms = intent.timeout_ms - (now - intent.created_at).total_seconds() * 1000
    assessments = []
    eligible = []
    for entry in sorted(registry.entries, key=lambda item: item.executor_id):
        reasons = []
        if intent.operation not in entry.operations:
            reasons.append("OPERATION_UNSUPPORTED")
        if entry.availability != Availability.AVAILABLE:
            reasons.append("EXECUTOR_UNAVAILABLE")
        if entry.health != Health.HEALTHY:
            reasons.append("HEALTH_NOT_CONFIRMED")
        health_age_ms = (now - entry.checked_at).total_seconds() * 1000
        if not 0 <= health_age_ms < 30000:
            reasons.append("HEALTH_OUTSIDE_WINDOW")
        if not entry.trusted:
            reasons.append("EXECUTOR_UNTRUSTED")
        if intent.local_only and not entry.local:
            reasons.append("PRIVACY_MISMATCH")
        if entry.mode == ExecutionMode.SIMULATED and not allow_simulated:
            reasons.append("SIMULATION_DISABLED")
        if entry.estimated_latency_ms >= remaining_ms:
            reasons.append("DEADLINE_BUDGET_EXCEEDED")
        if not set(entry.requirements) <= available_requirements:
            reasons.append("REQUIREMENTS_UNMET")
        assessments.append(CandidateAssessment(entry.executor_id, entry.mode, not reasons,
                                               tuple(reasons) if reasons else ("ELIGIBLE",)))
        if not reasons:
            eligible.append(entry)

    # Real before simulated; then latency, relative cost, and stable ID tie-break.
    eligible.sort(key=lambda entry: (entry.mode != ExecutionMode.REAL,
                                    entry.estimated_latency_ms, entry.cost_units, entry.executor_id))
    if not eligible:
        return Selection(policy, "NO_CANDIDATE", "NO_ELIGIBLE_EXECUTOR",
                         "No executor satisfies the policy and request constraints.",
                         None, (), tuple(assessments))
    confirmation = policy.decision == DecisionKind.CONFIRM
    return Selection(policy, "REQUIRES_CONFIRMATION" if confirmation else "PROPOSED",
                     "CANDIDATE_AWAITING_CONFIRMATION" if confirmation else "CANDIDATE_RANKED",
                     "Eligible candidates rank by real before simulated, then estimated latency, relative cost, and executor ID. Selection does not authorize execution.",
                     eligible[0].executor_id, tuple(entry.executor_id for entry in eligible[1:]), tuple(assessments))


def demo_registry(*, now: datetime) -> CapabilityRegistry:
    """Scenario metadata only: no probes, hardware discovery, or real workers."""
    entries = tuple(
        Capability(name, ("math.calculate", "capabilities.list", "demo.simulate"), hardware,
                   ExecutionMode.SIMULATED, Availability.AVAILABLE, Health.HEALTHY,
                   now, True, True, latency, cost)
        for name, hardware, latency, cost in (
            ("sim-edge", "edge-cpu", 5, 1),
            ("sim-nvidia", "nvidia-gpu", 20, 3),
            ("sim-amd", "amd-rocm", 25, 2),
        )
    )
    return CapabilityRegistry(entries)
