"""Shelly Pro 3EM via MQTT push (recommended for continuous logging).

Configure the Shelly (Settings -> MQTT) to publish to your local broker with the
prefix in MQTT_TOPIC_PREFIX. The device then PUSHES status; we never poll. This
gives the lowest latency and survives ingester restarts.

Shelly Gen2 publishes the energy-meter component status to:
    <prefix>/status/em:0       (power, voltage, current, pf per phase)
    <prefix>/status/emdata:0   (cumulative energy counters)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Sequence

import aiomqtt

from config import Config
from .base import EnergyAdapter, Reading

log = logging.getLogger("shelly_mqtt")
_PHASES = ("a", "b", "c")


class ShellyMqttAdapter(EnergyAdapter):
    streaming = True

    def __init__(self, cfg: Config) -> None:
        self.device_id = cfg.device_id
        self._cfg = cfg
        self._prefix = cfg.mqtt_topic_prefix
        # Latest known energy counters, merged into power messages as they arrive.
        self._energy: dict[int, float] = {}

    async def stream(self) -> AsyncIterator[Sequence[Reading]]:
        cfg = self._cfg
        while True:  # reconnect loop
            try:
                async with aiomqtt.Client(
                    hostname=cfg.mqtt_host,
                    port=cfg.mqtt_port,
                    username=cfg.mqtt_user or None,
                    password=cfg.mqtt_password or None,
                ) as client:
                    await client.subscribe(f"{self._prefix}/status/em:0")
                    await client.subscribe(f"{self._prefix}/status/emdata:0")
                    log.info("subscribed to %s/status/#", self._prefix)
                    async for msg in client.messages:
                        batch = self._handle(str(msg.topic), msg.payload)
                        if batch:
                            yield batch
            except aiomqtt.MqttError as exc:
                log.warning("mqtt error: %s; reconnecting in 5s", exc)
                import asyncio
                await asyncio.sleep(5)

    def _handle(self, topic: str, payload: bytes) -> Sequence[Reading]:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return []

        if topic.endswith("emdata:0"):
            for ch, ph in enumerate(_PHASES):
                v = data.get(f"{ph}_total_act_energy")
                if v is not None:
                    self._energy[ch] = float(v)
            return []

        # em:0 — power/voltage/current/pf
        now = datetime.now(timezone.utc)
        readings: list[Reading] = []
        for ch, ph in enumerate(_PHASES):
            power = data.get(f"{ph}_act_power")
            if power is None:
                continue
            readings.append(
                Reading(
                    ts=now,
                    device_id=self.device_id,
                    channel=ch,
                    power_w=float(power),
                    voltage_v=_f(data.get(f"{ph}_voltage")),
                    current_a=_f(data.get(f"{ph}_current")),
                    pf=_f(data.get(f"{ph}_pf")),
                    energy_wh=self._energy.get(ch),
                )
            )
        return readings


def _f(v) -> float | None:
    return None if v is None else float(v)
