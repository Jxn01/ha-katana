"""Bluetooth discovery, the user step, and options."""

from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResultType

from custom_components.sb_katana.const import (
    CONF_ALLOW_UNCONFIRMED,
    CONF_STREAM_RATE,
    CONF_STREAM_TIMEOUT,
    DOMAIN,
)

from .fakes import FAKE_ADDRESS


def service_info(
    name: str = "Control for MF8400\x00\x00\x00",
    address: str = FAKE_ADDRESS,
    service_uuids: list[str] | None = None,
) -> BluetoothServiceInfoBleak:
    service_uuids = service_uuids or []
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-58,
        manufacturer_data={0x4102: b""},
        service_data={},
        service_uuids=service_uuids,
        source="local",
        device=BLEDevice(address, name, None),
        advertisement=AdvertisementData(
            local_name=name,
            manufacturer_data={0x4102: b""},
            service_data={},
            service_uuids=service_uuids,
            tx_power=None,
            rssi=-58,
            platform_data=(),
        ),
        connectable=True,
        time=0,
        tx_power=None,
    )


async def test_bluetooth_discovery_confirm(hass, mock_bluetooth):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bluetooth_confirm"
    with patch("custom_components.sb_katana.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"address": FAKE_ADDRESS}
    assert result["result"].unique_id == FAKE_ADDRESS


async def test_passive_scan_discovery_by_service_uuid(hass, mock_bluetooth):
    """HA's adapter scans passively: no name, just the address and the command service UUID."""
    info = service_info(name=FAKE_ADDRESS, service_uuids=["9e9daaea-3a10-4fe8-b69f-7397aff77886"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bluetooth_confirm"


async def test_bluetooth_discovery_rejects_other_devices(hass, mock_bluetooth):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=service_info(name="SOUND BLASTER KATANA V2X")
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_user_step_lists_discovered(hass, mock_bluetooth):
    with patch("custom_components.sb_katana.config_flow.async_discovered_service_info", return_value=[service_info()]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    with patch("custom_components.sb_katana.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": FAKE_ADDRESS})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_nothing_found(hass, mock_bluetooth):
    with patch("custom_components.sb_katana.config_flow.async_discovered_service_info", return_value=[]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_devices_found"


async def test_already_configured(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_options_flow(hass, entry, fake):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ALLOW_UNCONFIRMED: True, CONF_STREAM_RATE: 5, CONF_STREAM_TIMEOUT: 20}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ALLOW_UNCONFIRMED: True, CONF_STREAM_RATE: 5, CONF_STREAM_TIMEOUT: 20}
    assert entry.runtime_data.device.allow_unconfirmed is True
    assert entry.runtime_data.stream.rate_hz == 5
