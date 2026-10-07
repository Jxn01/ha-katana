"""Whether the PC is streaming screen colours right now. Changes at the start and the hand-over only."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from .entity import KatanaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ScreenSyncReceiving(entry)])


class ScreenSyncReceiving(KatanaEntity, BinarySensorEntity):
    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "screen_sync_receiving")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        # Only the stream drives this one; device updates (every colour echo) are irrelevant.
        self.async_on_remove(self._stream.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._stream.receiving
