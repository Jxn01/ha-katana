"""Setup, unload, not-ready, the firmware repair issue."""

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


async def test_setup_not_ready_when_unreachable(hass, mock_bluetooth):
    fake = FakeKatana()
    fake.fail_connect = True
    config_entry = MockConfigEntry(domain=DOMAIN, unique_id=FAKE_ADDRESS, data={"address": FAKE_ADDRESS})
    config_entry.add_to_hass(hass)
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


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
