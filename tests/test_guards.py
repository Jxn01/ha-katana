"""Guards that fail the build if a dangerous class of frame or I/O ever appears.

Each guard has a positive control proving its pattern still bites -- a guard
that cannot fail is not evidence of anything.
"""

import inspect
import re
import struct
from pathlib import Path

import pytest

from custom_components.sb_katana import captured, protocol

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "sb_katana"

FORBIDDEN_OPS = {0x53: "firmware apply", 0x54: "memory read/write/exec", 0x98: "firmware transfer"}


def forbidden_reason(frame: bytes) -> str | None:
    if not frame:
        return "empty frame"
    if frame[0] == protocol.MARKER_LONG:
        return "5B firmware-transfer frame"
    if frame[0] != protocol.MARKER:
        return "unknown marker"
    if frame[1] in FORBIDDEN_OPS:
        return FORBIDDEN_OPS[frame[1]]
    if len(frame) > 3 and frame[3] == 0x98:
        return "firmware transfer sub-command"
    return None


# Sample arguments for every public builder. A builder missing from this table
# fails test_every_builder_is_sampled, so a new one cannot dodge the scan.
SAMPLES = {
    "ping": [()],
    "firmware_query": [()],
    "serial_query": [()],
    "output_query": [()],
    "set_output": [(True,), (False,)],
    "input_query": [()],
    "input_list_query": [()],
    "set_input": [(i,) for i in protocol.INPUT_LABELS],
    "auto_switch_query": [()],
    "set_auto_switch": [(True,), (False,)],
    "level_query": [(c,) for c in protocol.CHANNELS],
    "set_level": [(c, v) for c in protocol.CHANNELS for v in (0, 25, 50)],
    "mute_query": [(c,) for c in protocol.CHANNELS],
    "set_mute": [(c, m) for c in protocol.CHANNELS for m in (True, False)],
    "sub_query": [()],
    "set_sub": [(v,) for v in range(protocol.SUB_MIN, protocol.SUB_MAX + 1)],
    "scout_query": [()],
    "set_scout": [(True,), (False,)],
    "mode_active_query": [()],
    "select_mode": [(s,) for s in protocol.MODE_SLOTS],
    "mode_name_query": [(s,) for s in protocol.MODE_SLOTS],
    "store_query": [(0, sub, keys) for sub in (0, 2) for keys in protocol.STORE_READ_KEYS],
    "store_write": [(sub, [(k, lo), (k, hi)]) for sub in (0, 2) for k, (lo, hi) in protocol.STORE_WRITABLE.items()]
    + [(0, [(protocol.KEY_EQ_SLOT, 0)])],
    "eq_name_query": [(0,), (2,)],
    "dsp_query": [(protocol.DSP_READ_IDS,)],
    "dsp_write": [(pid, v) for pid in protocol.DSP_WRITABLE for v in (0.0, 1.0)],
    "light_power": [(True,), (False,)],
    "light_power_query": [()],
    "light_mode_query": [()],
    "light_colours_query": [()],
    "light_name_query": [()],
    "light_map_query": [()],
    "solo_prepare": [()],
    "solo_colour": [((0, 0, 0),), ((255, 255, 255),), ((0x5A, 0x53, 0x54),)],
    "captured_sequence": [(seq,) for seq in (*captured.LIGHTING_PRESETS.values(), *captured.EQ_PRESETS.values())],
}


def _builders():
    for name, fn in inspect.getmembers(protocol, inspect.isfunction):
        if name.startswith("_") or fn.__module__ != protocol.__name__:
            continue
        ret = str(inspect.signature(fn).return_annotation)
        if "Command" in ret:
            yield name, fn


def _all_frames():
    for name, fn in _builders():
        for args in SAMPLES[name]:
            out = fn(*args)
            for cmd in out if isinstance(out, list) else [out]:
                yield name, cmd.frame


def test_every_builder_is_sampled():
    assert {name for name, _ in _builders()} == set(SAMPLES)


def test_no_builder_or_captured_frame_is_forbidden():
    offenders = [
        (name, frame.hex(), forbidden_reason(frame)) for name, frame in _all_frames() if forbidden_reason(frame)
    ]
    assert offenders == []


def test_every_emitted_frame_is_allowlisted():
    for name, frame in _all_frames():
        key = (frame[1], frame[3] if len(frame) > 3 else None)
        assert key in protocol.ALLOWED_TX, (name, frame.hex())


@pytest.mark.parametrize(
    "frame",
    ["5a540600000000000004", "5a5305010100000000", "5b981200030000", "5a01019800"],
)
def test_forbidden_scanner_positive_control(frame):
    assert forbidden_reason(bytes.fromhex(frame)) is not None


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
COMMAND_UUIDS = {"9e9daaec-3a10-4fe8-b69f-7397aff77886", "9e9daaeb-3a10-4fe8-b69f-7397aff77886"}


def test_only_the_command_channel_uuids_appear_in_the_integration():
    found = set()
    for path in PACKAGE.rglob("*.py"):
        found |= {u.lower() for u in UUID_RE.findall(path.read_text())}
    assert found == COMMAND_UUIDS


def test_uuid_regex_positive_control():
    sample = 'SECOND = "e49a25e0-f69a-11e8-8eb2-f2801f1b9fd1"'
    assert UUID_RE.findall(sample) == ["e49a25e0-f69a-11e8-8eb2-f2801f1b9fd1"]


def test_only_transport_writes_gatt_and_only_to_the_write_uuid():
    writers = [p.name for p in PACKAGE.rglob("*.py") if "write_gatt_char" in p.read_text()]
    assert writers == ["transport.py"]
    calls = re.findall(r"write_gatt_char\(\s*([A-Za-z_]+)", (PACKAGE / "transport.py").read_text())
    assert calls and set(calls) == {"WRITE_UUID"}


def test_u32_store_keys_are_never_encoded_as_floats():
    for key in protocol.U32_KEYS:
        assert protocol._store_value(key, 1) == struct.pack("<I", 1)


def test_u32_guard_positive_control():
    # If a u32 key were packed as f32, 1 would read 0000803f, not 01000000.
    assert struct.pack("<f", 1.0) != struct.pack("<I", 1)
    assert protocol._store_value(protocol.KEY_SURROUND, 1) == struct.pack("<f", 1.0)
