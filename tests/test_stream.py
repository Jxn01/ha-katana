"""Screen sync: rate limit, newest-wins, dedup, the hand-over, manual override,
the HTTP endpoint -- and the recorder budget: a whole stream is two state changes."""

import asyncio

import pytest
from homeassistant.const import EVENT_CALL_SERVICE, EVENT_STATE_CHANGED
from homeassistant.helpers import entity_registry as er

from custom_components.sb_katana import protocol as p
from custom_components.sb_katana.const import DOMAIN

from .fakes import FAKE_ADDRESS


def stream_writes(fake, since: int = 0) -> list[str]:
    return [h for h in fake.writes_since(since) if h.startswith("5a3a082b")]


@pytest.fixture
def stream(entry):
    s = entry.runtime_data.stream
    s.timeout_s = 0.3
    return s


async def test_first_frame_prepares_then_colours(hass, entry, fake, stream):
    before = len(fake.writes)
    assert stream.handle_frame((10, 20, 30)) is True
    await asyncio.sleep(0.05)
    assert fake.writes_since(before)[:4] == [
        "5a3a022501",
        "5a3a03370001",
        "5a3a03290003",
        p.solo_colour((10, 20, 30)).frame.hex(),
    ]
    assert stream.receiving


async def test_burst_is_coalesced_newest_wins(hass, entry, fake, stream):
    before = len(fake.writes)
    for i in range(100):
        stream.handle_frame((i, 0, 0))
    await asyncio.sleep(0.2)
    sent = stream_writes(fake, before)
    assert len(sent) == 2  # the first frame at once, then the newest after 1/rate
    assert sent[-1] == p.solo_colour((99, 0, 0)).frame.hex()


async def test_rate_limit_over_one_second(hass, entry, fake, stream):
    before = len(fake.writes)
    for i in range(100):
        stream.handle_frame((i, i, 0))
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)
    assert 8 <= len(stream_writes(fake, before)) <= 12  # 10 Hz


async def test_repeated_colour_is_not_resent(hass, entry, fake, stream):
    before = len(fake.writes)
    for _ in range(5):
        stream.handle_frame((1, 2, 3))
        await asyncio.sleep(0.12)
    assert len(stream_writes(fake, before)) == 1


async def test_handover_turns_lights_off_once_and_keeps_screen_sync(hass, entry, fake, stream):
    stream.handle_frame((5, 5, 5))
    await asyncio.sleep(0.1)
    before = len(fake.writes)
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()
    assert fake.writes_since(before).count("5a3a022500") == 1
    assert stream.screen_sync is True and stream.receiving is False
    # The next frame resumes, starting with the prepare sequence again.
    before = len(fake.writes)
    stream.handle_frame((6, 6, 6))
    await asyncio.sleep(0.05)
    assert fake.writes_since(before)[0] == "5a3a022501"


async def test_frames_ignored_while_screen_sync_off(hass, entry, fake, stream):
    stream.set_screen_sync(False)
    before = len(fake.writes)
    assert stream.handle_frame((9, 9, 9)) is False
    await asyncio.sleep(0.05)
    assert fake.writes_since(before) == []


async def test_switching_screen_sync_off_does_not_power_off(hass, entry, fake, stream):
    stream.handle_frame((7, 7, 7))
    await asyncio.sleep(0.05)
    before = len(fake.writes)
    stream.set_screen_sync(False)
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()
    assert "5a3a022500" not in fake.writes_since(before)


async def test_stream_frame_validation(hass, entry, hass_client):
    client = await hass_client()
    for body in ({"rgb": [300, 0, 0]}, {"rgb": [1, 2]}, {}, {"rgb": "red"}):
        resp = await client.post("/api/sb_katana/stream", json=body)
        assert resp.status == 400, body
    resp = await client.post("/api/sb_katana/stream", data=b"not json")
    assert resp.status == 400


async def test_http_endpoint_accepts_and_fires_no_service_event(hass, entry, fake, hass_client):
    events = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, lambda e: events.append(e))
    client = await hass_client()
    resp = await client.post("/api/sb_katana/stream", json={"rgb": [1, 2, 3]})
    assert resp.status == 200 and (await resp.json()) == {"accepted": True}
    await asyncio.sleep(0.05)
    assert stream_writes(fake) == [p.solo_colour((1, 2, 3)).frame.hex()]
    assert events == []


async def test_http_endpoint_requires_auth(hass, entry, hass_client_no_auth):
    client = await hass_client_no_auth()
    resp = await client.post("/api/sb_katana/stream", json={"rgb": [1, 2, 3]})
    assert resp.status == 401


