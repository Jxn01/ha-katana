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
    assert state(hass, "select", "smart_volume_mode").state == "Manual"
    assert state(hass, "select", "eq_preset").attributes["options"] == [
        "Gaming",
        "Music",
        "Movies",
        "Footsteps Enhancer",
        "Flat",
    ]
    assert state(hass, "select", "mic_priority").state == "Auto"
    assert state(hass, "select", "mic_eq_preset").state == "Off"
    assert state(hass, "select", "auto_standby").state == "28 hours"
    assert state(hass, "select", "display").state == "Bright"
    assert state(hass, "switch", "energy_saving").state == "on"
    assert state(hass, "switch", "cec_link").state == "on"
    assert float(state(hass, "number", "eq_band_3").state) == -1.0
    assert float(state(hass, "number", "eq_band_9").state) == 2.0
    assert float(state(hass, "number", "mic_focus_angle").state) == 30.0
    assert state(hass, "light", "lighting").attributes["brightness"] == 255
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
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("number", DOMAIN, f"{FAKE_ADDRESS}_headphones_level")
    registry.async_update_entity(entity_id, disabled_by=None)
    from unittest.mock import patch

    with patch("custom_components.sb_katana._make_transport", return_value=fake):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "24.0"
    before = len(fake.writes)
    with pytest.raises(HomeAssistantError, match="not been confirmed"):
        await call(hass, "number", "set_value", entity_id, value=20)
    assert fake.writes_since(before) == []


async def test_light_turn_on_colour_sends_solo_and_stops_screen_sync(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), rgb_color=(0, 0, 255))
    assert fake.writes_since(before)[:4] == ["5a3a022501", "5a3a03370001", "5a3a03290003", "5a3a082b000101ffff0000"]
    assert state(hass, "switch", "screen_sync").state == "off"
    assert state(hass, "light", "lighting").attributes["rgb_color"] == (0, 0, 255)


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_light_brightness_is_the_soundbars_own(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), rgb_color=(255, 0, 0), brightness=128)
    sent = fake.writes_since(before)
    assert p.solo_colour((255, 0, 0)).frame.hex() in sent  # the colour itself, unscaled
    assert "5a3a022780" in sent  # Global Brightness 128
    light = state(hass, "light", "lighting")
    assert light.attributes["rgb_color"] == (255, 0, 0) and light.attributes["brightness"] == 128


async def test_light_brightness_is_gated_until_confirmed(hass, entry, fake):
    before = len(fake.writes)
    with pytest.raises(HomeAssistantError, match="not been confirmed"):
        await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), brightness=128)
    assert fake.writes_since(before) == []
    assert state(hass, "switch", "screen_sync").state == "on"


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_third_capture_entities_send_the_captured_bytes(hass, entry, fake):
    cases = [
        ("select", "select_option", "mic_priority", {"option": "Headset Microphone"}, "5a2d0405020100"),
        ("select", "select_option", "auto_standby", {"option": "8 hours"}, "5a390a07110f000000d1010000"),
        ("select", "select_option", "display", {"option": "Bright"}, "5a390407120700"),
        ("switch", "turn_off", "energy_saving", {}, "5a3903001100"),
        ("switch", "turn_on", "cec_link", {}, "5a3903001801"),
        ("number", "set_value", "mic_focus_angle", {"value": 180}, "5a12070195080000" + "3443"),
        (
            "select",
            "select_option",
            "smart_volume_mode",
            {"option": "Night"},
            p.store_write(0, [(p.KEY_SMART_VOLUME_MODE, 2.0)]).frame.hex(),
        ),
    ]
    for domain, service, key, data, first_frame in cases:
        before = len(fake.writes)
        await call(hass, domain, service, eid(hass, domain, key), **data)
        assert fake.writes_since(before)[0] == first_frame, key


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_eq_band_sends_all_ten_bands_after_the_custom_mark(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "number", "set_value", eid(hass, "number", "eq_band_4"), value=-6.0)
    sent = fake.writes_since(before)
    expected = p.eq_band_write(0, [0.0, 0.0, -1.0, -6.0, -1.0, 1.5, 1.5, 0.0, 2.0, 2.0])
    assert sent[:2] == [c.frame.hex() for c in expected]
    assert float(state(hass, "number", "eq_band_4").state) == -6.0


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_mic_eq_preset_switches_it_on_then_writes_the_bands(hass, entry, fake):
    from custom_components.sb_katana import captured

    name = next(iter(captured.MIC_EQ_PRESETS))
    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "mic_eq_preset"), option=name)
    sent = fake.writes_since(before)
    assert sent[:2] == [p.dsp_write(p.DSP_MIC_EQ, 1.0).frame.hex(), captured.MIC_EQ_PRESETS[name]]


async def test_light_turn_off(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "light", "turn_off", eid(hass, "light", "lighting"))
    assert fake.writes_since(before)[0] == "5a3a022500"
    assert state(hass, "light", "lighting").state == "off"


