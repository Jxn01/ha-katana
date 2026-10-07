"""Numbers: acoustic-engine levels, mixer levels, subwoofer."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfSoundPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from . import protocol as p
from .device import KatanaDevice
from .entity import KatanaEntity


@dataclass(frozen=True, kw_only=True)
class KatanaNumberDescription(NumberEntityDescription):
    value: Callable[[KatanaDevice], float | None]
    set_value: Callable[[KatanaDevice, float], Awaitable[None]]


def _store_pct(key: tuple[int, int]) -> Callable[[KatanaDevice], float | None]:
    def get(device: KatanaDevice) -> float | None:
        value = device.state.store.get(device.state.store_sub, {}).get(key)
        return None if value is None else round(float(value) * 100)

    return get


def _store_setter(family: str, key: tuple[int, int]) -> Callable[[KatanaDevice, float], Awaitable[None]]:
    return lambda d, v: d.set_store(family, key, round(v) / 100)


def _level_pct(channel: int) -> Callable[[KatanaDevice], float | None]:
    def get(device: KatanaDevice) -> float | None:
        level = device.state.levels.get(channel)
        return None if level is None else level * 100 / p.LEVEL_MAX

    return get


def _level_setter(family: str, channel: int) -> Callable[[KatanaDevice, float], Awaitable[None]]:
    return lambda d, v: d.set_level(family, channel, round(v * p.LEVEL_MAX / 100))


def _pct(key: str, value, set_value) -> KatanaNumberDescription:
    return KatanaNumberDescription(
        key=key,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value=value,
        set_value=set_value,
    )


def _mixer(key: str, family: str, channel: int, *, enabled: bool = True) -> KatanaNumberDescription:
    return KatanaNumberDescription(
        key=key,
        entity_registry_enabled_default=enabled,
        native_min_value=0,
        native_max_value=100,
        native_step=100 / p.LEVEL_MAX,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value=_level_pct(channel),
        set_value=_level_setter(family, channel),
    )


NUMBERS: tuple[KatanaNumberDescription, ...] = (
    _pct("surround_level", _store_pct(p.KEY_SURROUND_LEVEL), _store_setter("acoustic", p.KEY_SURROUND_LEVEL)),
    _pct("crystalizer_level", _store_pct(p.KEY_CRYSTALIZER_LEVEL), _store_setter("acoustic", p.KEY_CRYSTALIZER_LEVEL)),
    _pct("dialog_plus_level", _store_pct(p.KEY_DIALOG_PLUS_LEVEL), _store_setter("acoustic", p.KEY_DIALOG_PLUS_LEVEL)),
    _pct(
        "smart_volume_level",
        _store_pct(p.KEY_SMART_VOLUME_LEVEL),
        _store_setter("smart_volume_detail", p.KEY_SMART_VOLUME_LEVEL),
    ),
    _mixer("line_in_level", "mixer", p.CH_LINE_IN),
    _mixer("spdif_in_level", "mixer", p.CH_SPDIF_IN),
    _mixer("microphone_level", "mixer", p.CH_MICROPHONE),
    # Reported not working (2026-10-07); headphones are not used here, so hidden by default.
    _mixer("headphones_level", "headphones_level", p.CH_HEADPHONES, enabled=False),
    _mixer("what_u_hear_level", "what_u_hear", p.CH_WHAT_U_HEAR),
    KatanaNumberDescription(
        key="subwoofer",
        native_min_value=p.SUB_MIN,
        native_max_value=p.SUB_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        mode=NumberMode.SLIDER,
        value=lambda d: d.state.sub,
        set_value=lambda d, v: d.set_sub(round(v)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(KatanaNumber(entry, d) for d in NUMBERS)


class KatanaNumber(KatanaEntity, NumberEntity):
    entity_description: KatanaNumberDescription

    def __init__(self, entry: KatanaConfigEntry, description: KatanaNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self._device)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_value(self._device, value)
