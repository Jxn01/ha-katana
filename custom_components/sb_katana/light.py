"""The light bar: on/off, solid colour, the soundbar's Global Brightness, and the app's nine presets.

Two rules keep the recorder quiet (this HA has no recorder exclusions):

* While the PC is streaming through HA, colour attributes stay frozen at their
  value when the stream started -- a session costs two state changes, not one
  per frame.
* A colour change HA did not cause (ambience-rgb over USB, the remote, the
  Creative app) is published at most once per ``EXTERNAL_COLOUR_INTERVAL``.
  On/off changes and HA's own commands are always published at once.
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
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import KatanaConfigEntry
from .entity import KatanaEntity
from .families import LIGHT_PRESET_LABELS

_LABEL_TO_PRESET = {label: name for name, label in LIGHT_PRESET_LABELS.items()}
EXTERNAL_COLOUR_INTERVAL = 30.0

Shown = tuple[tuple[int, int, int] | None, int | None, str | None]


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


class KatanaLight(KatanaEntity, LightEntity):
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list: ClassVar[list[str]] = list(LIGHT_PRESET_LABELS.values())

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "lighting")
        self._frozen: Shown | None = None
        self._shown: Shown | None = None
        self._head: tuple[bool, bool | None] | None = None
        self._last_publish = float("-inf")
        self._publish_timer: CALLBACK_TYPE | None = None
        self._commanding = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._stream.add_listener(self._handle_update))
        self.async_on_remove(self._cancel_timer)

    def _cancel_timer(self) -> None:
        if self._publish_timer is not None:
            self._publish_timer()
            self._publish_timer = None

    def _live(self) -> Shown:
        s = self._device.state
        colours = s.light_colours
        rgb, brightness = (None, None)
        if colours:
            rgb, brightness = split_brightness(colours[0])
        if s.light_brightness is not None:
            # The soundbar's own Global Brightness (3a 27/28); the colour shows the hue.
            brightness = s.light_brightness
        effect = None
        if s.light_solid is False and s.light_name in LIGHT_PRESET_LABELS:
            effect = LIGHT_PRESET_LABELS[s.light_name]
        return rgb, brightness, effect

    def _presented(self) -> Shown:
        if self._stream.receiving:
            if self._frozen is None:
                self._frozen = self._live()
            return self._frozen
        self._frozen = None
        return self._live()

    def _handle_update(self) -> None:
        live = self._presented()
        head = (self._device.available, self._device.state.light_on)
        if self._shown is None or head != self._head or self._commanding:
            self._publish()
            return
        if live == self._shown or self._publish_timer is not None:
            return
        delay = max(0.0, self._last_publish + EXTERNAL_COLOUR_INTERVAL - self.hass.loop.time())
        self._publish_timer = async_call_later(self.hass, delay, self._publish_later)

    @callback
    def _publish_later(self, _now) -> None:
        self._publish_timer = None
        self._publish()

    def _publish(self) -> None:
        self._cancel_timer()
        shown = self._presented()
        head = (self._device.available, self._device.state.light_on)
        if (shown, head) == (self._shown, self._head):
            return
        self._shown, self._head = shown, head
        self._last_publish = self.hass.loop.time()
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._device.state.light_on

    def _current(self) -> Shown:
        return self._shown if self._shown is not None else self._presented()

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._current()[0]

    @property
    def brightness(self) -> int | None:
        return self._current()[1]

    @property
    def effect(self) -> str | None:
        return self._current()[2]

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._commanding = True
        try:
            await self._turn_on(**kwargs)
        finally:
            self._handle_update()
            self._commanding = False

    async def _turn_on(self, **kwargs: Any) -> None:
        # Refuse before yielding Screen sync: a refused command must change nothing.
        families = []
        if ATTR_EFFECT in kwargs:
            families.append("light_preset")
        elif ATTR_RGB_COLOR in kwargs:
            families.append("light_solo")
        if ATTR_BRIGHTNESS in kwargs:
            families.append("light_brightness")
        if not families or not self._device.state.light_on:
            families.append("light_power")
        for family in families:
            self._device.check_gate(family)
        self._stream.manual_override()
        if ATTR_EFFECT in kwargs:
            await self._device.light_preset(_LABEL_TO_PRESET.get(kwargs[ATTR_EFFECT], kwargs[ATTR_EFFECT]))
        elif ATTR_RGB_COLOR in kwargs:
            await self._device.light_solo(tuple(kwargs[ATTR_RGB_COLOR]))  # also switches the lights on
        elif not self._device.state.light_on:
            await self._device.light_on_off(True)
        if ATTR_BRIGHTNESS in kwargs:
            await self._device.set_light_brightness(kwargs[ATTR_BRIGHTNESS])

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._commanding = True
        try:
            self._device.check_gate("light_power")
            self._stream.manual_override()
            await self._device.light_on_off(False)
        finally:
            self._handle_update()
            self._commanding = False
