import unittest
from datetime import datetime, timedelta, timezone

from prometheus_voice.intent import IntentEnvelope, IntentValidationError
from prometheus_voice.policy import DecisionKind, evaluate, evaluate_payload

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def payload(**changes):
    value = dict(version=1, request_id="11111111-1111-4111-8111-111111111111",
                 trace_id="22222222-2222-4222-8222-222222222222",
                 created_at=NOW.isoformat(), operation="math.calculate",
                 parameters={"operator": "add", "a": 2, "b": 3}, confidence=0.95)
    value.update(changes)
    return value


class IntentPolicyTests(unittest.TestCase):
    def test_safe_local_calculation_is_allowed(self):
        decision = evaluate_payload(payload(), now=NOW)
        self.assertEqual(decision.decision, DecisionKind.ALLOW)
        self.assertEqual(decision.reason_code, "SAFE_LOCAL_OPERATION")

    def test_capability_query_is_allowed(self):
        self.assertEqual(evaluate_payload(payload(operation="capabilities.list", parameters={}), now=NOW).decision, DecisionKind.ALLOW)

    def test_simulation_requires_confirmation(self):
        decision = evaluate_payload(payload(operation="demo.simulate", parameters={"scenario": "executor_fallback"}), now=NOW)
        self.assertEqual(decision.decision, DecisionKind.CONFIRM)

    def test_prohibited_actions_cannot_be_allowed_by_confidence(self):
        for operation in ("external.send", "system.delete", "system.execute"):
            with self.subTest(operation=operation):
                decision = evaluate_payload(payload(operation=operation, parameters={}, confidence=1), now=NOW)
                self.assertEqual(decision.decision, DecisionKind.DENY)

    def test_unknown_operation_fails_closed(self):
        self.assertEqual(evaluate_payload(payload(operation="invented.action"), now=NOW).reason_code, "UNKNOWN_OPERATION")

    def test_invalid_inputs_fail_closed(self):
        variants = [None, {}, payload(version=2), payload(version=True), payload(request_id="invalid"),
                    payload(timeout_ms=True), payload(timeout_ms=0), payload(confidence=float("nan")),
                    payload(confidence=True), payload(local_only="true"), payload(created_at="invalid"),
                    payload(created_at="2026-09-23"), payload(parameters={"a": []}),
                    payload(parameters={"a": float("inf")}), payload(parameters={"a": 10**400}),
                    payload(parameters={"text": "x" * 257}), payload(approved=True)]
        for index, item in enumerate(variants):
            with self.subTest(index=index):
                self.assertEqual(evaluate_payload(item, now=NOW).decision, DecisionKind.FAIL_CLOSED)

    def test_schema_mismatch_rejects_commands_and_extra_fields(self):
        for params in ({"operator": "eval", "a": 1, "b": 2},
                       {"operator": "add", "a": True, "b": 2},
                       {"operator": "add", "a": 1, "b": 2, "command": "ignored"}):
            self.assertEqual(evaluate_payload(payload(parameters=params), now=NOW).reason_code, "INVALID_PARAMETERS")

    def test_time_window_and_clock_fail_closed(self):
        for delta in (-1, 10000, 10001):
            self.assertEqual(evaluate_payload(payload(), now=NOW + timedelta(milliseconds=delta)).reason_code, "REQUEST_OUTSIDE_WINDOW")
        self.assertEqual(evaluate_payload(payload(), now=NOW.replace(tzinfo=None)).reason_code, "INVALID_CLOCK")

    def test_uncertainty_and_privacy_are_enforced(self):
        for confidence in (None, 0.79):
            self.assertEqual(evaluate_payload(payload(confidence=confidence), now=NOW).reason_code, "INTENT_UNCERTAIN")
        self.assertEqual(evaluate_payload(payload(local_only=False), now=NOW).decision, DecisionKind.DENY)

    def test_parameter_mutation_cannot_change_validated_intent(self):
        source = payload()
        intent = IntentEnvelope.from_payload(source)
        source["parameters"]["operator"] = "eval"
        self.assertEqual(intent.parameters["operator"], "add")
        with self.assertRaises(TypeError):
            intent.parameters["operator"] = "eval"
        self.assertEqual(evaluate(intent, now=NOW).decision, DecisionKind.ALLOW)

    def test_parameter_text_is_not_in_repr_or_validation_errors(self):
        intent = IntentEnvelope.from_payload(payload(parameters={"note": "SYNTHETIC-PRIVATE"}))
        self.assertNotIn("SYNTHETIC-PRIVATE", repr(intent))
        with self.assertRaises(IntentValidationError) as error:
            IntentEnvelope.from_payload(payload(created_at="SYNTHETIC-PRIVATE"))
        self.assertNotIn("SYNTHETIC-PRIVATE", str(error.exception))

    def test_decision_is_deterministic(self):
        self.assertEqual(evaluate_payload(payload(), now=NOW), evaluate_payload(payload(), now=NOW))
