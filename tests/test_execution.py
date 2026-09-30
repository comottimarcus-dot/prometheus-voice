import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from prometheus_voice.capabilities import demo_registry
from prometheus_voice.execution import ExecutionService, ExecutionStatus, LocalCalculator, local_registry
from prometheus_voice.intent import IntentEnvelope
from prometheus_voice.planner import build_plan

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def intent(**changes):
    fields = dict(request_id="11111111-1111-4111-8111-111111111111",
                  trace_id="22222222-2222-4222-8222-222222222222", created_at=NOW,
                  operation="math.calculate", parameters={"operator": "add", "a": 19, "b": 23}, confidence=1)
    fields.update(changes)
    return IntentEnvelope(**fields)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.registry = local_registry(now=NOW)
        self.plan = build_plan(intent(), self.registry, now=NOW)

    def service(self, **options):
        return ExecutionService(self.registry, clock=options.pop("clock", lambda: NOW), **options)

    def test_real_local_calculation_and_correlated_result(self):
        result = self.service().execute(self.plan)
        self.assertEqual(result.status, ExecutionStatus.EXECUTED)
        self.assertEqual(result.value, 42)
        self.assertEqual(result.executor_id, "local-calculator")
        self.assertEqual(result.plan_fingerprint, self.plan.fingerprint)
        self.assertEqual(result.trace_id, self.plan.trace_id)

    def test_all_supported_operators(self):
        for op, expected in (("add", 5), ("subtract", -1), ("multiply", 6)):
            plan = build_plan(intent(parameters={"operator": op, "a": 2, "b": 3}), self.registry, now=NOW)
            self.assertEqual(self.service().execute(plan).value, expected)

    def test_duplicate_is_not_reexecuted(self):
        adapter = Mock(wraps=LocalCalculator(), executor_id="local-calculator")
        service = self.service(adapter=adapter)
        self.assertEqual(service.execute(self.plan).status, ExecutionStatus.EXECUTED)
        self.assertEqual(service.execute(self.plan).reason_code, "DUPLICATE_REQUEST")
        adapter.calculate.assert_called_once()

    def test_concurrent_duplicate_has_one_execution(self):
        service = self.service()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(service.execute, [self.plan] * 8))
        self.assertEqual(sum(result.status == ExecutionStatus.EXECUTED for result in results), 1)
        self.assertEqual(sum(result.reason_code == "DUPLICATE_REQUEST" for result in results), 7)

    def test_changed_parameters_with_same_request_id_are_still_replay(self):
        service = self.service()
        service.execute(self.plan)
        revised = build_plan(intent(parameters={"operator": "add", "a": 1, "b": 1}), self.registry, now=NOW)
        self.assertEqual(service.execute(revised).reason_code, "DUPLICATE_REQUEST")

    def test_modified_plan_is_rejected(self):
        for altered in (replace(self.plan, fingerprint="forged"),
                        replace(self.plan, objective="forged"),
                        replace(self.plan, steps=(replace(self.plan.steps[0], timeout_ms=30000),))):
            self.assertEqual(self.service().execute(altered).reason_code, "PLAN_MISMATCH")

    def test_expired_plan_never_calls_adapter(self):
        adapter = Mock(executor_id="local-calculator")
        result = self.service(adapter=adapter, clock=lambda: NOW + timedelta(seconds=10)).execute(self.plan)
        self.assertEqual(result.reason_code, "PLAN_OUTSIDE_WINDOW")
        adapter.calculate.assert_not_called()

    def test_simulated_and_confirmation_plans_cannot_execute(self):
        for request in (intent(), intent(operation="demo.simulate", parameters={"scenario": "executor_fallback"})):
            plan = build_plan(request, demo_registry(now=NOW), now=NOW, allow_simulated=True)
            self.assertEqual(self.service().execute(plan).status, ExecutionStatus.BLOCKED)

    def test_denied_plan_cannot_execute(self):
        plan = build_plan(intent(operation="system.execute", parameters={}), self.registry, now=NOW)
        self.assertEqual(self.service().execute(plan).reason_code, "PLAN_NOT_AUTHORIZED")

    def test_capacity_is_fail_closed_without_eviction(self):
        service = self.service(capacity=1)
        service.execute(self.plan)
        second = build_plan(intent(request_id="33333333-3333-4333-8333-333333333333"), self.registry, now=NOW)
        self.assertEqual(service.execute(second).reason_code, "REQUEST_GUARD_FULL")
        self.assertEqual(service.execute(self.plan).reason_code, "DUPLICATE_REQUEST")

    def test_cancellation_before_and_during_execution(self):
        cancel = threading.Event(); cancel.set()
        adapter = Mock(executor_id="local-calculator")
        self.assertEqual(self.service(adapter=adapter).execute(self.plan, cancel=cancel).reason_code, "CANCELLED_BEFORE_EXECUTION")
        adapter.calculate.assert_not_called()
        cancel.clear()
        adapter.calculate.side_effect = lambda _: (cancel.set(), 42)[1]
        result = self.service(adapter=adapter).execute(self.plan, cancel=cancel)
        self.assertEqual(result.reason_code, "CANCELLED")
        self.assertIsNone(result.value)

    def test_late_result_is_rejected(self):
        ticks = iter((0.0, 11.0))
        result = self.service(monotonic=lambda: next(ticks)).execute(self.plan)
        self.assertEqual(result.reason_code, "EXECUTION_TIMEOUT")
        self.assertIsNone(result.value)

    def test_adapter_failure_is_sanitized_and_request_stays_claimed(self):
        adapter = Mock(executor_id="local-calculator")
        adapter.calculate.side_effect = RuntimeError("SYNTHETIC-PRIVATE-CONTENT")
        service = self.service(adapter=adapter)
        result = service.execute(self.plan)
        self.assertEqual(result.reason_code, "ADAPTER_FAILED")
        self.assertNotIn("SYNTHETIC-PRIVATE-CONTENT", repr(result))
        self.assertEqual(service.execute(self.plan).reason_code, "DUPLICATE_REQUEST")

    def test_invalid_adapter_outputs_are_rejected(self):
        for value in (True, None, "42", float("nan"), float("inf"), 10**25):
            adapter = Mock(executor_id="local-calculator")
            adapter.calculate.return_value = value
            result = self.service(adapter=adapter).execute(self.plan)
            self.assertEqual(result.reason_code, "INVALID_ADAPTER_RESULT")
            self.assertIsNone(result.value)