async def test_sound_mode_is_confirmed(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "sound_mode"), option="Gaming.")
    assert fake.writes_since(before)[0] == "5aa7020002"


async def test_input_and_sound_mode_are_selects_too(hass, entry):
    source = state(hass, "select", "input")
    assert source.state == "USB Audio"
    assert source.attributes["options"] == ["TV", "USB Audio", "Optical", "Aux", "Bluetooth"]
    mode = state(hass, "select", "sound_mode")
    assert mode.state == "Music."
    assert mode.attributes["options"] == ["Music.", "Gaming.", "Voice.", "Effects Off"]


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_input_and_sound_mode_selects_send_the_captured_bytes(hass, entry, fake):
    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "input"), option="Optical")
    assert fake.writes_since(before)[0] == "5a9c03000700"
    assert state(hass, "select", "input").state == "Optical"
    before = len(fake.writes)
    await call(hass, "select", "select_option", eid(hass, "select", "sound_mode"), option="Gaming.")
    assert fake.writes_since(before)[0] == "5aa7020002"
    assert state(hass, "select", "sound_mode").state == "Gaming."
    assert state(hass, "media_player", "soundbar").attributes["sound_mode"] == "Gaming."


async def test_headphones_level_is_disabled_by_default(hass, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("number", DOMAIN, f"{FAKE_ADDRESS}_headphones_level")
    assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION


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


# --- review findings (2026-10-07) -----------------------------------------------------------


async def test_a_refused_light_command_leaves_screen_sync_alone(hass, entry):
    entry.runtime_data.device.state.firmware = "1.30.260813.1100"  # the firmware gate refuses everything
    with pytest.raises(HomeAssistantError, match="firmware"):
        await call(hass, "light", "turn_on", eid(hass, "light", "lighting"), effect="Aurora")
    assert state(hass, "switch", "screen_sync").state == "on"


@pytest.mark.parametrize("allow_unconfirmed", [True])
async def test_volume_step_refuses_an_unknown_level(hass, entry, fake):
    entry.runtime_data.device.state.levels.pop(p.CH_SPEAKERS)
    before = len(fake.writes)
    with pytest.raises(HomeAssistantError, match="unknown"):
        await call(hass, "media_player", "volume_up", eid(hass, "media_player", "soundbar"))
    assert fake.writes_since(before) == []


async def test_firmware_issue_follows_a_reconnect(hass, entry, fake):
    from homeassistant.helpers import issue_registry as ir

    device = entry.runtime_data.device
    issue_id = f"untested_firmware_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    fake.firmware = "1.30.260813.1100"
    fake.replies = fake._build_replies()
    await device.refresh(full=True)  # what a reconnect does
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert not device.firmware_ok


async def test_reread_button_does_not_blank_the_entities(hass, entry):
    from homeassistant.const import EVENT_STATE_CHANGED

    changes: list[str] = []
    hass.bus.async_listen(
        EVENT_STATE_CHANGED, lambda e: changes.append(e.data["new_state"].state) if e.data["new_state"] else None
    )
    await call(hass, "button", "press", eid(hass, "button", "reread_state"))
    await hass.async_block_till_done()
    assert "unavailable" not in changes


def _live_name_frame(name: str) -> str:
    data = name.encode("utf-16-le")
    payload = bytes([0x06, 0x00, 0x00, 0x10, 0x10, 0x00]) + data + bytes(32 - len(data))
    return (bytes([0x5A, 0xA7, len(payload)]) + payload).hex()


async def test_an_edited_mode_shows_onboard_and_picking_a_mode_restores(hass, entry, fake):
    """Changed live, the soundbar reports active slot 0 and renames its live copy "Onboard"."""
    fake.notify(_live_name_frame("Onboard"))
    fake.notify("5aa7020100")  # a7:01 -> slot 0
    await hass.async_block_till_done()
    mode = state(hass, "select", "sound_mode")
    assert mode.state == "Onboard"
    assert mode.attributes["options"] == ["Music.", "Gaming.", "Voice.", "Effects Off", "Onboard"]
    assert mode.attributes["modified"] is True
    assert state(hass, "media_player", "soundbar").attributes["sound_mode"] == "Onboard"
    before = len(fake.writes)
    entry.runtime_data.device.allow_unconfirmed = True
    await call(hass, "select", "select_option", eid(hass, "select", "sound_mode"), option="Onboard")
    assert fake.writes_since(before) == []  # already active: nothing sent
    fake.notify(_live_name_frame("Music."))
    fake.notify("5aa7020101")  # a stored mode picked again
    await hass.async_block_till_done()
    mode = state(hass, "select", "sound_mode")
    assert mode.state == "Music." and mode.attributes["modified"] is False
    assert "Onboard" not in mode.attributes["options"]
