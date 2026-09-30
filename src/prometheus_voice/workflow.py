"""Server-owned, bounded plan workflow for the local demonstration interface."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from .capabilities import demo_registry
from .evidence import EvidenceError, EvidenceLedger
from .execution import ExecutionService, local_registry
from .intent import IntentEnvelope, IntentValidationError
from .planner import GovernedPlan, PlanStatus, build_plan, plan_summary


class WorkflowError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class _Pending:
    plan: GovernedPlan
    outcome: dict[str, object] | None = None


class GovernedWorkflow:
    def __init__(self, ledger: EvidenceLedger, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 capacity: int = 128) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 1024:
            raise WorkflowError("INVALID_CAPACITY")
        self._clock = clock
        self._ledger = ledger
        self._capacity = capacity
        self._plans: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        # The built-in adapter is pure Python. Its deterministic descriptor can
        # be reconstructed at planning time and refreshed at execution time.
        self._executor = ExecutionService(local_registry(now=clock()), clock=clock,
                                          registry_provider=lambda stamp: local_registry(now=stamp))

    def prepare(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != {"operation", "parameters"}:
            raise WorkflowError("INVALID_REQUEST")
        now = self._clock()
        try:
            intent = IntentEnvelope(str(uuid4()), str(uuid4()), now, payload["operation"],
                                    payload["parameters"], timeout_ms=30000, confidence=1)
        except IntentValidationError:
            raise WorkflowError("INVALID_INTENT") from None
        # Confidence=1 reflects explicit structured form input, never ASR confidence.
        simulated = intent.operation == "demo.simulate"
        registry = demo_registry(now=now) if simulated else local_registry(now=now)
        plan = build_plan(intent, registry, now=now, allow_simulated=simulated)
        with self._lock:
            self._plans = {key: value for key, value in self._plans.items() if value.plan.expires_at > now}
            if len(self._plans) >= self._capacity:
                raise WorkflowError("PLAN_CAPACITY_REACHED", 503)
            self._plans[plan.request_id] = _Pending(plan)
        return {"plan_id": plan.request_id, "plan": plan_summary(plan),
                "can_execute": plan.status == PlanStatus.PROPOSED and intent.operation == "math.calculate"}

    def execute(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) != {"plan_id"} or not isinstance(payload["plan_id"], str):
            raise WorkflowError("INVALID_REQUEST")
        with self._lock:
            pending = self._plans.get(payload["plan_id"])
            if pending is None:
                raise WorkflowError("PLAN_NOT_FOUND", 404)
            if pending.outcome is not None:
                return {**pending.outcome, "replayed": True}
            plan = pending.plan
            if self._clock() >= plan.expires_at:
                raise WorkflowError("PLAN_EXPIRED", 409)
            if plan.status != PlanStatus.PROPOSED or plan.intent.operation != "math.calculate":
                raise WorkflowError("PLAN_NOT_EXECUTABLE", 409)
            result = self._executor.execute(plan)
            outcome = {
                "status": result.status.value, "reason_code": result.reason_code,
                "value": result.value, "executor": result.executor_id,
                "mode": result.mode.value if result.mode else None,
                "elapsed_ms": result.elapsed_ms, "trace_id": result.trace_id,
                "plan_fingerprint": result.plan_fingerprint, "replayed": False,
                "evidence": {"status": "FAILED", "reason_code": "EVIDENCE_UNAVAILABLE"},
            }
            # Cache BEFORE persistence so a storage failure cannot rerun the action.
            pending.outcome = outcome
            try:
                receipt = self._ledger.append_execution(plan, result)
                self._ledger.verify(expected_head=receipt.head_hash)
                outcome["evidence"] = {"status": "VERIFIED", "sequence": receipt.sequence, "head_hash": receipt.head_hash}
            except EvidenceError:
                pass  # The separate evidence failure is already explicit in the result.
            return dict(outcome)
