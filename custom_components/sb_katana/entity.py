"""Base entity: device info, availability and push updates from KatanaDevice."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import KatanaConfigEntry
from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL, MODEL_ID


class KatanaEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: KatanaConfigEntry, key: str) -> None:
        runtime = entry.runtime_data
        self._entry = entry
        self._device = runtime.device
        self._stream = runtime.stream
        self._attr_unique_id = f"{runtime.address}_{key}"
        self._attr_translation_key = key
        state = runtime.device.state
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.address)},
            connections={(CONNECTION_BLUETOOTH, runtime.address)},
            name=DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
            model_id=MODEL_ID,
            sw_version=state.firmware,
            serial_number=state.serial,
        )

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()