async def test_service_still_works(hass, entry, fake):
    await hass.services.async_call(DOMAIN, "stream_frame", {"rgb": [4, 5, 6]}, blocking=True)
    await asyncio.sleep(0.05)
    assert stream_writes(fake)[-1] == p.solo_colour((4, 5, 6)).frame.hex()


async def test_hundred_frames_cost_one_state_change(hass, entry, fake, stream, hass_client):
    """The recorder budget: a stream changes the receiving sensor once and the light not at all."""
    registry = er.async_get(hass)
    light = registry.async_get_entity_id("light", DOMAIN, f"{FAKE_ADDRESS}_lighting")
    receiving = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{FAKE_ADDRESS}_screen_sync_receiving")
    changes: list[str] = []
    hass.bus.async_listen(EVENT_STATE_CHANGED, lambda e: changes.append(e.data["entity_id"]))
    stream.timeout_s = 30
    client = await hass_client()
    for i in range(100):
        # The fake soundbar echoes each colour back, as the real one does.
        resp = await client.post("/api/sb_katana/stream", json={"rgb": [i, 255 - i, 0]})
        assert resp.status == 200
        fake.notify("5a3a202c000101" + bytes([0xFF, 0, 255 - i, i]).hex() + "ff000000" * 6)
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()
    assert changes.count(receiving) == 1
    assert changes.count(light) == 0
    assert len(stream_writes(fake)) >= 5


async def test_external_colour_changes_are_throttled(hass, entry, fake, monkeypatch):
    """ambience-rgb over USB (or the remote) changing colours must not flood the recorder."""
    from custom_components.sb_katana import light as light_mod

    monkeypatch.setattr(light_mod, "EXTERNAL_COLOUR_INTERVAL", 0.5)
    registry = er.async_get(hass)
    light = registry.async_get_entity_id("light", DOMAIN, f"{FAKE_ADDRESS}_lighting")
    changes: list = []
    hass.bus.async_listen(EVENT_STATE_CHANGED, lambda e: changes.append(e) if e.data["entity_id"] == light else None)
    for i in range(40):
        fake.notify("5a3a202c000101" + bytes([0xFF, 0, 0, i + 1]).hex() + "ff000000" * 6)
        await asyncio.sleep(0.025)  # 40 changes in 1 s
    await asyncio.sleep(0.6)
    await hass.async_block_till_done()
    # 40 changes over ~1.6 s with a 0.5 s interval: at most one publish per interval, plus the first.
    assert 1 <= len(changes) <= 4
    # The newest colour is what is eventually shown.
    assert hass.states.get(light).attributes["brightness"] == 40


async def test_on_off_from_outside_is_published_at_once(hass, entry, fake):
    registry = er.async_get(hass)
    light = registry.async_get_entity_id("light", DOMAIN, f"{FAKE_ADDRESS}_lighting")
    fake.notify("5a3a022600")
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "off"


# --- review findings (2026-10-07) -----------------------------------------------------------


async def test_failed_prepare_is_sent_again_with_the_next_frame(hass, entry, fake, stream, monkeypatch):
    from custom_components.sb_katana import device as dev

    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    fake.silent.add("5a3a022501")  # the prepare's first frame is lost once
    stream.handle_frame((10, 10, 10))
    await asyncio.sleep(0.2)
    fake.silent.clear()
    before = len(fake.writes)
    stream.handle_frame((10, 10, 10))  # the same colour: a keepalive
    await asyncio.sleep(0.2)
    assert fake.writes_since(before)[:4] == [
        "5a3a022501",
        "5a3a03370001",
        "5a3a03290003",
        p.solo_colour((10, 10, 10)).frame.hex(),
    ]


async def test_reconnect_while_receiving_prepares_again(hass, entry, fake, stream):
    stream.handle_frame((20, 20, 20))
    await asyncio.sleep(0.05)
    device = entry.runtime_data.device
    device.connect_count += 1  # what a successful reconnect does
    before = len(fake.writes)
    stream.handle_frame((21, 21, 21))
    await asyncio.sleep(0.15)
    assert fake.writes_since(before)[0] == "5a3a022501"


async def test_handover_option_cannot_undercut_the_keepalive(hass, entry):
    from homeassistant.data_entry_flow import FlowResultType

    result = await hass.config_entries.options.async_init(entry.entry_id)
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"allow_unconfirmed": False, "stream_rate_hz": 10, "stream_timeout_s": 4}
        )
    assert result["type"] is FlowResultType.FORM
