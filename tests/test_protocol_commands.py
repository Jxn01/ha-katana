"""Golden vectors: every builder reproduces a frame Creative's app sent, and every
parser decodes a reply the soundbar gave, byte for byte (from the captures)."""

import struct

import pytest

from custom_components.sb_katana import protocol as p


def frame(hexstr: str) -> p.Frame:
    return p.parse(bytes.fromhex(hexstr))


# (builder output, captured frame)
GOLDEN = [
    (p.ping(), "5a0300"),
    (p.firmware_query(), "5a090102"),
    (p.serial_query(), "5a090103"),
    (p.output_query(), "5a2c0101"),
    (p.set_output(True), "5a2c050024000000"),
    (p.set_output(False), "5a2c050002000000"),
    (p.input_query(), "5a9c0101"),
    (p.input_list_query(), "5a9c0102"),
    (p.set_input(0x0A), "5a9c03000a00"),
    (p.set_input(0x0C), "5a9c03000c00"),
    (p.auto_switch_query(), "5a67010d"),
    (p.set_auto_switch(False), "5a67020c00"),
    (p.set_auto_switch(True), "5a67020c01"),
    (p.level_query(5), "5a23050105000000"),
    (p.set_level(0, 13), "5a230500000d0000"),
    (p.set_level(5, 41), "5a23050005290000"),
    (p.mute_query(2), "5a24020102"),
    (p.set_mute(0, True), "5a2403000001"),
    (p.sub_query(), "5a400103"),
    (p.set_sub(-1), "5a40040401ffff"),
    (p.set_sub(3), "5a40040401" + "0300"),
    (p.scout_query(), "5a260308ffff"),
    (p.set_scout(True), "5a26050702000100"),
    (p.set_scout(False), "5a26050702000000"),
    (p.mode_active_query(), "5aa70101"),
    (p.select_mode(9), "5aa7020009"),
    (p.mode_name_query(1), "5aa703060100"),
    (p.store_query(0, 0, p.STORE_READ_KEYS[0]), "5aa7141300000803000301040002000100010101020103"),
    (p.store_query(0, 0, p.STORE_READ_KEYS[1]), "5aa71213000007010601080107010901" + "0a00000001"),
    (p.store_write(0, [(p.KEY_SURROUND, 0.0)]), "5aa70a12000001010000000000"),
    (p.store_write(0, [(p.KEY_SURROUND, 1.0)]), "5aa70a1200000101000000803f"),
    (p.store_write(0, [(p.KEY_DECODER, 3.0)]), "5aa70a12000001040000004040"),
    (p.store_write(2, [(p.KEY_EQ_SLOT, 0)]), "5aa70a12000201000100000000"),
    (p.eq_name_query(0), "5aa80406000000"),
    (p.dsp_write(p.DSP_MIC_SMART_VOLUME, 0.0), "5a120701952c00000000"),
    (p.dsp_write(p.DSP_MIC_EQ, 1.0), "5a1207019513" + "0000803f"),
    (p.light_power(False), "5a3a022500"),
    (p.light_power(True), "5a3a022501"),
    (p.light_power_query(), "5a3a0126"),
    (p.light_mode_query(), "5a3a022a00"),
    (p.light_colours_query(), "5a3a052c00010107"),
    (p.light_name_query(), "5a3a023200"),
    (p.light_map_query(), "5a3a022400"),
    (p.solo_colour((0, 0, 255)), "5a3a082b000101ffff0000"),
    # Second and third captures.
    (p.light_brightness(0xFC), "5a3a0227fc"),
    (p.light_brightness_query(), "5a3a0128"),
    (p.mic_priority_query(), "5a2d0101"),
    (p.set_mic_priority((0x01, 0x00)), "5a2d0405020100"),
    (p.set_mic_priority((0x00, 0x01)), "5a2d0405020001"),
    (p.set_mic_priority(()), "5a2d020500"),
    (p.settings_query(), "5a390101"),
    (p.auto_standby_query(), "5a39020611"),
    (p.display_query(), "5a39020612"),
    (p.set_setting(p.SETTING_ENERGY_SAVING, False), "5a3903001100"),
    (p.set_setting(p.SETTING_CEC_LINK, True), "5a3903001801"),
    (p.set_auto_standby(465), "5a390a07110f000000d1010000"),
    (p.set_auto_standby(1665), "5a390a07110f00000081060000"),
    (p.set_auto_standby(0), "5a390a07110f00000000000000"),
    (p.set_display((0x02, 0x05)), "5a390407120205"),
    (p.set_display((0x07, 0x00)), "5a390407120700"),
    (p.dsp_write(p.DSP_MIC_FOCUS_ANGLE, struct.unpack("<f", bytes.fromhex("17990643"))[0]), "5a120701950817990643"),
]


