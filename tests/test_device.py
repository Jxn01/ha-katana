"""KatanaDevice against the fake soundbar: read-back, the gate, ACK handling, ordering."""

import asyncio

import pytest

from custom_components.sb_katana import device as dev
from custom_components.sb_katana import protocol as p

from .fakes import FAKE_SERIAL, FakeKatana


async def started(**kwargs) -> tuple[FakeKatana, dev.KatanaDevice]:
    fake = FakeKatana(**{k: v for k, v in kwargs.items() if k == "firmware"})
    device = dev.KatanaDevice(fake, allow_unconfirmed=kwargs.get("allow_unconfirmed", False))
    await device.start()
    return fake, device


async def test_read_back_populates_every_field():
    _, device = await started()
    s = device.state
    assert s.firmware == p.TESTED_FIRMWARE and s.serial == FAKE_SERIAL
    assert (s.output, s.input, s.inputs) == ("speakers", 0x0C, [0x0A, 0x0C, 0x07, 0x04, 0x01])
    assert s.auto_switch is True and s.scout is False and s.sub == 3
    assert s.levels == {0: 12, 1: 12, 2: 18, 3: 50, 4: 18, 5: 35, 6: 50}
    assert s.mutes[2] is True and s.mutes[0] is False
    assert s.mode_active == 1 and s.mode_names[1] == "Music." and s.mode_names[9] == "Effects Off"
    assert s.store[0][p.KEY_CRYSTALIZER_LEVEL] == 0.5 and s.store[2][p.KEY_SURROUND_LEVEL] == 0.5
    assert s.store[0][p.KEY_EQ_SLOT] == 1
    assert s.eq_names == {0: "Music", 2: "Music"}
    assert s.dsp == {0x952C: 1.0, 0x9513: 0.0, 0x9506: 1.0}
    assert (s.light_on, s.light_mode, s.light_name, s.light_solid) == (True, 3, "Onboard", True)
    assert s.light_colours[1] == (4, 120, 3)
    assert device.available and device.firmware_ok
    await device.stop()


async def test_read_back_sends_only_reads():
    fake, device = await started()
    writes_with_acks = [h for h in fake.writes if h not in fake.replies]
    assert writes_with_acks == []
    await device.stop()


async def test_unconfirmed_family_is_refused_by_default():
    fake, device = await started()
    before = len(fake.writes)
    with pytest.raises(dev.KatanaUnconfirmedError):
        await device.set_level("headphones_level", p.CH_HEADPHONES, 10)
    assert fake.writes_since(before) == []
    await device.stop()


async def test_confirmed_families_match_the_owners_checklist():
    from custom_components.sb_katana.families import FAMILIES

    unconfirmed = {key for key, family in FAMILIES.items() if not family.confirmed}
    assert unconfirmed == {"headphones_level"}


async def test_unconfirmed_family_allowed_when_opted_in():
    fake, device = await started(allow_unconfirmed=True)
    before = len(fake.writes)
    await device.set_level("headphones_level", p.CH_HEADPHONES, 10)
    assert fake.writes_since(before) == ["5a230500010a0000"]
    assert device.state.levels[p.CH_HEADPHONES] == 10
    await device.stop()


async def test_volume_is_confirmed_and_needs_no_opt_in():
    fake, device = await started()
    before = len(fake.writes)
    await device.set_volume(15)
    assert fake.writes_since(before) == ["5a230500000f0000"]
    assert device.state.levels[0] == 15
    await device.stop()


async def test_confirmed_family_works_without_opt_in():
    fake, device = await started()
    before = len(fake.writes)
    await device.light_solo((0, 0, 255))
    assert fake.writes_since(before) == ["5a3a022501", "5a3a03370001", "5a3a03290003", "5a3a082b000101ffff0000"]
    assert device.state.light_colours[0] == (0, 0, 255)
    await device.stop()


async def test_untested_firmware_refuses_every_write():
    fake, device = await started(firmware="1.30.260813.1100", allow_unconfirmed=True)
    before = len(fake.writes)
    with pytest.raises(dev.KatanaCommandError, match="firmware"):
        await device.light_on_off(False)
    assert fake.writes_since(before) == []
    await device.stop()


