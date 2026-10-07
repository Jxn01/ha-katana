"""Every entity's state after the read-back, and what each write sends."""

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.sb_katana import protocol as p
from custom_components.sb_katana.const import DOMAIN

from .fakes import FAKE_ADDRESS


def eid(hass, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{FAKE_ADDRESS}_{key}")
    assert entity_id, (platform, key)
    return entity_id


def state(hass, platform: str, key: str):
    return hass.states.get(eid(hass, platform, key))


async def call(hass, domain: str, service: str, entity_id: str, **data):
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)


async def test_states_after_read_back(hass, entry):
    mp = state(hass, "media_player", "soundbar")
    assert mp.state == "on"
    assert mp.attributes["volume_level"] == pytest.approx(0.24)
    assert mp.attributes["is_volume_muted"] is False
    assert mp.attributes["source"] == "USB Audio"
    assert mp.attributes["source_list"] == ["TV", "USB Audio", "Optical", "Aux", "Bluetooth"]
    assert mp.attributes["sound_mode"] == "Music."
    assert mp.attributes["sound_mode_list"] == ["Music.", "Gaming.", "Voice.", "Effects Off"]
    assert state(hass, "select", "output").state == "Speakers"
    assert state(hass, "select", "decoder").state == "Full"
    assert state(hass, "select", "eq_preset").state == "Music"
    assert state(hass, "select", "smart_volume_mode").state == "Mode 1"
    assert state(hass, "number", "surround_level").state == "100"
    assert state(hass, "number", "crystalizer_level").state == "50"
    assert state(hass, "number", "dialog_plus_level").state == "0"
    assert float(state(hass, "number", "line_in_level").state) == 36
    assert float(state(hass, "number", "spdif_in_level").state) == 100
    assert float(state(hass, "number", "microphone_level").state) == 70
    assert float(state(hass, "number", "subwoofer").state) == 3
    assert state(hass, "switch", "scout_mode").state == "off"
    assert state(hass, "switch", "auto_switch_tv").state == "on"
    assert state(hass, "switch", "equalizer").state == "on"
    assert state(hass, "switch", "surround").state == "on"
    assert state(hass, "switch", "smart_volume").state == "off"
    assert state(hass, "switch", "mic_smart_volume").state == "on"
    assert state(hass, "switch", "mic_equalizer").state == "off"
    assert state(hass, "switch", "mic_focus").state == "on"
    assert state(hass, "switch", "screen_sync").state == "on"
    assert state(hass, "switch", "hold_connection").state == "on"
    assert state(hass, "sensor", "firmware").state == "1.3.230619.1820"
    assert state(hass, "binary_sensor", "screen_sync_receiving").state == "off"
    light = state(hass, "light", "lighting")
    assert light.state == "on"
    assert light.attributes["rgb_color"] == (0, 0, 0)
    assert "Wave Rainbow" in light.attributes["effect_list"]


async def test_unconfirmed_write_is_refused(hass, entry, fake):
    before = len(fake.writes)
    with pytest.raises(HomeAssistantError, match="not been confirmed"):
        await call(hass, "media_player", "volume_set", eid(hass, "media_player", "soundbar"), volume_level=0.5)
    assert fake.writes_since(before) == []


async def test_light_turn_on_colour_sends_solo_and_stops_screen_sync(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), rgb_color=(0, 0, 255))
    assert fake.writes_since(before)[:4] == ["5a3a022501", "5a3a03370001", "5a3a03290003", "5a3a082b000101ffff0000"]
    assert state(hass, "switch", "screen_sync").state == "off"
    assert state(hass, "light", "lighting").attributes["rgb_color"] == (0, 0, 255)


async def test_light_brightness_scales_the_colour(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), rgb_color=(255, 0, 0), brightness=128)
    assert fake.writes_since(before)[3] == p.solo_colour((128, 0, 0)).frame.hex()
    light = state(hass, "light", "lighting")
    assert light.attributes["rgb_color"] == (255, 0, 0) and light.attributes["brightness"] == 128