@pytest.mark.parametrize(("cmd", "expected"), GOLDEN, ids=[g[1] for g in GOLDEN])
def test_builder_matches_capture(cmd, expected):
    assert cmd.frame.hex() == expected


def test_solo_prepare_is_ambience_rgbs_sequence():
    # Confirmed over BLE on the real soundbar.
    assert [c.frame.hex() for c in p.solo_prepare()] == ["5a3a022501", "5a3a03370001", "5a3a03290003"]


def test_writes_expect_acks_and_reads_expect_replies():
    assert p.set_level(0, 1).ack and p.set_level(0, 1).reply_op is None
    q = p.level_query(3)
    assert not q.ack and q.reply_op == 0x23 and q.reply_prefix == b"\x03"


def test_dsp_query_frame_and_limit():
    assert p.dsp_query(p.DSP_READ_IDS).frame.hex() == "5a1107" + "03952c95139506"
    with pytest.raises(p.ForbiddenCommand):
        p.dsp_query(tuple(range(0x9600, 0x960A)))


def test_solo_colour_rejects_bad_channels():
    with pytest.raises(ValueError):
        p.solo_colour((256, 0, 0))
    with pytest.raises(ValueError):
        p.solo_colour((1, 2))


# --- parsers over real replies -------------------------------------------------------------


def test_parse_firmware():
    assert p.parse_firmware(frame("5a09120210312e332e3233303631392e3138323000")) == "1.3.230619.1820"


def test_parse_serial():
    fake = b"Q8MF0000000000000W".hex()
    assert p.parse_serial(frame("5a0914" + "03" + fake + "00")) == "Q8MF0000000000000W"


def test_parse_output():
    assert p.parse_output(frame("5a2c050102000000")) == "speakers"
    assert p.parse_output(frame("5a2c050124000000")) == "headphones"


def test_parse_input_and_list():
    assert p.parse_input(frame("5a9c07010c590b000000")) == 0x0C
    assert p.parse_input_list(frame("5a9c120205050a00010c0001070001040001010001")) == [0x0A, 0x0C, 0x07, 0x04, 0x01]


def test_parse_level_and_mute():
    assert p.parse_level(frame("5a2303000c00")) == (0, 12)
    assert p.parse_mute(frame("5a24020201")) == (2, True)


def test_parse_sub_signed():
    assert p.parse_sub(frame("5a4003030300")) == 3
    assert p.parse_sub(frame("5a400303ffff")) == -1


def test_parse_scout():
    assert p.parse_scout(frame("5a260b08ffff0000000000000000")) is False
    assert p.parse_scout(frame("5a260b08ffff0200000000000000")) is True


def test_parse_auto_switch_and_mode_active():
    assert p.parse_auto_switch(frame("5a67020d01")) is True
    assert p.parse_mode_active(frame("5aa7020101")) == 1


def test_parse_mode_name():
    raw = "5aa7260601001010004d0075007300690063002e000000000000000000000000000000000000000000"
    assert p.parse_mode_name(frame(raw)) == (1, 0, "Music.")


def test_parse_store_types_each_key():
    raw = (
        "5aa7341300000803000000803f03010000000004000000803f02000000000001000000803f01010000803f01020000803f01030000003f"
    )
    slot, sub, values = p.parse_store(frame(raw))
    assert (slot, sub) == (0, 0)
    assert values[p.KEY_SURROUND_LEVEL] == 1.0
    assert values[p.KEY_CRYSTALIZER_LEVEL] == 0.5
    assert values[p.KEY_DECODER] == 1.0
    assert values[p.KEY_LIGHT_POWER] == 1.0


def test_parse_store_reads_u32_keys_as_integers():
    # Slot 1 sub 1's lighting slot is 0x81 and its EQ slot 1: denormals if read as floats.
    raw = (
        "5aa7341300010803000000000003018100000004000000004002000000000001000000803f01013333333f01020000803f0103cdcccc3e"
    )
    _, _, values = p.parse_store(frame(raw))
    assert values[p.KEY_LIGHT_SLOT] == 0x81
    body = "13000107010600000000010800000000010700000000010900000000010a0000000000000000803f000101000000"
    _, _, values2 = p.parse_store(frame(f"5aa7{len(body) // 2:02x}{body}"))
    assert values2[p.KEY_EQ_SLOT] == 1
    assert values2[p.KEY_EQ_ENABLE] == 1.0


