#!/usr/bin/env python3
"""Standalone simulator — seed the database with fake data WITHOUT Docker.

Useful for local dev against a Postgres/TimescaleDB you already have running.
Reads DATABASE_URL (and optional DEVICE_ID / POLL_INTERVAL) from the environment
or a .env file, then writes simulated readings until interrupted.

    DATABASE_URL=postgresql://energy:energy@localhost:5432/energy \
        python tools/simulate.py

Inside Docker you don't need this — the `ingester` service runs the same
simulator adapter automatically when SOURCE=simulator.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Make the ingester package importable when run from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ingester"))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from store import Store                       # noqa: E402
from adapters.simulator import SimulatorAdapter  # noqa: E402


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL", "postgresql://energy:energy@localhost:5432/energy"
    )
    device_id = os.environ.get("DEVICE_ID", "sim-board")
    interval = float(os.environ.get("POLL_INTERVAL", "2"))

    store = Store(dsn)
    await store.connect()
    adapter = SimulatorAdapter(device_id)
    print(f"Simulating into {dsn} as device_id={device_id} (Ctrl-C to stop)")
    try:
        while True:
            await store.write(await adapter.read())
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
