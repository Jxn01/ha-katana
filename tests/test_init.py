"""Setup, unload, not-ready, the firmware repair issue."""

import asyncio
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sb_katana.const import DOMAIN

from .fakes import FAKE_ADDRESS, FakeKatana


async def test_setup_and_unload(hass, entry, fake):
    assert entry.state is ConfigEntryState.LOADED
    assert fake.connected
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not fake.connected


async def test_a_sleeping_soundbar_loads_anyway_and_comes_back(hass, mock_bluetooth, monkeypatch):
    # In standby the soundbar's BLE is off. Setup must not hand retrying to HA (every ~80 s forever, each an
    # active scan): it loads with the device unavailable, and the device's own loop reconnects.
    from custom_components.sb_katana import device as dev

    monkeypatch.setattr(dev, "RECONNECT_BACKOFF", (0.05,))
    monkeypatch.setattr(dev, "RECONNECT_IDLE", 0.05)
    fake = FakeKatana()
    fake.fail_connect = True
    config_entry = MockConfigEntry(domain=DOMAIN, unique_id=FAKE_ADDRESS, data={"address": FAKE_ADDRESS})
    config_entry.add_to_hass(hass)
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert config_entry.state is ConfigEntryState.LOADED
        device = config_entry.runtime_data.device
        assert not device.available
        assert not device.firmware_ok  # writes stay locked until the firmware is read on a real connection
        fake.fail_connect = False  # it wakes up
        for _ in range(100):
            await asyncio.sleep(0.02)
            if device.available:
                break
        assert device.available and device.firmware_ok
        assert await hass.config_entries.async_unload(config_entry.entry_id)


async def test_untested_firmware_raises_a_repair_issue(hass, mock_bluetooth):
    fake = FakeKatana(firmware="1.30.260813.1100")
    config_entry = MockConfigEntry(domain=DOMAIN, unique_id=FAKE_ADDRESS, data={"address": FAKE_ADDRESS})
    config_entry.add_to_hass(hass)
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"untested_firmware_{config_entry.entry_id}")
    assert issue is not None and issue.translation_placeholders["found"] == "1.30.260813.1100"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_hold_connection_off_survives_a_restart(hass, mock_bluetooth):
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import mock_restore_cache

    mock_restore_cache(hass, [State("switch.sound_blaster_katana_v2x_hold_connection", "off")])
    fake = FakeKatana()
    config_entry = MockConfigEntry(domain=DOMAIN, unique_id=FAKE_ADDRESS, data={"address": FAKE_ADDRESS})
    config_entry.add_to_hass(hass)
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.runtime_data.device.hold_connection is False
    assert not fake.connected
    await hass.config_entries.async_unload(config_entry.entry_id)