def test_parse_eq_name():
    raw = "5aa827060000001010004d00750073006900630000000000000000000000000000000000000000000000"
    assert p.parse_eq_name(frame(raw)) == (0, 0, "Music")


def test_parse_dsp():
    raw = "5a1114" + "0300" + "952c0000803f" + "951300000000" + "95060000803f"
    assert p.parse_dsp(frame(raw)) == {0x952C: 1.0, 0x9513: 0.0, 0x9506: 1.0}


def test_parse_dsp_real_bulk_frame():
    raw = (
        "5a1138090196000000803f96010000803f96070000803f96080000003f960400000000960500000000"
        "960600000000960200000000960300000000"
    )
    assert p.parse_dsp(frame(raw))[0x9608] == 0.5


def test_parse_lighting():
    assert p.parse_light_power(frame("5a3a022601")) is True
    assert p.parse_light_mode(frame("5a3a032a0003")) == (0, 3)
    slot, colours = p.parse_colours(frame("5a3a202c000101ff000000ff037804ff037804ff000000ff000000ff000000ff000000"))
    assert slot == 0
    assert colours[0] == (0, 0, 0)
    assert colours[1] == (4, 120, 3)
    name = "5a3a2532001010004f006e0062006f00610072006400000000000000000000000000000000000000"
    assert p.parse_light_name(frame(name)) == (0, "Onboard")


def test_parse_light_map():
    solid = "5a3a1f24001a1a00" + "01" * 26
    multi = "5a3a1f24011a1a000101010102020202030303040404040505050606060607070707"
    assert p.parse_light_map_is_solid(frame(solid)) == (0, True)
    assert p.parse_light_map_is_solid(frame(multi)) == (1, False)


def test_parsers_reject_the_wrong_frame():
    with pytest.raises(p.ProtocolError):
        p.parse_firmware(frame("5a2c050102000000"))
    with pytest.raises(p.ProtocolError):
        p.parse_colours(frame("5a3a052c00033605"))


def test_auto_standby_options_match_the_captured_values():
    # 8 h, 2 h, 1 h, 30 min, never, 28 h -- as the app sent them, minutes beyond the 15-min network standby.
    assert sorted(p.AUTO_STANDBY_OPTIONS.values()) == sorted([0x1D1, 0x69, 0x2D, 0x0F, 0x00, 0x681])


def test_eq_band_write_reproduces_the_captured_drag():
    captured = bytes.fromhex(
        "5aa837100000000a010000000002000000000300000000040000000005000000000600000000"
        "070000000008000000000910dc07400a60433940"
    )
    gains = [struct.unpack("<f", captured[9 + 5 * i : 13 + 5 * i])[0] for i in range(10)]
    mark, bands = p.eq_band_write(0, gains)
    assert mark.frame.hex() == "5aa8140b000000" + "00" * 16
    assert bands.frame == captured


def test_eq_value_reads_match_the_app():
    first, second = p.eq_values_queries(0)
    assert first.frame.hex() == "5aa80f110000000a00010203040506070809"
    assert second.frame.hex() == "5aa80811000000030a0b0c"


def test_captured_mic_eq_preset_frame_passes_the_encoder():
    raw = bytes.fromhex(
        "5a123108951700000000951900008040951b0000e040951a0000c04095140000a0c09516000000c09515000080c0951800004040"
    )
    frame = p.parse(raw)
    assert p.encode(frame.op, frame.payload) == raw


def test_parse_new_replies():
    assert p.parse_light_brightness(p.parse(bytes.fromhex("5a3a0228b7"))) == 0xB7
    assert p.parse_mic_priority(p.parse(bytes.fromhex("5a2d0401020001"))) == (0x00, 0x01)
    assert p.parse_settings(p.parse(bytes.fromhex("5a39050100000601"))) == (True, True)
    assert p.parse_settings(p.parse(bytes.fromhex("5a39050100000401"))) == (False, True)
    assert p.parse_auto_standby(p.parse(bytes.fromhex("5a391206110f000000810600000000000001000000"))) == 1665
    assert p.parse_display(p.parse(bytes.fromhex("5a390406120700"))) == (0x07, 0x00)
    body = "1100000003" + "0a" + "00001040" + "0b" + "0000c0c0" + "0c" + "00000000"
    slot, sub, values = p.parse_eq_values(p.parse(bytes.fromhex(f"5aa8{len(body) // 2:02x}{body}")))
    assert (slot, sub) == (0, 0) and values == {0x0A: 2.25, 0x0B: -6.0, 0x0C: 0.0}
