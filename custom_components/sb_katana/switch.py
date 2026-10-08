"""Switches: Screen sync, Hold connection, and the soundbar's on/off settings."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import KatanaConfigEntry
from . import protocol as p
from .device import KatanaCommandError, KatanaDevice
from .entity import KatanaEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KatanaSwitchDescription(SwitchEntityDescription):
    is_on: Callable[[KatanaDevice], bool | None]
    set_on: Callable[[KatanaDevice, bool], Awaitable[None]]


def _store(key: tuple[int, int]) -> Callable[[KatanaDevice], bool | None]:
    def get(device: KatanaDevice) -> bool | None:
        value = device.state.store.get(device.state.store_sub, {}).get(key)
        return None if value is None else bool(value)

    return get


def _dsp(pid: int) -> Callable[[KatanaDevice], bool | None]:
    def get(device: KatanaDevice) -> bool | None:
        value = device.state.dsp.get(pid)
        return None if value is None else bool(value)

    return get


SWITCHES: tuple[KatanaSwitchDescription, ...] = (
    KatanaSwitchDescription(key="scout_mode", is_on=lambda d: d.state.scout, set_on=lambda d, on: d.set_scout(on)),
    KatanaSwitchDescription(
        key="auto_switch_tv",
        is_on=lambda d: d.state.auto_switch,
        set_on=lambda d, on: d.set_auto_switch(on),
        entity_category=EntityCategory.CONFIG,
    ),
    KatanaSwitchDescription(
        key="equalizer",
        is_on=_store(p.KEY_EQ_ENABLE),
        set_on=lambda d, on: d.set_store("eq_enable", p.KEY_EQ_ENABLE, float(on)),
    ),
    KatanaSwitchDescription(
        key="surround",
        is_on=_store(p.KEY_SURROUND),
        set_on=lambda d, on: d.set_store("acoustic", p.KEY_SURROUND, float(on)),
    ),
    KatanaSwitchDescription(
        key="crystalizer",
        is_on=_store(p.KEY_CRYSTALIZER),
        set_on=lambda d, on: d.set_store("acoustic", p.KEY_CRYSTALIZER, float(on)),
    ),
    KatanaSwitchDescription(
        key="smart_volume",
        is_on=_store(p.KEY_SMART_VOLUME),
        set_on=lambda d, on: d.set_store("acoustic", p.KEY_SMART_VOLUME, float(on)),
    ),
    KatanaSwitchDescription(
        key="dialog_plus",
        is_on=_store(p.KEY_DIALOG_PLUS),
        set_on=lambda d, on: d.set_store("acoustic", p.KEY_DIALOG_PLUS, float(on)),
    ),
    KatanaSwitchDescription(
        key="energy_saving",
        is_on=lambda d: d.state.energy_saving,
        set_on=lambda d, on: d.set_energy_saving(on),
        entity_category=EntityCategory.CONFIG,
    ),
    KatanaSwitchDescription(
        key="cec_link",
        is_on=lambda d: d.state.cec_link,
        set_on=lambda d, on: d.set_cec_link(on),
        entity_category=EntityCategory.CONFIG,
    ),
    KatanaSwitchDescription(
        key="mic_smart_volume",
        is_on=_dsp(p.DSP_MIC_SMART_VOLUME),
        set_on=lambda d, on: d.set_dsp(p.DSP_MIC_SMART_VOLUME, on),
    ),
    KatanaSwitchDescription(
        key="mic_equalizer", is_on=_dsp(p.DSP_MIC_EQ), set_on=lambda d, on: d.set_dsp(p.DSP_MIC_EQ, on)
    ),
    KatanaSwitchDescription(
        key="mic_focus", is_on=_dsp(p.DSP_MIC_FOCUS), set_on=lambda d, on: d.set_dsp(p.DSP_MIC_FOCUS, on)
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        [ScreenSyncSwitch(entry), HoldConnectionSwitch(entry), *(KatanaSwitch(entry, d) for d in SWITCHES)]
    )


class KatanaSwitch(KatanaEntity, SwitchEntity):
    entity_description: KatanaSwitchDescription

    def __init__(self, entry: KatanaConfigEntry, description: KatanaSwitchDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on(self._device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.entity_description.set_on(self._device, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.entity_description.set_on(self._device, False)


class ScreenSyncSwitch(KatanaEntity, SwitchEntity, RestoreEntity):
    """On by default. A manual lighting change turns it off; switch it back on to resume."""

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "screen_sync")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state in ("on", "off"):
            self._stream.set_screen_sync(last.state == "on")
        self.async_on_remove(self._stream.add_listener(self._handle_update))

    @property
    def is_on(self) -> bool:
        return self._stream.screen_sync

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._stream.set_screen_sync(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._stream.set_screen_sync(False)


class HoldConnectionSwitch(KatanaEntity, SwitchEntity, RestoreEntity):
    """Off releases the Bluetooth link so Creative's app can connect (one central at a time).

    Restored across restarts and reloads: setup connects first (it has to, to read the
    firmware), then this releases the link again if it was off.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "hold_connection")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state == "off":
            self._device.hold_connection = False
            self.hass.async_create_task(self._device.stop(), "sb_katana release link")

    @property
    def is_on(self) -> bool:
        return self._device.hold_connection

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._device.hold_connection = True
        try:
            await self._device.start(keep_trying=True)
        except (KatanaCommandError, TimeoutError, OSError) as err:
            # Not an error: the soundbar is asleep (BLE off) or out of range, and the reconnect loop keeps trying
            # in the background. The entities read unavailable until it answers -- raising here only produced an
            # error toast (and an HTTP 500 over REST) every time this was switched on at night.
            _LOGGER.info(
                "Hold connection on; the soundbar is not reachable yet (%s), reconnecting in the background", err
            )
        finally:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._device.hold_connection = False
        await self._device.stop()
        self.async_write_ha_state()
