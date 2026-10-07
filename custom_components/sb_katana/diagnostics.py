"""Diagnostics: the decoded state and stream counters, with identifiers redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import KatanaConfigEntry
from .families import FAMILIES

TO_REDACT = {CONF_ADDRESS, "serial", "address"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: KatanaConfigEntry) -> dict[str, Any]:
    runtime = entry.runtime_data
    device, stream = runtime.device, runtime.stream
    state = asdict(device.state)
    state["store"] = {
        sub: {f"{g:02x}.{i:02x}": v for (g, i), v in values.items()} for sub, values in state["store"].items()
    }
    state["dsp"] = {f"{k:04x}": v for k, v in state["dsp"].items()}
    transport = device._transport
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "address": runtime.address,
            "available": device.available,
            "firmware_ok": device.firmware_ok,
            "allow_unconfirmed": device.allow_unconfirmed,
            "write_limit": getattr(transport, "write_limit", None),
            "families": {k: {"tier": f.tier, "confirmed": f.confirmed} for k, f in FAMILIES.items()},
            "state": state,
            "stream": stream.status(),
        },
        TO_REDACT,
    )
