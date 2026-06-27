"""The pluggable ingestion contract.

Every hardware/source adapter returns the same `Reading` objects, so the rest
of the system (database, dashboards) is identical no matter which meter you use.
Swapping Shelly for Emporia is a one-line config change, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Sequence


@dataclass(slots=True)
class Reading:
    ts: datetime                 # timezone-aware UTC
    device_id: str
    channel: int
    power_w: float
    voltage_v: float | None = None
    current_a: float | None = None
    pf: float | None = None
    energy_wh: float | None = None  # cumulative counter, if the device exposes one


class EnergyAdapter:
    """Base class for all sources.

    Poll-based adapters implement `read()`. Push-based adapters (e.g. MQTT) set
    `streaming = True` and implement `stream()`. `main.py` picks the right loop.
    """

    streaming: bool = False

    async def read(self) -> Sequence[Reading]:
        """Return the latest reading(s). Called every poll interval."""
        raise NotImplementedError

    async def stream(self) -> AsyncIterator[Sequence[Reading]]:
        """Yield reading batches as the device pushes them."""
        raise NotImplementedError
        yield  # pragma: no cover  (makes this an async generator)

    async def close(self) -> None:
        """Release any sockets/clients. Override if needed."""
