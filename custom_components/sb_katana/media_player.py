"""Volume, mute, input source and sound mode, as one media player."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from . import protocol as p
from .entity import KatanaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([KatanaMediaPlayer(entry)])


class KatanaMediaPlayer(KatanaEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "soundbar")
        self._attr_translation_key = None

    @property
    def state(self) -> MediaPlayerState | None:
        return MediaPlayerState.ON if self._device.available else None

    @property
    def volume_level(self) -> float | None:
        level = self._device.state.levels.get(p.CH_SPEAKERS)
        return None if level is None else level / p.LEVEL_MAX

    @property
    def volume_step(self) -> float:
        return 1 / p.LEVEL_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        return self._device.state.mutes.get(p.CH_SPEAKERS)

    @property
    def source_list(self) -> list[str]:
        ids = self._device.state.inputs or list(p.INPUT_LABELS)
        return [p.INPUT_LABELS[i] for i in ids if i in p.INPUT_LABELS]

    @property
    def source(self) -> str | None:
        return p.INPUT_LABELS.get(self._device.state.input)

    @property
    def sound_mode_list(self) -> list[str]:
        return self._device.state.mode_options()

    @property
    def sound_mode(self) -> str | None:
        return self._device.state.mode_name

    async def async_set_volume_level(self, volume: float) -> None:
        await self._device.set_volume(round(volume * p.LEVEL_MAX))

    def _current_level(self) -> int:
        level = self._device.state.levels.get(p.CH_SPEAKERS)
        if level is None:
            raise HomeAssistantError("the current volume is unknown; re-read state first")
        return level

    async def async_volume_up(self) -> None:
        await self._device.set_volume(self._current_level() + 1)

    async def async_volume_down(self) -> None:
        await self._device.set_volume(self._current_level() - 1)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._device.set_mute(mute)

    async def async_select_source(self, source: str) -> None:
        ids = {label: i for i, label in p.INPUT_LABELS.items()}
        if source not in ids:
            raise ServiceValidationError(f"unknown source {source!r}")
        await self._device.set_input(ids[source])

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        modes = self._device.state.stored_modes()
        if sound_mode == self._device.state.mode_name and sound_mode not in modes:
            return  # the live settings ("Onboard") are already active
        if sound_mode not in modes:
            raise ServiceValidationError(f"unknown sound mode {sound_mode!r}")
        await self._device.select_mode(modes[sound_mode])