async def test_rejected_write_raises_and_rereads():
    fake, device = await started(allow_unconfirmed=True)
    fake.status["5a230500001e0000"] = 0x81
    before = len(fake.writes)
    with pytest.raises(dev.KatanaCommandError, match="0x81"):
        await device.set_volume(30)
    assert fake.writes_since(before) == ["5a230500001e0000", p.level_query(0).frame.hex()]
    assert device.state.levels[0] == 12  # the re-read value, not the rejected one
    await device.stop()


async def test_unanswered_write_times_out(monkeypatch):
    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    fake, device = await started()
    fake.silent.add("5a3a022500")
    with pytest.raises(dev.KatanaCommandError, match="no answer"):
        await device.light_on_off(False)
    await device.stop()


async def test_manual_sequence_not_interleaved():
    fake, device = await started(allow_unconfirmed=True)
    before = len(fake.writes)
    preset = asyncio.create_task(device.light_preset("Wave Rainbow"))
    await asyncio.sleep(0)
    for i in range(5):
        device.submit_stream([p.solo_colour((i, i, i))])
        await asyncio.sleep(0)
    await preset
    await asyncio.sleep(0.05)
    sent = fake.writes_since(before)
    from custom_components.sb_katana import captured

    seq = list(captured.LIGHTING_PRESETS["Wave Rainbow"])
    start = sent.index(seq[0])
    assert sent[start : start + len(seq)] == seq
    # Only the newest stream frame survives coalescing.
    stream_writes = [h for h in sent if h.startswith("5a3a082b")]
    assert stream_writes and stream_writes[-1] == p.solo_colour((4, 4, 4)).frame.hex()
    await device.stop()


async def test_store_sub_follows_output():
    fake, device = await started(allow_unconfirmed=True)
    fake.notify("5a2c050124000000")
    await asyncio.sleep(0)
    assert device.state.output == "headphones" and device.state.store_sub == 2
    before = len(fake.writes)
    await device.set_store("acoustic", p.KEY_SURROUND, 0.0)
    assert fake.writes_since(before)[0] == "5aa70a12000201010000000000"
    assert device.state.store[2][p.KEY_SURROUND] == 0.0
    assert device.state.store[0][p.KEY_SURROUND] == 1.0
    await device.stop()


async def test_unsolicited_notification_updates_state_and_listeners():
    fake, device = await started()
    calls = []
    device.add_listener(lambda: calls.append(1))
    fake.notify("5a2303000b00")
    await asyncio.sleep(0)
    assert device.state.levels[0] == 11 and calls
    await device.stop()


async def test_unknown_frames_are_ignored():
    fake, device = await started()
    before = repr(device.state)
    fake.notify("5a6f0b0d4d562020303030372e31")  # stream format report
    fake.notify("5a01020104")
    await asyncio.sleep(0)
    assert repr(device.state) == before
    await device.stop()


async def test_disconnect_marks_unavailable_and_reconnects(monkeypatch):
    monkeypatch.setattr(dev, "RECONNECT_BACKOFF", (0.01,))
    fake, device = await started()
    fake.drop()
    assert not device.available
    await asyncio.sleep(0.1)
    assert device.available
    await device.stop()


async def test_select_mode_rereads_the_live_store():
    fake, device = await started(allow_unconfirmed=True)
    before = len(fake.writes)
    await device.select_mode(2)
    sent = fake.writes_since(before)
    assert sent[0] == "5aa7020002"
    assert p.store_query(0, 0, p.STORE_READ_KEYS[0]).frame.hex() in sent
    assert device.state.mode_active == 2
    await device.stop()


async def test_start_fails_when_unreachable():
    fake = FakeKatana()
    fake.fail_connect = True
    device = dev.KatanaDevice(fake)
    with pytest.raises(TimeoutError):
        await device.start()
    assert not device.available
    await device.stop()  # what setup does on failure


async def test_reads_that_time_out_are_retried_once(monkeypatch):
    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    fake = FakeKatana()
    stalled = p.output_query().frame.hex()
    fake.silent.add(stalled)
    original = fake.write

    async def write_once_silent(data: bytes) -> None:
        await original(data)
        if data.hex() == stalled:
            fake.silent.discard(stalled)  # the second ask is answered

    fake.write = write_once_silent
    device = dev.KatanaDevice(fake)
    await device.start()
    assert fake.writes.count(stalled) == 2
    assert device.state.output == "speakers"
    await device.stop()


