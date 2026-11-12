"""Sound Blaster Katana V2X over Bluetooth LE.

Replaces Creative's app: lighting (and screen sync from the PC), volume,
input/output, sound modes, the acoustic engine, EQ, CrystalVoice, scout mode
and the mixer -- every command the app was captured sending. See
docs/protocol.md for the evidence and the design spec for the safety model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from . import protocol
from .api import async_setup_api
from .const import (
    CONF_ALLOW_UNCONFIRMED,
    CONF_STREAM_RATE,
    CONF_STREAM_TIMEOUT,
    DEFAULT_STREAM_RATE,
    DEFAULT_STREAM_TIMEOUT,
    DOMAIN,
    POLL_INTERVAL,
)
from .device import KatanaCommandError, KatanaDevice
from .stream import StreamController
from .transport import BleakTransport

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class KatanaRuntime:
    device: KatanaDevice
    stream: StreamController
    address: str


type KatanaConfigEntry = ConfigEntry[KatanaRuntime]


def _make_transport(hass: HomeAssistant, address: str) -> BleakTransport:
    """Separate so tests can substitute the fake soundbar."""
    return BleakTransport(hass, address)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KatanaConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]
    device = KatanaDevice(
        _make_transport(hass, address),
        allow_unconfirmed=entry.options.get(CONF_ALLOW_UNCONFIRMED, False),
    )
    try:
        await device.start(keep_trying=True)
    except (KatanaCommandError, BleakError, TimeoutError, OSError) as err:
        # The config flow reached this soundbar once, so silence now most likely means standby -- its BLE is off
        # then (every night, with the TV or auto standby). Load anyway: entities read unavailable and every write
        # stays locked until the firmware is read on a real connection; the device's own reconnect loop (gentle
        # while asleep, immediate on request) brings it back. Raising ConfigEntryNotReady instead hands retrying
        # to HA, which re-attempts every ~80 s forever -- each an active scan on the adapter other BLE devices
        # share -- and keeps the screen-sync endpoint down meanwhile.
        _LOGGER.info(
            "Katana at %s not reachable at setup (%s); loading anyway, reconnecting in the background", address, err
        )

    issue_id = f"untested_firmware_{entry.entry_id}"
    shown: list[str | None] = [None]

    def _sync_firmware_issue() -> None:
        """Re-checked on every verified (re)connect: the app could update the firmware meanwhile."""
        if not device.available or device.state.firmware == shown[0]:
            return
        shown[0] = device.state.firmware
        if device.firmware_ok:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        else:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="untested_firmware",
                translation_placeholders={"found": str(device.state.firmware), "tested": protocol.TESTED_FIRMWARE},
            )

    _sync_firmware_issue()
    entry.async_on_unload(device.add_listener(_sync_firmware_issue))

    stream = StreamController(
        hass,
        device,
        rate_hz=entry.options.get(CONF_STREAM_RATE, DEFAULT_STREAM_RATE),
        timeout_s=entry.options.get(CONF_STREAM_TIMEOUT, DEFAULT_STREAM_TIMEOUT),
    )
    entry.runtime_data = KatanaRuntime(device, stream, address)

    # Heard advertising = awake again (in standby its BLE is off): reconnect now, not at the next blind retry.
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            lambda _info, _change: device.request_reconnect("advertisement heard"),
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=False),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    async def _poll(_now) -> None:
        if device.available:
            await device.refresh()

    entry.async_on_unload(async_track_time_interval(hass, _poll, timedelta(seconds=POLL_INTERVAL)))

    async def _on_stop(_event: Event) -> None:
        stream.shutdown()
        await device.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: KatanaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KatanaConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry.runtime_data.stream.shutdown()
        await entry.runtime_data.device.stop()
    return unload_ok
