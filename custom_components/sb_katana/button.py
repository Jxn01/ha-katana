"""Diagnostic button: read every value back from the soundbar (reads only)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from .entity import KatanaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([KatanaRefreshButton(entry)])


class KatanaRefreshButton(KatanaEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "reread_state")

    async def async_press(self) -> None:
        await self._device.refresh(full=True)