async def test_poll_heals_reads_that_failed_at_connect(monkeypatch):
    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    fake = FakeKatana()
    store_read = p.store_query(0, 0, p.STORE_READ_KEYS[0]).frame.hex()
    fake.silent.add(store_read)
    device = dev.KatanaDevice(fake)
    await device.start()
    assert p.KEY_SURROUND not in device.state.store.get(0, {})
    fake.silent.discard(store_read)
    before = len(fake.writes)
    await device.refresh()  # the 60 s poll
    assert store_read in fake.writes_since(before)
    assert device.state.store[0][p.KEY_SURROUND] == 1.0
    # Once everything is known, the poll is back to its six quick reads.
    before = len(fake.writes)
    await device.refresh()
    assert len(fake.writes_since(before)) == 6
    await device.stop()


# --- review findings (2026-10-07) -----------------------------------------------------------


async def test_failed_read_back_after_reconnect_drops_the_link_and_retries(monkeypatch):
    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    monkeypatch.setattr(dev, "RECONNECT_BACKOFF", (0.01,))
    fake, device = await started()
    firmware = p.firmware_query().frame.hex()
    fake.silent.add(firmware)  # the identity read is lost on the first reconnect
    original = fake.write

    async def lose_once(data: bytes) -> None:
        await original(data)
        if data.hex() == firmware:
            fake.silent.discard(firmware)

    fake.write = lose_once
    fake.drop()
    assert not device.available
    for _ in range(100):
        await asyncio.sleep(0.02)
        if device.available:
            break
    assert device.available and device.firmware_ok
    assert fake.writes.count(firmware) >= 3  # setup, the lost one, the retry
    await device.stop()


async def test_identity_is_not_trusted_across_a_disconnect():
    fake, device = await started()
    assert device.firmware_ok
    device.hold_connection = False
    fake.drop()
    assert not device.available and not device.firmware_ok  # the old firmware read no longer counts
    await device.stop()


async def test_no_answer_forgets_the_value_but_a_refusal_keeps_it(monkeypatch):
    monkeypatch.setattr(dev, "REPLY_TIMEOUT", 0.05)
    fake, device = await started(allow_unconfirmed=True)
    # Refused: the old value stands.
    fake.status["5a26050702000100"] = 0x81
    with pytest.raises(dev.KatanaRejectedError):
        await device.set_scout(True)
    assert device.state.scout is False
    # Unanswered, and the re-read is lost too: unknown, not the old value.
    fake.silent.update({"5a26050702000100", p.scout_query().frame.hex()})
    fake.status.clear()
    with pytest.raises(dev.KatanaCommandError):
        await device.set_scout(True)
    assert device.state.scout is None
    await device.stop()


async def test_a_late_ok_ack_does_not_answer_a_read():
    _fake, device = await started()
    task = asyncio.create_task(device.request(p.scout_query()))
    await asyncio.sleep(0)
    # The fake has queued the real reply; a stray status-00 ACK arriving first must not win.
    device._on_frame(bytes.fromhex("5a020a26000000000000000000"))
    frame = await task
    assert frame.op == 0x26
    await device.stop()


async def test_store_write_refused_while_the_output_is_unknown():
    fake, device = await started(allow_unconfirmed=True)
    device.state.output = None
    before = len(fake.writes)
    with pytest.raises(dev.KatanaCommandError, match="output is unknown"):
        await device.set_store("acoustic", p.KEY_SURROUND, 0.0)
    assert fake.writes_since(before) == []
    await device.stop()


async def test_a_replaced_prepare_batch_carries_its_prepare_forward():
    _fake, device = await started()
    async with device._io_lock:  # hold the writer so both batches meet in the slot
        device.submit_stream([*p.solo_prepare(), p.solo_colour((1, 1, 1))], prepare=True)
        device.submit_stream([p.solo_colour((2, 2, 2))])
        assert [c.frame.hex() for c in device._stream_slot.cmds] == [
            *[c.frame.hex() for c in p.solo_prepare()],
            p.solo_colour((2, 2, 2)).frame.hex(),
        ]
    await asyncio.sleep(0.05)
    await device.stop()


async def test_writer_survives_an_unexpected_error():
    fake, device = await started()
    results: list[bool] = []
    original = fake.write
    calls = {"n": 0}

    async def explode_once(data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        await original(data)

    fake.write = explode_once
    device.submit_stream([p.solo_colour((3, 3, 3))], on_done=results.append)
    await asyncio.sleep(0.05)
    device.submit_stream([p.solo_colour((4, 4, 4))], on_done=results.append)
    await asyncio.sleep(0.05)
    assert results == [False, True]
    await device.stop()
