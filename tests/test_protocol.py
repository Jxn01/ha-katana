"""Framing, reassembly, acknowledgements and the allowlist."""

import pytest

from custom_components.sb_katana import protocol as p


def test_encode_builds_a_5a_frame():
    assert p.encode(0x3A, b"\x25\x01") == bytes.fromhex("5a3a022501")


def test_encode_empty_payload():
    assert p.encode(0x03, b"") == bytes.fromhex("5a0300")


@pytest.mark.parametrize(
    ("op", "payload"),
    [
        (0x54, b"\x00\x00\x00\x00\x00\x00"),  # debug memory read
        (0x53, b"\x01\x01\x00\x00\x00"),  # firmware validate
        (0x98, b"\x03"),  # firmware transfer sub-command
        (0x5B, b"\x98"),
        (0x3A, b"\x30"),  # a lighting sub-command never seen
        (0xA7, b"\x05\xff\x02"),  # mode editor
        (0x60, b"\x04"),
    ],
)
def test_encode_refuses_what_is_not_allowlisted(op, payload):
    with pytest.raises(p.ForbiddenCommand):
        p.encode(op, payload)


@pytest.mark.parametrize(
    ("op", "payload", "reason"),
    [
        (0x23, bytes([0x00, 0x00, 51, 0, 0]), "level write shape"),  # level above 50
        (0x23, bytes([0x00, 0x07, 10, 0, 0]), "level write shape"),  # no channel 7
        (0x24, bytes([0x00, 0x00, 2]), "mute write shape"),
        (0x9C, bytes([0x00, 0x05, 0x00]), "input write shape"),  # not an input id
        (0x2C, bytes([0x00, 0x03, 0, 0, 0]), "output id"),
        (0x40, bytes([0x04, 0x01, 0x07, 0x00]), "subwoofer range"),  # +7
        (0xA7, bytes([0x00, 0x00]), "mode slot"),  # slot 0 is the live copy, not selectable
        (0xA7, bytes.fromhex("1201000101000000803f"), "live slot only"),
        (0xA7, bytes.fromhex("1200010101000000803f"), "store sub"),
        (0xA7, bytes.fromhex("12000001010000803f"), "store write length"),
        (0xA7, bytes.fromhex("1200000102000000803f"), "not writable"),  # unknown key 02.00
        (0xA7, bytes.fromhex("12000001000101000000"), "may only be cleared"),
        (0xA7, bytes.fromhex("1200000104000000a040"), "out of range"),  # decoder 5.0
        (0xA8, bytes.fromhex("0b000002"), "EQ custom-mark shape"),  # custom mark without its 16 zero bytes
        (0xA8, bytes.fromhex("0b000102") + bytes(16), "EQ live-load shape"),  # a stored EQ slot
        (0xA8, bytes.fromhex("100000000a") + bytes([2, 0, 0, 0, 0]) * 10, "EQ band order"),
        (
            0xA8,
            bytes.fromhex("100000000a") + b"".join(bytes([b]) + bytes.fromhex("00002041") for b in range(1, 11)),
            "EQ band gain range",
        ),  # +10 dB
        (0x12, bytes.fromhex("01950800008041"), "focus angle range"),  # 16 degrees
        (0x2D, bytes.fromhex("05010100"), "mic priority list"),
        (0x39, bytes.fromhex("001201"), "setting id"),
        (0x39, bytes.fromhex("07110f0000002c000000"), "auto standby value"),  # 44 min is not an option
        (0x39, bytes.fromhex("07120300"), "display value"),
        (0x12, bytes.fromhex("01960a00000000"), "not writable"),  # main EQ preamp
        (0x12, bytes.fromhex("01952c0000003f"), "DSP value"),  # 0.5
        (0x3A, bytes([0x25, 0x02]), "lighting power value"),
    ],
)
def test_encode_refuses_write_shapes_the_app_never_sent(op, payload, reason):
    with pytest.raises(p.ForbiddenCommand, match=reason):
        p.encode(op, payload)


def test_reader_split_and_joined():
    reader = p.FrameReader()
    reader.feed(bytes.fromhex("5a03"))
    assert reader.frames() == []
    reader.feed(bytes.fromhex("023b005a0102"))
    assert reader.frames() == [bytes.fromhex("5a03023b00")]
    reader.feed(bytes.fromhex("0104"))
    assert reader.frames() == [bytes.fromhex("5a01020104")]


def test_reader_skips_leading_junk():
    reader = p.FrameReader()
    reader.feed(b"\r\n" + bytes.fromhex("5a2c050102000000"))
    assert reader.frames() == [bytes.fromhex("5a2c050102000000")]


def test_reader_consumes_a_long_frame_whole_without_yielding_it():
    reader = p.FrameReader()
    # 5B, sub, u16 length 3, then three bytes that contain a 5A marker.
    reader.feed(bytes.fromhex("5b980300") + bytes.fromhex("5a0300") + bytes.fromhex("5a0300"))
    assert reader.frames() == [bytes.fromhex("5a0300")]


def test_parse_rejects_truncated():
    with pytest.raises(p.ProtocolError):
        p.parse(bytes.fromhex("5a3a0525"))


def test_parse_ack_ok():
    ack = p.parse_ack(p.parse(bytes.fromhex("5a020aa7000002000000000000")))
    assert ack == p.Ack(0xA7, 0x00, bytes.fromhex("0002000000000000"))


def test_parse_ack_unsupported():
    ack = p.parse_ack(p.parse(bytes.fromhex("5a020a28810000000000000000")))
    assert ack is not None
    assert (ack.op, ack.status) == (0x28, 0x81)


def test_parse_ack_ignores_data_frames():
    assert p.parse_ack(p.parse(bytes.fromhex("5a2c050102000000"))) is None


def test_matches_reply_uses_the_selector():
    colours = p.light_colours_query()
    assert p.matches_reply(colours, p.parse(bytes.fromhex("5a3a202c000101" + "ff000000" * 7)))
    # A speed reply shares sub-command 2C but not the parameter byte.
    assert not p.matches_reply(colours, p.parse(bytes.fromhex("5a3a052c00033605")))


def test_matches_ack_by_opcode():
    cmd = p.set_level(0, 12)
    assert p.matches_ack(cmd, p.Ack(0x23, 0, b""))
    assert not p.matches_ack(cmd, p.Ack(0x24, 0, b""))
