"""Selects: input, sound mode, output, decoder, EQ and microphone presets, device settings.

Selects with a fixed option list expose slug keys ("usb_audio", "28_hours") rather than
the soundbar's English labels, so the UI can translate them (``strings.json`` ->
``entity.select.<key>.state``). The labels stay the internal currency: protocol tables,
captured presets and the device API all speak labels, and ``option_key`` is the one
place that maps between the two. Options the soundbar names itself (its stored sound
modes, its EQ presets) are shown as it names them.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry, captured
from . import protocol as p
from .const import DOMAIN
from .device import KatanaDevice
from .entity import KatanaEntity
from .families import EQ_PRESET_LABELS

_EQ_LABEL_TO_NAME = {label: name for name, label in EQ_PRESET_LABELS.items()}
# 0 = the level slider, 1 = Loud, 2 = Night (third capture: the app's Night/Loud buttons).
_SMART_VOLUME_MODES = {"Manual": 0, "Loud": 1, "Night": 2}
_MIC_EQ_OFF = "Off"
_DECODER_CODES = {label: code for code, label in p.DECODER_LABELS.items()}


def option_key(label: str) -> str:
    """A label as a translation key: lower case, every run of other characters one '_'."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _store_value(device: KatanaDevice, key: tuple[int, int]) -> float | int | None:
    return device.state.store.get(device.state.store_sub, {}).get(key)


def _output(device: KatanaDevice) -> str | None:
    return {"speakers": "Speakers", "headphones": "Headphones"}.get(device.state.output or "")


def _decoder(device: KatanaDevice) -> str | None:
    value = _store_value(device, p.KEY_DECODER)
    return None if value is None else p.DECODER_LABELS.get(round(value))


def _eq_live_name(device: KatanaDevice) -> str | None:
    return device.state.eq_names.get(device.state.store_sub)


def _eq_preset(device: KatanaDevice) -> str | None:
    name = _eq_live_name(device)
    return None if name is None else EQ_PRESET_LABELS.get(name, name)


def _eq_options(device: KatanaDevice) -> list[str]:
    """The captured presets, plus the live EQ's own name ("Onboard" once edited) while it is none of them."""
    options = list(_EQ_LABEL_TO_NAME)
    current = _eq_preset(device)
    if current and current not in options:
        options.append(current)
    return options


async def _choose_eq(device: KatanaDevice, label: str) -> None:
    if label not in _EQ_LABEL_TO_NAME:
        return  # the live EQ itself: already active, nothing to send
    await device.eq_preset(_EQ_LABEL_TO_NAME[label])


def _mic_priority(device: KatanaDevice) -> str | None:
    current = device.state.mic_priority
    return next((label for label, ids in p.MIC_PRIORITY_OPTIONS.items() if ids == current), None)


def _mic_eq(device: KatanaDevice) -> str | None:
    enabled = device.state.dsp.get(p.DSP_MIC_EQ)
    if enabled is None:
        return None
    if not enabled:
        return _MIC_EQ_OFF
    bands = [device.state.dsp.get(pid) for pid in p.DSP_MIC_EQ_BANDS]
    if any(b is None for b in bands):
        return None
    for name, hexframe in captured.MIC_EQ_PRESETS.items():
        payload = bytes.fromhex(hexframe)[3:]
        preset = {
            struct.unpack(">H", payload[1 + 6 * i : 3 + 6 * i])[0]: struct.unpack("<f", payload[3 + 6 * i : 7 + 6 * i])[
                0
            ]
            for i in range(8)
        }
        if all(abs(preset[pid] - value) < 0.01 for pid, value in zip(p.DSP_MIC_EQ_BANDS, bands, strict=True)):
            return name
    return None


async def _choose_mic_eq(device: KatanaDevice, label: str) -> None:
    await device.mic_eq_preset(None if label == _MIC_EQ_OFF else label)


def _auto_standby(device: KatanaDevice) -> str | None:
    value = device.state.auto_standby
    return next((label for label, minutes in p.AUTO_STANDBY_OPTIONS.items() if minutes == value), None)


def _display(device: KatanaDevice) -> str | None:
    value = device.state.display
    return next((label for label, code in p.DISPLAY_OPTIONS.items() if code == value), None)


def _smart_volume_mode(device: KatanaDevice) -> str | None:
    value = _store_value(device, p.KEY_SMART_VOLUME_MODE)
    if value is None:
        return None
    return next((label for label, code in _SMART_VOLUME_MODES.items() if code == round(value)), None)


