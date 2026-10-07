"""The generated preset sequences are intact and replayable."""

from custom_components.sb_katana import captured, protocol
from custom_components.sb_katana.families import EQ_PRESET_LABELS, LIGHT_PRESET_LABELS

LIGHT_COUNTS = {
    "Aurora": 8,
    "Cycle": 8,
    "Mood Orange": 8,
    "Morph Cyan": 10,
    "Pulsate Red": 9,
    "Solo White": 8,
    "Wave Green": 10,
    "Wave Ice Blue": 10,
    "Wave Rainbow": 10,
}


def test_all_nine_lighting_presets_with_their_frame_counts():
    assert {k: len(v) for k, v in captured.LIGHTING_PRESETS.items()} == LIGHT_COUNTS


def test_lighting_presets_are_bracketed_by_power_off_and_on():
    for name, seq in captured.LIGHTING_PRESETS.items():
        assert seq[0].startswith("5a3a1234ff"), name  # preset id into the live slot
        assert "5a3a022500" in seq, name  # lights off while the effect is rebuilt
        assert seq[-1] == "5a3a022501", name  # and back on


def test_all_five_eq_presets_have_both_outputs():
    assert set(captured.EQ_PRESETS) == {"Movies", "Footsteps Enhanc", "Gaming", "Music", "Flat"}
    for name, seq in captured.EQ_PRESETS.items():
        assert len(seq) == 10, name
        subs = {bytes.fromhex(h)[6] for h in seq if h.startswith("5aa8")}
        assert subs == {0x00, 0x02}, name  # Speakers and Headphones


def test_every_captured_frame_reencodes_through_the_allowlist():
    for seq in (
        *captured.LIGHTING_PRESETS.values(),
        *captured.EQ_PRESETS.values(),
        *((h,) for h in captured.MIC_EQ_PRESETS.values()),
    ):
        cmds = protocol.captured_sequence(seq)
        assert [c.frame.hex() for c in cmds] == list(seq)
        assert all(c.ack for c in cmds)


def test_labels_cover_exactly_the_captured_presets():
    assert set(LIGHT_PRESET_LABELS) == set(captured.LIGHTING_PRESETS)
    assert set(EQ_PRESET_LABELS) == set(captured.EQ_PRESETS)


def test_eleven_mic_eq_presets_all_distinct():
    assert len(captured.MIC_EQ_PRESETS) == 11
    assert len(set(captured.MIC_EQ_PRESETS.values())) == 11
    assert all(h.startswith("5a123108") for h in captured.MIC_EQ_PRESETS.values())


def test_only_builtin_eq_presets_are_kept():
    # The owner's own "Test2"/"Asddd" saves carry random identities and must not appear.
    for seq in captured.EQ_PRESETS.values():
        uuid = bytes.fromhex(next(h for h in seq if h.startswith("5aa8140b")))[7:23]
        assert uuid[:6] == bytes(6) and uuid[6:8] == b"\x10\x00"
