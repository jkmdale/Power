"""Ingester entrypoint: pick a source adapter from config, pump it into the DB.

Poll-based sources (simulator, shelly_http, emporia) read every POLL_INTERVAL.
Push-based sources (shelly_mqtt) stream as the device publishes.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from config import Config
from store import Store
from adapters.base import EnergyAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ingester")


def build_adapter(cfg: Config) -> EnergyAdapter:
    """Factory: map the SOURCE env var to a concrete adapter."""
    if cfg.source == "simulator":
        from adapters.simulator import SimulatorAdapter
        return SimulatorAdapter(cfg.device_id)
    if cfg.source == "shelly_http":
        from adapters.shelly_http import ShellyHttpAdapter
        return ShellyHttpAdapter(cfg)
    if cfg.source == "shelly_mqtt":
        from adapters.shelly_mqtt import ShellyMqttAdapter
        return ShellyMqttAdapter(cfg)
    if cfg.source == "emporia":
        from adapters.emporia import EmporiaAdapter
        return EmporiaAdapter(cfg)
    raise SystemExit(f"Unknown SOURCE={cfg.source!r}")


async def run_poll(adapter: EnergyAdapter, store: Store, interval: int,
                   stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            readings = await adapter.read()
            await store.write(readings)
        except Exception:  # never let one bad poll kill the loop
            log.exception("poll failed; continuing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def run_stream(adapter: EnergyAdapter, store: Store,
                     stop: asyncio.Event) -> None:
    async for readings in adapter.stream():
        if stop.is_set():
            break
        try:
            await store.write(readings)
        except Exception:
            log.exception("write failed; continuing")


async def main() -> None:
    cfg = Config.from_env()
    log.info("starting ingester: source=%s device_id=%s", cfg.source, cfg.device_id)

    store = Store(cfg.database_url)
    # Retry the initial DB connection — Timescale may still be starting up.
    for attempt in range(1, 31):
        try:
            await store.connect()
            break
        except Exception as exc:
            log.warning("db not ready (attempt %d): %s", attempt, exc)
            await asyncio.sleep(2)
    else:
        raise SystemExit("could not connect to database")

    adapter = build_adapter(cfg)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        if adapter.streaming:
            await run_stream(adapter, store, stop)
        else:
            await run_poll(adapter, store, cfg.poll_interval, stop)
    finally:
        await adapter.close()
        await store.close()
        log.info("ingester stopped")


if __name__ == "__main__":
    asyncio.run(main())
