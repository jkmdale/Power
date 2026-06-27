"""Synthetic data source so the whole stack works WITHOUT any hardware.

Models a Christchurch home: a few big appliances that switch on and off, plus a
constant-ish house baseload. Channel 0 is the mains (whole house) and equals the
sum of every appliance PLUS the unmetered baseload — so "rest of house" comes out
positive, exactly as it will with real CT clamps.

Each channel also carries a monotonically increasing energy_wh counter, mirroring
what a real meter exposes, so energy/kWh maths is exercised end to end.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Sequence

from .base import EnergyAdapter, Reading

# channel -> (label, typical-on power W, duty cycle 0..1)
_APPLIANCES = {
    1: ("spa", 3000.0, 0.15),       # spa heater: high power, occasional
    2: ("heat_pump", 1800.0, 0.45),  # ducted heat pump: cycles often
    3: ("oven", 2400.0, 0.08),       # oven: high power, rare
}
_BASELOAD_W = 350.0  # fridge, standby, lights — the unmetered "rest of house"


class SimulatorAdapter(EnergyAdapter):
    streaming = False

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._t = 0.0
        self._energy_wh: dict[int, float] = {ch: 0.0 for ch in (0, 1, 2, 3)}
        self._last_ts: datetime | None = None

    def _appliance_power(self, on_power: float, duty: float, phase: float) -> float:
        # Slow on/off behaviour via a thresholded sine plus jitter.
        cycle = math.sin(self._t / 30.0 + phase)
        on = cycle > (1.0 - 2.0 * duty)
        if not on:
            return 0.0
        return round(on_power * (0.85 + 0.3 * random.random()), 1)

    async def read(self) -> Sequence[Reading]:
        now = datetime.now(timezone.utc)
        dt_h = 0.0
        if self._last_ts is not None:
            dt_h = (now - self._last_ts).total_seconds() / 3600.0
        self._last_ts = now
        self._t += 1.0

        # Appliances
        powers: dict[int, float] = {}
        for i, (ch, (_name, on_power, duty)) in enumerate(_APPLIANCES.items()):
            powers[ch] = self._appliance_power(on_power, duty, phase=i * 2.1)

        baseload = round(_BASELOAD_W * (0.8 + 0.4 * random.random()), 1)
        powers[0] = round(sum(powers.values()) + baseload, 1)  # mains = everything

        readings: list[Reading] = []
        for ch, p in powers.items():
            self._energy_wh[ch] += p * dt_h  # integrate power -> energy
            readings.append(
                Reading(
                    ts=now,
                    device_id=self.device_id,
                    channel=ch,
                    power_w=p,
                    voltage_v=round(230.0 + random.uniform(-3, 3), 1),
                    current_a=round(p / 230.0, 2),
                    pf=0.98,
                    energy_wh=round(self._energy_wh[ch], 3),
                )
            )
        return readings
