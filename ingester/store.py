"""Batched writes into the TimescaleDB `readings` hypertable via asyncpg."""
from __future__ import annotations

import logging
from typing import Sequence

import asyncpg

from adapters.base import Reading

log = logging.getLogger("store")

_INSERT = """
    INSERT INTO readings
        (ts, device_id, channel, power_w, voltage_v, current_a, pf, energy_wh)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""


class Store:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        log.info("connected to database")

    async def write(self, readings: Sequence[Reading]) -> None:
        if not self._pool or not readings:
            return
        rows = [
            (r.ts, r.device_id, r.channel, r.power_w,
             r.voltage_v, r.current_a, r.pf, r.energy_wh)
            for r in readings
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(_INSERT, rows)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
