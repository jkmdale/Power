"""Shelly Pro 3EM via its LOCAL Gen2 HTTP RPC API (no cloud).

Polls two endpoints on the device:
  - EM.GetStatus    -> per-phase real power, voltage, current, power factor
  - EMData.GetStatus -> per-phase cumulative energy counters (Wh)

The Pro 3EM has three measurement "phases" (a, b, c). On a single-phase NZ supply
you can clamp three *different circuits* onto these three CTs, so we map
phase a/b/c -> channel 0/1/2. Make the channels table match your physical wiring.

Whole-house + 3 appliances needs 4 CTs, i.e. a second Shelly device: run a second
copy of this ingester with a different DEVICE_ID and SHELLY_HOST. Rows key on
(device_id, channel), so the two devices coexist cleanly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

import httpx

from config import Config
from .base import EnergyAdapter, Reading

log = logging.getLogger("shelly_http")
_PHASES = ("a", "b", "c")


class ShellyHttpAdapter(EnergyAdapter):
    streaming = False

    def __init__(self, cfg: Config) -> None:
        self.device_id = cfg.device_id
        self._base = f"http://{cfg.shelly_host}"
        # Gen2 uses HTTP digest auth; user is always "admin" on Shelly.
        auth = None
        if cfg.shelly_password:
            auth = httpx.DigestAuth(cfg.shelly_user or "admin", cfg.shelly_password)
        self._client = httpx.AsyncClient(timeout=5.0, auth=auth)

    async def _rpc(self, method: str) -> dict:
        r = await self._client.get(f"{self._base}/rpc/{method}", params={"id": 0})
        r.raise_for_status()
        return r.json()

    async def read(self) -> Sequence[Reading]:
        now = datetime.now(timezone.utc)
        em = await self._rpc("EM.GetStatus")
        try:
            emd = await self._rpc("EMData.GetStatus")
        except httpx.HTTPError:
            emd = {}  # energy counters are optional; power still flows

        readings: list[Reading] = []
        for ch, ph in enumerate(_PHASES):
            power = em.get(f"{ph}_act_power")
            if power is None:
                continue
            readings.append(
                Reading(
                    ts=now,
                    device_id=self.device_id,
                    channel=ch,
                    power_w=float(power),
                    voltage_v=_f(em.get(f"{ph}_voltage")),
                    current_a=_f(em.get(f"{ph}_current")),
                    pf=_f(em.get(f"{ph}_pf")),
                    energy_wh=_f(emd.get(f"{ph}_total_act_energy")),
                )
            )
        return readings

    async def close(self) -> None:
        await self._client.aclose()


def _f(v) -> float | None:
    return None if v is None else float(v)
