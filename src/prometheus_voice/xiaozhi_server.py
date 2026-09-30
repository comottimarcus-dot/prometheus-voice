from __future__ import annotations

import asyncio

from .config import load_settings
from .xiaozhi_bridge import run_bridge


def main() -> None:
    asyncio.run(run_bridge(load_settings()))


if __name__ == "__main__":
    main()
