import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

from prometheus_voice.capabilities import CapabilityRegistry, demo_registry
from prometheus_voice.intent import IntentEnvelope
from prometheus_voice.planner import PlanStatus, PlanningError, build_plan, plan_summary

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def request(**changes):
    args = dict(request_id="11111111-1111-4111-8111-111111111111",
                trace_id="22222222-2222-4222-8222-222222222222", created_at=NOW,
                operation="math.calculate", parameters={"operator": "add", "a": 2, "b": 3}, confidence=0.9)
    args.update(changes)
    return IntentEnvelope(**args)


def plan(intent=None, **options):
    return build_plan(intent or request(), demo_registry(now=NOW), now=NOW,
                      allow_simulated=True, **options)


class PlannerTests(unittest.TestCase):
    def test_proposal_contains_inspectable_step_without_execution(self):
        result = plan()
        self.assertEqual(result.status, PlanStatus.PROPOSED)
        step = result.steps[0]
        self.assertEqual(step.executor_id, "sim-edge")
        self.assertEqual(step.dependencies, ())
        self.assertEqual(step.fallback_candidates, ("sim-nvidia", "sim-amd"))
        self.assertEqual(step.fallback_rule, "REPLAN_AND_REAUTHORIZE_BEFORE_RETRY")
        self.assertIn("RESULT_MARKED_SIMULATED", step.success_criteria)
        self.assertFalse(plan_summary(result)["execution_started"])

    def test_confirmation_is_pending_not_granted(self):
        result = plan(request(operation="demo.simulate", parameters={"scenario": "executor_fallback"}))
        self.assertEqual(result.status, PlanStatus.AWAITING_CONFIRMATION)
        self.assertEqual(result.selection.policy.decision.value, "CONFIRM")

    def test_denied_unknown_and_uncertain_requests_have_no_steps(self):
        for intent in (request(operation="system.delete", parameters={}),
                       request(operation="invented.action", parameters={}), request(confidence=None)):
            result = plan(intent)
            self.assertEqual(result.status, PlanStatus.BLOCKED)
            self.assertEqual(result.steps, ())

    def test_no_candidate_produces_blocked_plan(self):
        result = build_plan(request(), CapabilityRegistry(()), now=NOW)
        self.assertEqual(result.status, PlanStatus.BLOCKED)
        self.assertEqual(result.steps, ())

    def test_simulations_are_disabled_by_default(self):
        result = build_plan(request(), demo_registry(now=NOW), now=NOW)
        self.assertEqual(result.status, PlanStatus.BLOCKED)

    def test_budget_uses_remaining_time(self):
        result = build_plan(request(), demo_registry(now=NOW), now=NOW + timedelta(seconds=3), allow_simulated=True)
        self.assertEqual(result.steps[0].timeout_ms, 7000)
        self.assertEqual(result.expires_at, NOW + timedelta(seconds=10))

    def test_plan_cannot_outlive_health_observation(self):
        registry = demo_registry(now=NOW - timedelta(seconds=29))
        result = build_plan(request(), registry, now=NOW, allow_simulated=True)
        self.assertEqual(result.steps[0].timeout_ms, 1000)

    def test_expired_request_has_no_steps(self):
        result = build_plan(request(), demo_registry(now=NOW), now=NOW + timedelta(seconds=10), allow_simulated=True)
        self.assertEqual(result.status, PlanStatus.BLOCKED)
        self.assertEqual(result.steps, ())

    def test_fingerprint_is_deterministic_and_binds_parameters(self):
        self.assertEqual(plan().fingerprint, plan().fingerprint)
        modified = request(parameters={"operator": "add", "a": 2, "b": 4})
        self.assertNotEqual(plan().fingerprint, plan(modified).fingerprint)

    def test_fingerprint_changes_when_executor_changes(self):
        registry = demo_registry(now=NOW)
        changed = CapabilityRegistry(tuple(replace(entry, estimated_latency_ms=100) if entry.executor_id == "sim-edge" else entry for entry in registry.entries))
        result = build_plan(request(), changed, now=NOW, allow_simulated=True)
        self.assertNotEqual(result.fingerprint, plan().fingerprint)

    def test_summary_and_repr_do_not_include_raw_parameters(self):
        result = plan(request(parameters={"note": "SYNTHETIC-PRIVATE-MARKER"}))
        self.assertNotIn("SYNTHETIC-PRIVATE-MARKER", repr(result))
        self.assertNotIn("SYNTHETIC-PRIVATE-MARKER", json.dumps(plan_summary(result)))

    def test_plan_is_immutable(self):
        result = plan()
        with self.assertRaises(FrozenInstanceError):
            result.status = PlanStatus.PROPOSED
        with self.assertRaises(TypeError):
            result.intent.parameters["a"] = 100

    def test_invalid_clock_and_overflow_have_domain_errors(self):
        with self.assertRaises(PlanningError):
            build_plan(request(), demo_registry(now=NOW), now=NOW.replace(tzinfo=None))
        with self.assertRaises(PlanningError):
            plan(request(created_at=datetime.max.replace(tzinfo=timezone.utc)))
