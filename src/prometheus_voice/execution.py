"""Bounded in-process execution. No shell, network, file writes, or GPU access."""
from __future__ import annotations

import math
import operator
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Protocol

from .capabilities import Availability, Capability, CapabilityRegistry, ExecutionMode, Health, select_executor
from .intent import IntentEnvelope
from .planner import GovernedPlan, PlanStatus, PlanningError, build_plan
from .policy import DecisionKind


class ExecutionError(RuntimeError):
    """Sanitized adapter-domain error."""


class ExecutionStatus(StrEnum):
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class CalculationAdapter(Protocol):
    """Trusted, bounded arithmetic only; not a generic external worker contract."""
    executor_id: str

    def calculate(self, intent: IntentEnvelope) -> int | float: ...


class LocalCalculator:
    executor_id = "local-calculator"

    def calculate(self, intent: IntentEnvelope) -> int | float:
        parameters = intent.parameters
        operations = {"add": operator.add, "subtract": operator.sub, "multiply": operator.mul}
        if intent.operation != "math.calculate" or set(parameters) != {"operator", "a", "b"}:
            raise ExecutionError("unsupported calculation")
        op = parameters["operator"]
        if not isinstance(op, str) or op not in operations:
            raise ExecutionError("unsupported calculation")
        a, b = parameters["a"], parameters["b"]
        if any(type(value) not in (int, float) or abs(value) > 10**12 or not math.isfinite(value) for value in (a, b)):
            raise ExecutionError("invalid calculation operands")
        return operations[op](a, b)


def local_registry(*, now: datetime) -> CapabilityRegistry:
    """Availability of the bundled pure-Python adapter, not hardware discovery."""
    return CapabilityRegistry((Capability(
        "local-calculator", ("math.calculate",), "cpu", ExecutionMode.REAL,
        Availability.AVAILABLE, Health.HEALTHY, now, True, True, 1, 0,
    ),))


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    trace_id: str
    plan_fingerprint: str
    status: ExecutionStatus
    reason_code: str
    executor_id: str | None
    mode: ExecutionMode | None
    started_at: datetime
    finished_at: datetime
    elapsed_ms: float
    value: int | float | None = field(default=None, repr=False)


class ExecutionService:
    """One shared service per process; replay guard is bounded and not persistent."""

    def __init__(self, registry: CapabilityRegistry, *, adapter: CalculationAdapter | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic, capacity: int = 1024,
                 registry_provider: Callable[[datetime], CapabilityRegistry] | None = None) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ExecutionError("invalid request guard capacity")
        self._registry = registry
        self._adapter = adapter if adapter is not None else LocalCalculator()
        self._clock = clock
        self._monotonic = monotonic
        self._capacity = capacity
        self._registry_provider = registry_provider
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def execute(self, plan: GovernedPlan, *, cancel: threading.Event | None = None) -> ExecutionResult:
        started = self._clock()
        if not isinstance(started, datetime) or started.utcoffset() is None:
            raise ExecutionError("execution clock requires a timezone")

        def blocked(reason: str) -> ExecutionResult:
            return ExecutionResult(plan.request_id, plan.trace_id, plan.fingerprint,
                                   ExecutionStatus.BLOCKED, reason, None, None, started, started, 0.0)

        if cancel is not None and cancel.is_set():
            return blocked("CANCELLED_BEFORE_EXECUTION")
        if plan.status != PlanStatus.PROPOSED:
            return blocked("PLAN_NOT_AUTHORIZED")
        if started < plan.created_at or started >= plan.expires_at:
            return blocked("PLAN_OUTSIDE_WINDOW")
        try:
            planning_registry = self._registry_provider(plan.created_at) if self._registry_provider else self._registry
            expected = build_plan(plan.intent, planning_registry, now=plan.created_at)
        except PlanningError:
            return blocked("PLAN_REVALIDATION_FAILED")
        if expected != plan:
            return blocked("PLAN_MISMATCH")
        current_registry = self._registry_provider(started) if self._registry_provider else self._registry
        current = select_executor(plan.intent, current_registry, now=started)
        if current.policy.decision != DecisionKind.ALLOW or current.status != "PROPOSED":
            return blocked("POLICY_OR_CAPABILITY_BLOCKED")
        if (len(plan.steps) != 1 or plan.intent.operation != "math.calculate"
                or current.proposed_executor_id != self._adapter.executor_id
                or plan.steps[0].executor_id != self._adapter.executor_id
                or plan.steps[0].mode != ExecutionMode.REAL):
            return blocked("ADAPTER_MISMATCH")

        # Claim atomically before computation. Never evict claims to make space.
        with self._lock:
            if plan.request_id in self._seen:
                return blocked("DUPLICATE_REQUEST")
            if len(self._seen) >= self._capacity:
                return blocked("REQUEST_GUARD_FULL")
            self._seen.add(plan.request_id)

        tick = self._monotonic()
        reason = "CALCULATION_COMPLETED"
        value: int | float | None = None
        try:
            value = self._adapter.calculate(plan.intent)
            if type(value) not in (int, float) or abs(value) > 10**24 or not math.isfinite(value):
                reason, value = "INVALID_ADAPTER_RESULT", None
        except Exception:
            # Trust boundary: adapter exception text must not enter results or logs.
            reason, value = "ADAPTER_FAILED", None
        elapsed_ms = (self._monotonic() - tick) * 1000
        finished = self._clock()
        if not isinstance(finished, datetime) or finished.utcoffset() is None:
            finished = started
            reason, value = "INVALID_CLOCK", None
        if not math.isfinite(elapsed_ms) or elapsed_ms < 0 or finished < started:
            reason, value, elapsed_ms = "INVALID_CLOCK", None, 0.0
        if cancel is not None and cancel.is_set():
            reason, value = "CANCELLED", None
        elif finished >= plan.expires_at or elapsed_ms >= (plan.expires_at - started).total_seconds() * 1000:
            reason, value = "EXECUTION_TIMEOUT", None
        return ExecutionResult(
            plan.request_id, plan.trace_id, plan.fingerprint,
            ExecutionStatus.EXECUTED if reason == "CALCULATION_COMPLETED" else ExecutionStatus.FAILED,
            reason, self._adapter.executor_id, ExecutionMode.REAL, started, finished, elapsed_ms, value,
        )
