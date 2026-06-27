"""Configuration loaded once from the environment. No secrets in code."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(slots=True)
class Config:
    database_url: str
    source: str
    device_id: str
    poll_interval: int

    # Shelly (local)
    shelly_host: str
    shelly_user: str
    shelly_password: str

    # MQTT (Shelly push)
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_topic_prefix: str

    # Emporia (cloud)
    emporia_email: str
    emporia_password: str
    emporia_poll_interval: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://energy:energy@timescaledb:5432/energy"
            ),
            source=os.environ.get("SOURCE", "simulator").strip().lower(),
            device_id=os.environ.get("DEVICE_ID", "sim-board"),
            poll_interval=_int("POLL_INTERVAL", 2),
            shelly_host=os.environ.get("SHELLY_HOST", ""),
            shelly_user=os.environ.get("SHELLY_USER", "admin"),
            shelly_password=os.environ.get("SHELLY_PASSWORD", ""),
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=_int("MQTT_PORT", 1883),
            mqtt_user=os.environ.get("MQTT_USER", ""),
            mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
            mqtt_topic_prefix=os.environ.get("MQTT_TOPIC_PREFIX", "shellypro3em"),
            emporia_email=os.environ.get("EMPORIA_EMAIL", ""),
            emporia_password=os.environ.get("EMPORIA_PASSWORD", ""),
            emporia_poll_interval=_int("EMPORIA_POLL_INTERVAL", 60),
        )
