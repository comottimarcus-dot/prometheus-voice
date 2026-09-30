from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    assemblyai_api_key: str = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8780
    xiaozhi_host: str = "0.0.0.0"
    xiaozhi_port: int = 8766
    xiaozhi_token: str = field(repr=False, default="")
    ota_host: str = "0.0.0.0"
    ota_port: int = 8001
    xiaozhi_public_host: str = ""
    x6_read_enabled: bool = False


def load_settings(env_path: Path | str = ".env") -> Settings:
    path = Path(env_path)

    if not path.is_file():
        raise ConfigurationError("configuration file not found")

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ConfigurationError("configuration file must have mode 600")

    values: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()

    api_key = values.get("ASSEMBLYAI_API_KEY", "")
    if not api_key:
        raise ConfigurationError("ASSEMBLYAI_API_KEY is missing")

    host = values.get("PROMETHEUS_VOICE_HOST", "127.0.0.1")
    xiaozhi_host = values.get("PROMETHEUS_XIAOZHI_HOST", "0.0.0.0")
    xiaozhi_token = values.get("PROMETHEUS_XIAOZHI_TOKEN", "")
    ota_host = values.get("PROMETHEUS_OTA_HOST", "0.0.0.0")
    xiaozhi_public_host = values.get("PROMETHEUS_XIAOZHI_PUBLIC_HOST", "")
    x6_read_enabled = values.get("PROMETHEUS_X6_READ_ENABLED", "0") == "1"

    try:
        port = int(values.get("PROMETHEUS_VOICE_PORT", "8780"))
        xiaozhi_port = int(values.get("PROMETHEUS_XIAOZHI_PORT", "8766"))
        ota_port = int(values.get("PROMETHEUS_OTA_PORT", "8001"))
    except ValueError as exc:
        raise ConfigurationError("PROMETHEUS_VOICE_PORT is invalid") from exc

    if not 1 <= port <= 65535 or not 1 <= xiaozhi_port <= 65535 or not 1 <= ota_port <= 65535:
        raise ConfigurationError("PROMETHEUS_VOICE_PORT is outside the valid range")

    return Settings(
        assemblyai_api_key=api_key,
        host=host,
        port=port,
        xiaozhi_host=xiaozhi_host,
        xiaozhi_port=xiaozhi_port,
        xiaozhi_token=xiaozhi_token,
        ota_host=ota_host,
        ota_port=ota_port,
        xiaozhi_public_host=xiaozhi_public_host,
        x6_read_enabled=x6_read_enabled,
    )
