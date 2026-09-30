"""Bounded local JSONL evidence, hash-linked and private by filesystem mode."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import UUID

from .execution import ExecutionResult
from .planner import GovernedPlan


class EvidenceError(RuntimeError):
    """Sanitized persistence/verification error. Never carries raw record content."""


@dataclass(frozen=True)
class EvidenceReceipt:
    sequence: int
    head_hash: str


_ZERO = "0" * 64
_REASONS = {
    "EXECUTED": {"CALCULATION_COMPLETED"},
    "FAILED": {"INVALID_ADAPTER_RESULT", "ADAPTER_FAILED", "INVALID_CLOCK", "CANCELLED", "EXECUTION_TIMEOUT"},
    "BLOCKED": {"CANCELLED_BEFORE_EXECUTION", "PLAN_NOT_AUTHORIZED", "PLAN_OUTSIDE_WINDOW",
                "PLAN_REVALIDATION_FAILED", "PLAN_MISMATCH", "POLICY_OR_CAPABILITY_BLOCKED",
                "ADAPTER_MISMATCH", "DUPLICATE_REQUEST", "REQUEST_GUARD_FULL"},
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validate(event: object) -> None:
    fields = {"request_id", "trace_id", "plan_fingerprint", "policy", "status", "reason_code",
              "executor_id", "mode", "started_at", "finished_at", "elapsed_ms"}
    if not isinstance(event, dict) or set(event) != fields:
        raise EvidenceError("invalid evidence schema")
    for name in ("request_id", "trace_id"):
        value = event[name]
        if not isinstance(value, str):
            raise EvidenceError("invalid evidence identifier")
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except ValueError:
            raise EvidenceError("invalid evidence identifier") from None
    if not isinstance(event["plan_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", event["plan_fingerprint"]):
        raise EvidenceError("invalid plan fingerprint")
    if event["policy"] not in ("ALLOW", "CONFIRM", "DENY", "FAIL_CLOSED"):
        raise EvidenceError("invalid policy decision")
    status_value = event["status"]
    if not isinstance(status_value, str) or status_value not in _REASONS:
        raise EvidenceError("invalid execution status")
    if not isinstance(event["reason_code"], str) or event["reason_code"] not in _REASONS[status_value]:
        raise EvidenceError("invalid execution reason")
    if status_value == "BLOCKED":
        if event["executor_id"] is not None or event["mode"] is not None:
            raise EvidenceError("blocked record cannot claim execution")
    elif event["executor_id"] != "local-calculator" or event["mode"] != "REAL" or event["policy"] != "ALLOW":
        raise EvidenceError("unsupported execution evidence")
    try:
        timestamps = [datetime.fromisoformat(event[name]) for name in ("started_at", "finished_at")]
    except (TypeError, ValueError):
        raise EvidenceError("invalid evidence timestamp") from None
    if any(value.utcoffset() is None for value in timestamps):
        raise EvidenceError("evidence timestamps require a timezone")
    elapsed = event["elapsed_ms"]
    if type(elapsed) not in (int, float) or elapsed < 0 or elapsed > 86400000 or not math.isfinite(elapsed):
        raise EvidenceError("invalid execution duration")


def execution_event(plan: GovernedPlan, result: ExecutionResult) -> dict[str, object]:
    if (plan.request_id, plan.trace_id, plan.fingerprint) != (result.request_id, result.trace_id, result.plan_fingerprint):
        raise EvidenceError("plan and result correlation mismatch")
    event = {
        "request_id": result.request_id, "trace_id": result.trace_id,
        "plan_fingerprint": result.plan_fingerprint, "policy": plan.selection.policy.decision.value,
        "status": result.status.value, "reason_code": result.reason_code,
        "executor_id": result.executor_id, "mode": result.mode.value if result.mode is not None else None,
        "started_at": result.started_at.isoformat(), "finished_at": result.finished_at.isoformat(),
        "elapsed_ms": result.elapsed_ms,
    }
    _validate(event)
    return event


class EvidenceLedger:
    def __init__(self, path: Path | str, *, max_bytes: int = 1048576) -> None:
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 10485760:
            raise EvidenceError("invalid evidence capacity")
        self.path = Path(path)
        self.max_bytes = max_bytes

    @contextmanager
    def _locked(self, *, create: bool) -> Iterator[int]:
        fd = None
        try:
            flags = (os.O_RDWR | os.O_APPEND | os.O_CREAT) if create else os.O_RDONLY
            fd = os.open(self.path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_uid != os.geteuid() or metadata.st_nlink != 1):
                raise EvidenceError("evidence file permissions or type are unsafe")
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    fcntl.flock(fd, (fcntl.LOCK_EX if create else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise EvidenceError("evidence file is busy") from None
                    time.sleep(0.005)
            yield fd
        except OSError:
            raise EvidenceError("evidence storage unavailable") from None
        finally:
            if fd is not None:
                os.close(fd)

    def _verify(self, fd: int) -> EvidenceReceipt:
        if os.fstat(fd).st_size > self.max_bytes:
            raise EvidenceError("evidence capacity exceeded")
        os.lseek(fd, 0, os.SEEK_SET)
        pieces = []
        remaining = self.max_bytes + 1
        while remaining:
            piece = os.read(fd, min(65536, remaining))
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        data = b"".join(pieces)
        if len(data) > self.max_bytes or (data and not data.endswith(b"\n")):
            raise EvidenceError("evidence file is oversized or incomplete")
        receipt = EvidenceReceipt(0, _ZERO)
        for line in data.splitlines():
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or set(record) != {"version", "sequence", "previous_hash", "event", "hash"}:
                    raise EvidenceError("invalid evidence record")
                if type(record["version"]) is not int or record["version"] != 1:
                    raise EvidenceError("unsupported evidence version")
                if type(record["sequence"]) is not int or record["sequence"] != receipt.sequence + 1 or record["previous_hash"] != receipt.head_hash:
                    raise EvidenceError("evidence chain mismatch")
                _validate(record["event"])
                claimed = record.pop("hash")
                digest = hashlib.sha256(_canonical(record)).hexdigest()
                if claimed != digest:
                    raise EvidenceError("evidence digest mismatch")
                receipt = EvidenceReceipt(record["sequence"], digest)
            except (ValueError, TypeError, RecursionError):
                raise EvidenceError("invalid evidence encoding") from None
        return receipt

    def append_execution(self, plan: GovernedPlan, result: ExecutionResult) -> EvidenceReceipt:
        event = execution_event(plan, result)
        with self._locked(create=True) as fd:
            previous = self._verify(fd)
            record = {"version": 1, "sequence": previous.sequence + 1,
                      "previous_hash": previous.head_hash, "event": event}
            digest = hashlib.sha256(_canonical(record)).hexdigest()
            data = _canonical({**record, "hash": digest}) + b"\n"
            if os.fstat(fd).st_size + len(data) > self.max_bytes:
                raise EvidenceError("evidence capacity exceeded")
            pending = memoryview(data)
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise EvidenceError("evidence write failed")
                pending = pending[written:]
            os.fsync(fd)
            return EvidenceReceipt(record["sequence"], digest)

    def verify(self, *, expected_head: str | None = None) -> EvidenceReceipt:
        with self._locked(create=False) as fd:
            receipt = self._verify(fd)
            if expected_head is not None and expected_head != receipt.head_hash:
                raise EvidenceError("evidence head does not match retained receipt")
            return receipt
