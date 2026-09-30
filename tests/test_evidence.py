import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from prometheus_voice.evidence import EvidenceError, EvidenceLedger
from prometheus_voice.execution import ExecutionService, local_registry
from prometheus_voice.intent import IntentEnvelope
from prometheus_voice.planner import build_plan


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "audit.jsonl"
        self.ledger = EvidenceLedger(self.path)
        now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        intent = IntentEnvelope("11111111-1111-4111-8111-111111111111",
                                "22222222-2222-4222-8222-222222222222", now,
                                "math.calculate", {"operator": "add", "a": 19, "b": 23}, confidence=1)
        registry = local_registry(now=now)
        self.plan = build_plan(intent, registry, now=now)
        self.service = ExecutionService(registry, clock=lambda: now)
        self.result = self.service.execute(self.plan)

    def test_append_verify_permissions_and_replay_record(self):
        first = self.ledger.append_execution(self.plan, self.result)
        second = self.ledger.append_execution(self.plan, self.service.execute(self.plan))
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual(self.ledger.verify(expected_head=second.head_hash), second)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_records_exclude_values_and_parameters(self):
        result = replace(self.result, value="SYNTHETIC-PRIVATE-MARKER")
        self.ledger.append_execution(self.plan, result)
        content = self.path.read_text()
        self.assertNotIn("SYNTHETIC-PRIVATE-MARKER", content)
        event = json.loads(content)["event"]
        self.assertNotIn("value", event)
        self.assertNotIn("parameters", event)

    def test_mismatched_correlation_is_rejected_before_file_creation(self):
        with self.assertRaises(EvidenceError):
            self.ledger.append_execution(self.plan, replace(self.result, plan_fingerprint="0" * 64))
        self.assertFalse(self.path.exists())

    def test_untrusted_reason_text_is_rejected(self):
        with self.assertRaises(EvidenceError) as error:
            self.ledger.append_execution(self.plan, replace(self.result, reason_code="SYNTHETIC-PRIVATE-MARKER"))
        self.assertNotIn("SYNTHETIC-PRIVATE-MARKER", str(error.exception))
        self.assertFalse(self.path.exists())

    def test_changed_record_is_detected_and_not_extended(self):
        self.ledger.append_execution(self.plan, self.result)
        self.path.write_bytes(self.path.read_bytes().replace(b'"elapsed_ms":', b'"unexpected":'))
        before = self.path.read_bytes()
        with self.assertRaises(EvidenceError):
            self.ledger.verify()
        with self.assertRaises(EvidenceError):
            self.ledger.append_execution(self.plan, self.result)
        self.assertEqual(self.path.read_bytes(), before)

    def test_tail_deletion_detected_with_retained_head(self):
        self.ledger.append_execution(self.plan, self.result)
        last = self.ledger.append_execution(self.plan, self.result)
        self.path.write_bytes(self.path.read_bytes().splitlines(keepends=True)[0])
        with self.assertRaises(EvidenceError):
            self.ledger.verify(expected_head=last.head_hash)

    def test_partial_write_is_not_automatically_repaired(self):
        self.ledger.append_execution(self.plan, self.result)
        with self.path.open("ab") as stream:
            stream.write(b'{"incomplete":')
        with self.assertRaises(EvidenceError):
            self.ledger.append_execution(self.plan, self.result)

    def test_capacity_limit_preserves_existing_records(self):
        ledger = EvidenceLedger(self.path, max_bytes=1024)
        first = ledger.append_execution(self.plan, self.result)
        with self.assertRaises(EvidenceError):
            ledger.append_execution(self.plan, self.result)
        self.assertEqual(ledger.verify(), first)

    def test_symlink_and_hardlink_are_rejected(self):
        target = Path(self.directory.name) / "target"
        target.write_bytes(b"unchanged")
        self.path.symlink_to(target)
        with self.assertRaises(EvidenceError):
            self.ledger.append_execution(self.plan, self.result)
        self.path.unlink()
        os.link(target, self.path)
        with self.assertRaises(EvidenceError):
            self.ledger.append_execution(self.plan, self.result)
        self.assertEqual(target.read_bytes(), b"unchanged")

    def test_unsafe_permissions_are_rejected(self):
        self.ledger.append_execution(self.plan, self.result)
        self.path.chmod(0o644)
        with self.assertRaises(EvidenceError):
            self.ledger.verify()

    def test_concurrent_instances_preserve_chain(self):
        def append(_):
            return EvidenceLedger(self.path).append_execution(self.plan, self.result)
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(append, range(8)))
        self.assertEqual(sorted(r.sequence for r in receipts), list(range(1, 9)))
        self.assertEqual(self.ledger.verify().sequence, 8)