def _input_options(device: KatanaDevice) -> list[str]:
    ids = device.state.inputs or list(p.INPUT_LABELS)
    return [p.INPUT_LABELS[i] for i in ids if i in p.INPUT_LABELS]


async def _choose_input(device: KatanaDevice, label: str) -> None:
    ids = {name: i for i, name in p.INPUT_LABELS.items()}
    await device.set_input(ids[label])


async def _choose_mode(device: KatanaDevice, name: str) -> None:
    stored = device.state.stored_modes()
    if name not in stored:
        # The live settings ("Onboard"): already active, nothing to send.
        return
    await device.select_mode(stored[name])


@dataclass(frozen=True, kw_only=True)
class KatanaSelectDescription(SelectEntityDescription):
    current: Callable[[KatanaDevice], str | None]
    choose: Callable[[KatanaDevice, str], Awaitable[None]]
    # Options read from the soundbar (its input list, its stored modes) rather than fixed.
    options_fn: Callable[[KatanaDevice], list[str]] | None = None
    # Expose option_key(label) instead of the label, so the state can be translated.
    translated: bool = True


SELECTS: tuple[KatanaSelectDescription, ...] = (
    # Input and sound mode are also on the media player; as selects they show up on
    # the device page and in dashboards, where users look for them.
    KatanaSelectDescription(
        key="input",
        options=[],
        options_fn=_input_options,
        current=lambda d: p.INPUT_LABELS.get(d.state.input) if d.state.input is not None else None,
        choose=_choose_input,
    ),
    KatanaSelectDescription(
        key="sound_mode",
        options=[],
        options_fn=lambda d: d.state.mode_options(),
        current=lambda d: d.state.mode_name,
        choose=_choose_mode,
        translated=False,  # the soundbar's own names: "Music.", "Gaming.", "Onboard"
    ),
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
        options=[],
        options_fn=_eq_options,
        current=_eq_preset,
        choose=_choose_eq,
        translated=False,  # Creative's preset names, plus the live EQ's own name
    ),
    KatanaSelectDescription(
        key="mic_priority",
        options=list(p.MIC_PRIORITY_OPTIONS),
        current=_mic_priority,
        choose=lambda d, o: d.set_mic_priority(p.MIC_PRIORITY_OPTIONS[o]),
    ),
    KatanaSelectDescription(
        key="mic_eq_preset",
        options=[_MIC_EQ_OFF, *captured.MIC_EQ_PRESETS],
        current=_mic_eq,
        choose=_choose_mic_eq,
    ),
    KatanaSelectDescription(
        key="auto_standby",
        options=list(p.AUTO_STANDBY_OPTIONS),
        current=_auto_standby,
        choose=lambda d, o: d.set_auto_standby(p.AUTO_STANDBY_OPTIONS[o]),
        entity_category=EntityCategory.CONFIG,
    ),
    KatanaSelectDescription(
        key="display",
        options=list(p.DISPLAY_OPTIONS),
        current=_display,
        choose=lambda d, o: d.set_display(p.DISPLAY_OPTIONS[o]),
        entity_category=EntityCategory.CONFIG,
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

    def _labels(self) -> list[str]:
        if self.entity_description.options_fn is not None:
            return self.entity_description.options_fn(self._device)
        return list(self.entity_description.options or [])

    @property
    def options(self) -> list[str]:
        labels = self._labels()
        return [option_key(label) for label in labels] if self.entity_description.translated else labels

    @property
    def current_option(self) -> str | None:
        current = self.entity_description.current(self._device)
        if current is None or current not in self._labels():
            return None
        return option_key(current) if self.entity_description.translated else current

    @property
    def extra_state_attributes(self) -> dict[str, bool] | None:
        if self.entity_description.key != "sound_mode":
            return None
        # Settings changed after the mode was picked; picking it again restores it.
        return {"modified": self._device.state.mode_modified}

    async def async_select_option(self, option: str) -> None:
        labels = self._labels()
        key = option_key if self.entity_description.translated else str
        by_option = {key(label): label for label in labels}
        if option not in by_option:
            raise ServiceValidationError(
                f"unknown option {option!r}",
                translation_domain=DOMAIN,
                translation_key="unknown_option",
                translation_placeholders={"option": option},
            )
        await self.entity_description.choose(self._device, by_option[option])