async def test_light_turn_off(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_off", eid(hass, "light", "lighting"))
    assert fake.writes_since(before)[0] == "5a3a022500"
    assert state(hass, "light", "lighting").state == "off"


async def test_light_preset_needs_confirmation(hass, entry):
    with pytest.raises(HomeAssistantError, match="not been confirmed"):
        await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), effect="Aurora")


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_every_write_entity_sends_the_captured_bytes(hass, entry, fake):
    from custom_components.sb_katana import captured

    cases = [
        ("media_player", "volume_set", "soundbar", {"volume_level": 0.26}, "5a230500000d0000"),
        ("media_player", "volume_mute", "soundbar", {"is_volume_muted": True}, "5a2403000001"),
        ("media_player", "select_source", "soundbar", {"source": "Optical"}, "5a9c03000700"),
        ("media_player", "select_sound_mode", "soundbar", {"sound_mode": "Effects Off"}, "5aa7020004"),
        ("select", "select_option", "output", {"option": "Headphones"}, "5a2c050024000000"),
        ("switch", "turn_on", "scout_mode", {}, "5a26050702000100"),
        ("switch", "turn_off", "auto_switch_tv", {}, "5a67020c00"),
        ("number", "set_value", "subwoofer", {"value": -1}, "5a40040401ffff"),
        ("number", "set_value", "microphone_level", {"value": 70}, "5a23050005230000"),
        ("switch", "turn_off", "mic_smart_volume", {}, "5a120701952c00000000"),
        ("light", "turn_on", "lighting", {"effect": "Wave Rainbow"}, captured.LIGHTING_PRESETS["Wave Rainbow"][0]),
    ]
    for domain, service, key, data, first_frame in cases:
        platform = domain
        before = len(fake.writes)
        await call(hass, domain, service, eid(hass, platform, key), **data)
        assert fake.writes_since(before)[0] == first_frame, (domain, service, key)


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_store_writes_follow_the_output(hass, entry, fake):
    await call(hass, "select", "select_option", eid(hass, "select", "output"), option="Headphones")
    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "decoder"), option="Night")
    assert fake.writes_since(before)[0] == p.store_write(2, [(p.KEY_DECODER, 3.0)]).frame.hex()
    await call(hass, "number", "set_value", eid(hass, "number", "surround_level"), value=40)
    assert p.store_write(2, [(p.KEY_SURROUND_LEVEL, 0.4)]).frame.hex() in fake.writes
    # The Headphones side reads its own values (fake: surround 50).
    await hass.async_block_till_done()


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_eq_preset_replays_the_capture(hass, entry, fake):
    from custom_components.sb_katana import captured

    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "eq_preset"), option="Footsteps Enhancer")
    sent = fake.writes_since(before)
    seq = list(captured.EQ_PRESETS["Footsteps Enhanc"])
    assert sent[: len(seq)] == seq


async def test_unavailable_after_disconnect(hass, entry, fake, monkeypatch):
    from custom_components.sb_katana import device as dev

    monkeypatch.setattr(dev, "RECONNECT_BACKOFF", (3600,))
    fake.drop()
    await hass.async_block_till_done()
    assert state(hass, "media_player", "soundbar").state == "unavailable"
    assert state(hass, "switch", "screen_sync").state == "on"  # integration state stays available


async def test_hold_connection_off_releases_the_link(hass, entry, fake):
    await call(hass, "switch", "turn_off", eid(hass, "switch", "hold_connection"))
    assert not fake.connected
    assert state(hass, "light", "lighting").state == "unavailable"
    await call(hass, "switch", "turn_on", eid(hass, "switch", "hold_connection"))
    assert fake.connected
    assert state(hass, "light", "lighting").state == "on"


async def test_diagnostics_redact_identifiers(hass, entry):
    from custom_components.sb_katana.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(diag)
    assert FAKE_ADDRESS not in text
    assert "Q8MF0000000000000W" not in text
    assert diag["state"]["firmware"] == "1.3.230619.1820"
    assert diag["families"]["light_solo"]["confirmed"] is True
