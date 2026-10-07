"""Diagnostic sensor: firmware version (writes are refused on anything but the tested one)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KatanaConfigEntry
from .entity import KatanaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KatanaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([KatanaFirmwareSensor(entry)])


class KatanaFirmwareSensor(KatanaEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: KatanaConfigEntry) -> None:
        super().__init__(entry, "firmware")

    @property
    def native_value(self) -> str | None:
        return self._device.state.firmware
