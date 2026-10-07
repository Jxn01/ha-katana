"""Shared fixtures. HA's own test harness is loaded by pytest-homeassistant-custom-component."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/sb_katana in every test."""
    return
