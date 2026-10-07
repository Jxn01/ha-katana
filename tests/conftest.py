"""Shared fixtures. HA's own test harness is loaded by pytest-homeassistant-custom-component."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sb_katana.const import CONF_ALLOW_UNCONFIRMED, DOMAIN

from .fakes import FAKE_ADDRESS, FakeKatana


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/sb_katana in every test."""
    return


@pytest.fixture
def fake() -> FakeKatana:
    return FakeKatana()


@pytest.fixture
def allow_unconfirmed() -> bool:
    return False


@pytest.fixture
async def entry(hass, mock_bluetooth, fake, allow_unconfirmed) -> MockConfigEntry:
    """The integration set up against the fake soundbar."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=FAKE_ADDRESS,
        data={"address": FAKE_ADDRESS},
        options={CONF_ALLOW_UNCONFIRMED: allow_unconfirmed},
        title="Sound Blaster Katana V2X",
    )
    config_entry.add_to_hass(hass)
    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
