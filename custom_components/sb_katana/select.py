"""Selects: output, decoder, EQ preset, Smart Volume mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from . import protocol as p
from .device import KatanaDevice
from .entity import KatanaEntity
from .families import EQ_PRESET_LABELS

_EQ_LABEL_TO_NAME = {label: name for name, label in EQ_PRESET_LABELS.items()}
_SMART_VOLUME_MODES = {"Mode 1": 0, "Mode 2": 1, "Mode 3": 2}
_DECODER_CODES = {label: code for code, label in p.DECODER_LABELS.items()}


def _store_value(device: KatanaDevice, key: tuple[int, int]) -> float | int | None:
    return device.state.store.get(device.state.store_sub, {}).get(key)


def _output(device: KatanaDevice) -> str | None:
    return {"speakers": "Speakers", "headphones": "Headphones"}.get(device.state.output or "")


def _decoder(device: KatanaDevice) -> str | None:
    value = _store_value(device, p.KEY_DECODER)
    return None if value is None else p.DECODER_LABELS.get(round(value))


def _eq_preset(device: KatanaDevice) -> str | None:
    return EQ_PRESET_LABELS.get(device.state.eq_names.get(device.state.store_sub, ""))


def _smart_volume_mode(device: KatanaDevice) -> str | None:
    value = _store_value(device, p.KEY_SMART_VOLUME_MODE)
    if value is None:
        return None
    return next((label for label, code in _SMART_VOLUME_MODES.items() if code == round(value)), None)


@dataclass(frozen=True, kw_only=True)
class KatanaSelectDescription(SelectEntityDescription):
    current: Callable[[KatanaDevice], str | None]
    choose: Callable[[KatanaDevice, str], Awaitable[None]]


SELECTS: tuple[KatanaSelectDescription, ...] = (
    KatanaSelectDescription(
        key="output",
        options=["Speakers", "Headphones"],
        current=_output,
        choose=lambda d, o: d.set_output(o == "Headphones"),
    ),
    KatanaSelectDescription(
        key="decoder",
        options=list(_DECODER_CODES),
        current=_decoder,
        choose=lambda d, o: d.set_store("decoder", p.KEY_DECODER, float(_DECODER_CODES[o])),
    ),
    KatanaSelectDescription(
        key="eq_preset",
        options=list(_EQ_LABEL_TO_NAME),
        current=_eq_preset,
        choose=lambda d, o: d.eq_preset(_EQ_LABEL_TO_NAME[o]),
    ),
    KatanaSelectDescription(
        key="smart_volume_mode",
        options=list(_SMART_VOLUME_MODES),
        current=_smart_volume_mode,
        choose=lambda d, o: d.set_store("smart_volume_detail", p.KEY_SMART_VOLUME_MODE, float(_SMART_VOLUME_MODES[o])),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(KatanaSelect(entry, d) for d in SELECTS)


class KatanaSelect(KatanaEntity, SelectEntity):
    entity_description: KatanaSelectDescription

    def __init__(self, entry: KatanaConfigEntry, description: KatanaSelectDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        return self.entity_description.current(self._device)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ServiceValidationError(f"unknown option {option!r}")
        await self.entity_description.choose(self._device, option)
