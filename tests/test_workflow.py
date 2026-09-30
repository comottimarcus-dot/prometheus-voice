import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from prometheus_voice.evidence import EvidenceError, EvidenceLedger
from prometheus_voice.workflow import GovernedWorkflow, WorkflowError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.ledger = EvidenceLedger(Path(self.temp.name) / 'audit.jsonl')
        self.workflow = GovernedWorkflow(self.ledger, clock=lambda: self.now)

    def prepare(self):
        return self.workflow.prepare({'operation': 'math.calculate', 'parameters': {'operator': 'add', 'a': 19, 'b': 23}})

    def test_plan_execute_evidence_and_cached_retry(self):
        proposal = self.prepare()
        self.assertTrue(proposal['can_execute'])
        self.assertFalse(self.ledger.path.exists())
        first = self.workflow.execute({'plan_id': proposal['plan_id']})
        self.assertEqual(first['value'], 42)
        self.assertEqual(first['evidence']['status'], 'VERIFIED')
        second = self.workflow.execute({'plan_id': proposal['plan_id']})
        self.assertTrue(second['replayed'])
        self.assertEqual(second['value'], 42)
        self.assertEqual(self.ledger.verify().sequence, 1)

    def test_server_remains_usable_after_original_health_window(self):
        self.now += timedelta(minutes=5)
        proposal = self.prepare()
        self.now += timedelta(seconds=2)
        self.assertEqual(self.workflow.execute({'plan_id': proposal['plan_id']})['status'], 'EXECUTED')

    def test_execution_uses_stored_plan_not_client_parameters(self):
        proposal = self.prepare()
        with self.assertRaises(WorkflowError):
            self.workflow.execute({'plan_id': proposal['plan_id'], 'parameters': {'a': 100}})

    def test_confirmation_and_denial_cannot_execute(self):
        for operation, params, decision in [('demo.simulate', {'scenario': 'executor_fallback'}, 'CONFIRM'), ('system.delete', {}, 'DENY')]:
            proposal = self.workflow.prepare({'operation': operation, 'parameters': params})
            self.assertFalse(proposal['can_execute'])
            self.assertEqual(proposal['plan']['selection']['policy']['decision'], decision)
            with self.assertRaises(WorkflowError):
                self.workflow.execute({'plan_id': proposal['plan_id']})
        self.assertFalse(self.ledger.path.exists())

    def test_expired_plan_is_not_executed(self):
        proposal = self.prepare()
        self.now += timedelta(seconds=30)
        with self.assertRaises(WorkflowError) as error:
            self.workflow.execute({'plan_id': proposal['plan_id']})
        self.assertEqual(error.exception.code, 'PLAN_EXPIRED')

    def test_client_authority_and_malformed_intent_are_rejected(self):
        for payload in ({'operation': 'math.calculate', 'parameters': {}, 'approved': True},
                        {'operation': 'math.calculate', 'parameters': []}, None):
            with self.assertRaises(WorkflowError):
                self.workflow.prepare(payload)

    def test_evidence_failure_does_not_repeat_calculation(self):
        ledger = Mock()
        ledger.append_execution.side_effect = EvidenceError('storage unavailable')
        workflow = GovernedWorkflow(ledger, clock=lambda: self.now)
        proposal = workflow.prepare({'operation': 'math.calculate', 'parameters': {'operator': 'add', 'a': 1, 'b': 2}})
        first = workflow.execute({'plan_id': proposal['plan_id']})
        self.assertEqual(first['status'], 'EXECUTED')
        self.assertEqual(first['evidence']['status'], 'FAILED')
        self.assertTrue(workflow.execute({'plan_id': proposal['plan_id']})['replayed'])
        ledger.append_execution.assert_called_once()

    def test_plan_store_capacity_and_expiration(self):
        self.workflow = GovernedWorkflow(self.ledger, clock=lambda: self.now, capacity=1)
        self.prepare()
        with self.assertRaises(WorkflowError):
            self.prepare()
        self.now += timedelta(seconds=31)
        self.assertTrue(self.prepare()['can_execute'])
