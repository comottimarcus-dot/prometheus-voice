from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


class TokenBrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssemblyAIVoiceTokenBroker:
    api_key: str = field(repr=False)
    endpoint: str = "https://agents.assemblyai.com/v1/token"
    timeout_seconds: float = 20.0

    def mint(
        self,
        *,
        expires_in_seconds: int = 60,
        max_session_duration_seconds: int = 900,
    ) -> str:
        if not self.api_key:
            raise TokenBrokerError("API key is missing")

        if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= 600:
            raise TokenBrokerError("token expiry must be between 1 and 600 seconds")

        if type(max_session_duration_seconds) is not int or not 60 <= max_session_duration_seconds <= 10800:
            raise TokenBrokerError(
                "session duration must be between 60 and 10800 seconds"
            )

        query = urllib.parse.urlencode(
            {
                "expires_in_seconds": expires_in_seconds,
                "max_session_duration_seconds": max_session_duration_seconds,
            }
        )

        request = urllib.request.Request(
            f"{self.endpoint}?{query}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "prometheus-voice/0.1",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                if response.status != 200:
                    raise TokenBrokerError("unexpected upstream status")

                raw = response.read(65537)
                if len(raw) > 65536:
                    raise TokenBrokerError("AssemblyAI response exceeded size limit")
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError:
            # Suppress upstream exception text in formatted tracebacks.
            raise TokenBrokerError("AssemblyAI rejected the token request") from None
        except (urllib.error.URLError, OSError):
            raise TokenBrokerError("AssemblyAI token endpoint unavailable") from None
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise TokenBrokerError("AssemblyAI returned an invalid response") from None

        if not isinstance(payload, dict):
            raise TokenBrokerError("AssemblyAI returned an invalid response")

        token = payload.get("token")
        if not isinstance(token, str) or not token.strip():
            raise TokenBrokerError("AssemblyAI response did not contain a token")

        return token
