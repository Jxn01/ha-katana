"""Config flow: Bluetooth discovery of "Control for MF8400", plus options."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    CONF_ALLOW_UNCONFIRMED,
    CONF_STREAM_RATE,
    CONF_STREAM_TIMEOUT,
    DEFAULT_NAME,
    DEFAULT_STREAM_RATE,
    DEFAULT_STREAM_TIMEOUT,
    DOMAIN,
    LOCAL_NAME_PREFIX,
    SERVICE_UUID,
    STREAM_RATE_RANGE,
    STREAM_TIMEOUT_RANGE,
)


def _is_katana(info: BluetoothServiceInfoBleak) -> bool:
    # The command service UUID is in the advertisement itself; the name (with trailing
    # NULs, so matched by prefix) only arrives with active scanning.
    return SERVICE_UUID in info.service_uuids or (info.name or "").startswith(LOCAL_NAME_PREFIX)


class KatanaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._found: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        if not _is_katana(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": DEFAULT_NAME}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._discovery is not None
        if user_input is not None:
            return self.async_create_entry(title=DEFAULT_NAME, data={CONF_ADDRESS: self._discovery.address})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": DEFAULT_NAME, "address": self._discovery.address},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=DEFAULT_NAME, data={CONF_ADDRESS: address})

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if _is_katana(info) and info.address not in configured:
                self._found[info.address] = info
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In({a: f"{DEFAULT_NAME} ({a})" for a in self._found})}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KatanaOptionsFlow()


class KatanaOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ALLOW_UNCONFIRMED, default=options.get(CONF_ALLOW_UNCONFIRMED, False)): bool,
                    vol.Required(CONF_STREAM_RATE, default=options.get(CONF_STREAM_RATE, DEFAULT_STREAM_RATE)): vol.All(
                        vol.Coerce(int), vol.Range(*STREAM_RATE_RANGE)
                    ),
                    vol.Required(
                        CONF_STREAM_TIMEOUT, default=options.get(CONF_STREAM_TIMEOUT, DEFAULT_STREAM_TIMEOUT)
                    ): vol.All(vol.Coerce(int), vol.Range(*STREAM_TIMEOUT_RANGE)),
                }
            ),
        )
