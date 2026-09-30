"""Offline end-to-end domain smoke: intent -> policy -> plan -> result -> replay."""
from datetime import datetime, timezone
import argparse
from uuid import uuid4

from .execution import ExecutionService, ExecutionStatus, local_registry
from .intent import IntentEnvelope
from .planner import build_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline governed calculation smoke test")
    parser.add_argument("--ledger", help="Optional local JSONL evidence path; parent must exist")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    intent = IntentEnvelope(str(uuid4()), str(uuid4()), now, "math.calculate",
                            {"operator": "add", "a": 19, "b": 23}, confidence=1)
    registry = local_registry(now=now)
    plan = build_plan(intent, registry, now=now)
    service = ExecutionService(registry)
    result = service.execute(plan)
    replay = service.execute(plan)
    if result.status != ExecutionStatus.EXECUTED or result.value != 42 or replay.reason_code != "DUPLICATE_REQUEST":
        raise SystemExit("SMOKE=FAIL-CLOSED")
    print("MODE=REAL EXECUTOR=local-calculator RESULT=42 REPLAY=BLOCKED SMOKE=GREEN")
    if args.ledger:
        from .evidence import EvidenceError, EvidenceLedger
        try:
            ledger = EvidenceLedger(args.ledger)
            ledger.append_execution(plan, result)
            receipt = ledger.append_execution(plan, replay)
            ledger.verify(expected_head=receipt.head_hash)
        except EvidenceError:
            raise SystemExit("EVIDENCE=FAIL-CLOSED; calculation already completed") from None
        print(f"EVIDENCE=GREEN RECORDS={receipt.sequence} CHAIN=VERIFIED")


if __name__ == "__main__":
    main()
