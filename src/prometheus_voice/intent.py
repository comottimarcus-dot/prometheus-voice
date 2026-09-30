"""Public, versioned request contract; contains no provider credentials or audio."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class IntentValidationError(ValueError):
    """Invalid request. Messages deliberately exclude supplied values."""


def _identifier(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True)
class IntentEnvelope:
    request_id: str
    trace_id: str
    created_at: datetime
    operation: str
    parameters: Mapping[str, str | int | float | bool] = field(repr=False)
    timeout_ms: int = 10000
    confidence: float | None = None
    local_only: bool = True
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise IntentValidationError("unsupported intent version")
        if not _identifier(self.request_id) or not _identifier(self.trace_id):
            raise IntentValidationError("invalid correlation identifier")
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise IntentValidationError("timestamp must include a timezone")
        if not isinstance(self.operation, str) or not re.fullmatch(r"[a-z][a-z0-9_.]{0,63}", self.operation):
            raise IntentValidationError("invalid operation identifier")
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 30000:
            raise IntentValidationError("timeout is outside the supported range")
        if self.confidence is not None and (
            type(self.confidence) not in (int, float) or not 0 <= self.confidence <= 1
        ):
            raise IntentValidationError("invalid confidence")
        if type(self.local_only) is not bool:
            raise IntentValidationError("invalid privacy constraint")
        if not isinstance(self.parameters, Mapping) or len(self.parameters) > 8:
            raise IntentValidationError("invalid parameters")
        copied = dict(self.parameters)
        for key, value in copied.items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", key):
                raise IntentValidationError("invalid parameter name")
            if type(value) not in (str, int, float, bool):
                raise IntentValidationError("unsupported parameter value")
            if isinstance(value, str) and len(value) > 256:
                raise IntentValidationError("parameter text exceeds limit")
            if type(value) in (int, float) and (abs(value) > 10**12 or not math.isfinite(value)):
                raise IntentValidationError("parameter number exceeds limit")
        object.__setattr__(self, "parameters", MappingProxyType(copied))

    @classmethod
    def from_payload(cls, payload: object) -> IntentEnvelope:
        """Parse JSON-decoded input without accepting extra authority fields."""
        required = {"version", "request_id", "trace_id", "created_at", "operation", "parameters"}
        optional = {"timeout_ms", "confidence", "local_only"}
        if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys() - required - optional:
            raise IntentValidationError("invalid intent fields")
        values = dict(payload)
        stamp = values["created_at"]
        if not isinstance(stamp, str) or len(stamp) > 40:
            raise IntentValidationError("invalid timestamp")
        try:
            values["created_at"] = datetime.fromisoformat(stamp)
        except ValueError:
            raise IntentValidationError("invalid timestamp") from None
        return cls(**values)
