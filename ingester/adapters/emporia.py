"""Emporia Vue via the UNOFFICIAL cloud API (pyemvue).

Caveats (see the README and the architecture guide):
  * No official/local API exists — this polls Emporia's cloud and can break if
    Emporia changes their backend.
  * Granularity is ~1 minute; do not poll faster than EMPORIA_POLL_INTERVAL.
  * Credentials are your Emporia app email/password. We log in once and reuse the
    returned tokens; never hard-code these in source.

Channel mapping: each Emporia CT becomes a channel. By convention we put the
whole-house mains on channel 0 and the branch circuits on 1..N — adjust to match
how you've named circuits in the Emporia app, and seed the `channels` table to suit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from config import Config
from .base import EnergyAdapter, Reading

log = logging.getLogger("emporia")


class EmporiaAdapter(EnergyAdapter):
    streaming = False

    def __init__(self, cfg: Config) -> None:
        if not cfg.emporia_email or not cfg.emporia_password:
            raise SystemExit("EMPORIA_EMAIL / EMPORIA_PASSWORD must be set")
        # Imported lazily so the other sources don't need pyemvue installed.
        import pyemvue
        from pyemvue.enums import Scale, Unit

        self.device_id = cfg.device_id
        self._Scale = Scale
        self._Unit = Unit
        self._vue = pyemvue.PyEmVue()
        self._vue.login(username=cfg.emporia_email, password=cfg.emporia_password)
        self._devices = self._vue.get_devices()
        # gid -> channel index, in a stable order.
        self._gids = sorted({d.device_gid for d in self._devices})
        log.info("emporia: %d device(s) found", len(self._gids))

    async def read(self) -> Sequence[Reading]:
        now = datetime.now(timezone.utc)
        # 1-minute average power in kW for every channel, in one cloud call.
        usage = self._vue.get_device_list_usage(
            deviceGids=self._gids,
            instant=now,
            scale=self._Scale.MINUTE.value,
            unit=self._Unit.KWH.value,
        )
        readings: list[Reading] = []
        ch = 0
        for gid, device in usage.items():
            for _name, chan in device.channels.items():
                kwh_per_min = chan.usage or 0.0
                power_w = kwh_per_min * 60.0 * 1000.0  # kWh/min -> W
                readings.append(
                    Reading(
                        ts=now,
                        device_id=self.device_id,
                        channel=ch,
                        power_w=round(power_w, 1),
                    )
                )
                ch += 1
        return readings
