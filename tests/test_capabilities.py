import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from prometheus_voice.capabilities import (
    Availability, CapabilityRegistry, ExecutionMode, Health, RegistryError,
    demo_registry, select_executor,
)
from prometheus_voice.intent import IntentEnvelope

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def intent(**changes):
    values = dict(request_id="11111111-1111-4111-8111-111111111111",
                  trace_id="22222222-2222-4222-8222-222222222222", created_at=NOW,
                  operation="math.calculate", parameters={"operator": "add", "a": 2, "b": 3},
                  confidence=0.95)
    values.update(changes)
    return IntentEnvelope(**values)


class CapabilityTests(unittest.TestCase):
    def test_demo_is_simulated_and_disabled_by_default(self):
        registry = demo_registry(now=NOW)
        self.assertTrue(all(entry.mode == ExecutionMode.SIMULATED for entry in registry.entries))
        result = select_executor(intent(), registry, now=NOW)
        self.assertIsNone(result.proposed_executor_id)
        self.assertTrue(all("SIMULATION_DISABLED" in row.reasons for row in result.assessments))

    def test_selection_is_explained_and_order_independent(self):
        registry = demo_registry(now=NOW)
        result = select_executor(intent(), registry, now=NOW, allow_simulated=True)
        self.assertEqual(result.proposed_executor_id, "sim-edge")
        self.assertEqual(result.alternatives, ("sim-nvidia", "sim-amd"))
        self.assertEqual(result.status, "PROPOSED")
        reverse = CapabilityRegistry(tuple(reversed(registry.entries)))
        self.assertEqual(result, select_executor(intent(), reverse, now=NOW, allow_simulated=True))

    def test_unavailable_candidate_is_excluded_and_alternative_proposed(self):
        registry = demo_registry(now=NOW)
        registry = CapabilityRegistry((replace(registry.entries[0], availability=Availability.UNAVAILABLE), *registry.entries[1:]))
        result = select_executor(intent(), registry, now=NOW, allow_simulated=True)
        self.assertEqual(result.proposed_executor_id, "sim-nvidia")
        edge = next(row for row in result.assessments if row.executor_id == "sim-edge")
        self.assertIn("EXECUTOR_UNAVAILABLE", edge.reasons)

    def test_policy_deny_and_uncertainty_cannot_be_overridden(self):
        for request in (intent(operation="system.execute", parameters={}), intent(confidence=None)):
            result = select_executor(request, demo_registry(now=NOW), now=NOW, allow_simulated=True)
            self.assertEqual(result.status, "BLOCKED")
            self.assertIsNone(result.proposed_executor_id)

    def test_confirmation_is_preserved_in_proposal(self):
        request = intent(operation="demo.simulate", parameters={"scenario": "executor_fallback"})
        result = select_executor(request, demo_registry(now=NOW), now=NOW, allow_simulated=True)
        self.assertEqual(result.status, "REQUIRES_CONFIRMATION")
        self.assertIsNotNone(result.proposed_executor_id)

    def test_hard_constraints_each_exclude_candidate(self):
        baseline = demo_registry(now=NOW).entries[0]
        variants = [({"local": False}, "PRIVACY_MISMATCH"),
                    ({"trusted": False}, "EXECUTOR_UNTRUSTED"),
                    ({"health": Health.UNKNOWN}, "HEALTH_NOT_CONFIRMED"),
                    ({"checked_at": NOW - timedelta(seconds=30)}, "HEALTH_OUTSIDE_WINDOW"),
                    ({"checked_at": NOW + timedelta(seconds=1)}, "HEALTH_OUTSIDE_WINDOW"),
                    ({"operations": ("another.operation",)}, "OPERATION_UNSUPPORTED"),
                    ({"requirements": ("special-runtime",)}, "REQUIREMENTS_UNMET"),
                    ({"estimated_latency_ms": 10000}, "DEADLINE_BUDGET_EXCEEDED")]
        for changes, reason in variants:
            with self.subTest(reason=reason):
                result = select_executor(intent(), CapabilityRegistry((replace(baseline, **changes),)), now=NOW, allow_simulated=True)
                self.assertIsNone(result.proposed_executor_id)
                self.assertIn(reason, result.assessments[0].reasons)

    def test_uses_remaining_budget_not_original_timeout(self):
        result = select_executor(intent(), demo_registry(now=NOW), now=NOW + timedelta(milliseconds=9998), allow_simulated=True)
        self.assertEqual(result.status, "NO_CANDIDATE")

    def test_empty_registry_fails_closed(self):
        self.assertEqual(select_executor(intent(), CapabilityRegistry(()), now=NOW).status, "NO_CANDIDATE")

    def test_real_metadata_precedes_faster_simulated_metadata(self):
        baseline = demo_registry(now=NOW).entries[0]
        # Synthetic test descriptor, not a claim of a deployed worker.
        real = replace(baseline, executor_id="test-real", mode=ExecutionMode.REAL, estimated_latency_ms=100)
        result = select_executor(intent(), CapabilityRegistry((baseline, real)), now=NOW, allow_simulated=True)
        self.assertEqual(result.proposed_executor_id, "test-real")

    def test_cost_then_identifier_break_latency_ties(self):
        baseline = demo_registry(now=NOW).entries[0]
        entries = (replace(baseline, executor_id="c", cost_units=2),
                   replace(baseline, executor_id="b", cost_units=1),
                   replace(baseline, executor_id="a", cost_units=1))
        result = select_executor(intent(), CapabilityRegistry(entries), now=NOW, allow_simulated=True)
        self.assertEqual(result.proposed_executor_id, "a")
        self.assertEqual(result.alternatives, ("b", "c"))

    def test_registry_rejects_invalid_metadata_and_duplicates(self):
        baseline = demo_registry(now=NOW).entries[0]
        for changes in ({"estimated_latency_ms": True}, {"cost_units": -1},
                        {"mode": "REAL"}, {"trusted": "yes"}, {"operations": []},
                        {"checked_at": NOW.replace(tzinfo=None)}, {"executor_id": "private/path"}):
            with self.subTest(fields=list(changes)):
                with self.assertRaises(RegistryError):
                    replace(baseline, **changes)
        with self.assertRaises(RegistryError):
            CapabilityRegistry((baseline, baseline))

    def test_requirement_inventory_is_explicit(self):
        entry = replace(demo_registry(now=NOW).entries[0], requirements=("demo-runtime",))
        result = select_executor(intent(), CapabilityRegistry((entry,)), now=NOW,
                                 allow_simulated=True, available_requirements=frozenset({"demo-runtime"}))
        self.assertEqual(result.status, "PROPOSED")
