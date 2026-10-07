"""The light bar: on/off, solid colour (software brightness), and the app's nine presets.

The light's state does not follow screen-sync frames. While the PC is streaming,
colour attributes stay frozen at their value when the stream started, so the
recorder sees two changes per session (on, off) instead of one per frame.
"""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from .entity import KatanaEntity
from .families import LIGHT_PRESET_LABELS

_LABEL_TO_PRESET = {label: name for name, label in LIGHT_PRESET_LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([KatanaLight(entry)])


def split_brightness(rgb: tuple[int, int, int]) -> tuple[tuple[int, int, int], int]:
    """Device colour -> (full-brightness colour, brightness). The device has no brightness of its own."""
    peak = max(rgb)
    if peak == 0:
        return (0, 0, 0), 0
    return tuple(round(c * 255 / peak) for c in rgb), peak


def apply_brightness(rgb: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * brightness / 255))) for c in rgb)


class KatanaLight(KatanaEntity, LightEntity):
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list: ClassVar[list[str]] = list(LIGHT_PRESET_LABELS.values())

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "lighting")
        self._frozen: tuple[tuple[int, int, int] | None, int | None, str | None] | None = None
        self._last_presented: tuple | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._stream.add_listener(self._handle_update))

    def _live(self) -> tuple[tuple[int, int, int] | None, int | None, str | None]:
        s = self._device.state
        colours = s.light_colours
        rgb, brightness = (None, None)
        if colours:
            rgb, brightness = split_brightness(colours[0])
        effect = None
        if s.light_solid is False and s.light_name in LIGHT_PRESET_LABELS:
            effect = LIGHT_PRESET_LABELS[s.light_name]
        return rgb, brightness, effect

    def _presented(self) -> tuple[tuple[int, int, int] | None, int | None, str | None]:
        if self._stream.receiving:
            if self._frozen is None:
                self._frozen = self._live()
            return self._frozen
        self._frozen = None
        return self._live()

    def _handle_update(self) -> None:
        snapshot = (self._device.available, self.is_on, *self._presented())
        if snapshot != self._last_presented:
            self._last_presented = snapshot
            self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.light_on

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._presented()[0]

    @property
    def brightness(self) -> int | None:
        return self._presented()[1]

    @property
    def effect(self) -> str | None:
        return self._presented()[2]

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._stream.manual_override()
        if ATTR_EFFECT in kwargs:
            await self._device.light_preset(_LABEL_TO_PRESET.get(kwargs[ATTR_EFFECT], kwargs[ATTR_EFFECT]))
            return
        if ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            current_rgb, current_brightness, _ = self._live()
            rgb = kwargs.get(ATTR_RGB_COLOR) or (current_rgb if current_rgb and any(current_rgb) else (255, 255, 255))
            brightness = kwargs.get(ATTR_BRIGHTNESS, current_brightness or 255)
            await self._device.light_solo(apply_brightness(tuple(rgb), brightness))
            return
        await self._device.light_on_off(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._stream.manual_override()
        await self._device.light_on_off(False)
