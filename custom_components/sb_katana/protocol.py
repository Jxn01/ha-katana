"""Sound Blaster Katana V2X control protocol over BLE, as pure functions.

Nothing in this module knows about Home Assistant or Bluetooth: it turns
intents into frames and frames into values. ``docs/protocol.md`` is the
evidence for every byte here -- each builder reproduces a frame Creative's own
app sent to this soundbar, and ``tests/test_protocol_commands.py`` pins each one
to the captured bytes.

Framing is ``5A <op> <len> <payload>``. A write is answered by an
acknowledgement, ``5A 02 0A <op> <status> <8 bytes>``; a read by a data frame of
the same opcode whose first payload bytes repeat the question's selector.

Safety is structural:

* :func:`encode` refuses any ``(opcode, first payload byte)`` not in
  :data:`ALLOWED_TX`, and checks the rest of each write's payload against the
  shapes seen in the capture (channel ranges, the live slot only, and so on).
* There is no builder for firmware transfer (``5B``/``0x98``), firmware
  apply (``0x53``) or device memory access (``0x54``), and a guard test fails if
  one appears.

Portions (lighting power, solo mode, colour count, solo colour, the colour
query and the frame reader) are a translation of the ``v2x`` crate by Rasmus
Moorats, MIT License, by way of ambience-rgb's ``katana_protocol.py``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MARKER = 0x5A
# Starts a firmware-transfer frame with a u16 length. Never sent; recognised only
# so that one arriving is skipped whole instead of being misread from the middle.
MARKER_LONG = 0x5B
ACK_OP = 0x02

TESTED_FIRMWARE = "1.3.230619.1820"

OP_PING = 0x03
OP_INFO = 0x09
OP_DSP_READ = 0x11
OP_DSP_WRITE = 0x12
OP_LEVEL = 0x23
OP_MUTE = 0x24
OP_SCOUT = 0x26
OP_OUTPUT = 0x2C
OP_LIGHT = 0x3A
OP_SUB = 0x40
OP_AUTO_SWITCH = 0x67
OP_INPUT = 0x9C
OP_MODE = 0xA7
OP_EQ = 0xA8

OUTPUT_SPEAKERS = 0x02
OUTPUT_HEADPHONES = 0x24

# Input ids in the order the device lists them (9C 02), which is the app's
# display order. USB is certain (readback + screenshot); the rest follow the list.
INPUT_LABELS: dict[int, str] = {
    0x0A: "TV",
    0x0C: "USB Audio",
    0x07: "Optical",
    0x04: "Aux",
    0x01: "Bluetooth",
}

# Volume channels (0x23 / 0x24). Levels are 0-50; the app shows level x 2 %.
CH_SPEAKERS = 0x00
CH_HEADPHONES = 0x01
CH_SPDIF_IN = 0x03
CH_LINE_IN = 0x04
CH_MICROPHONE = 0x05
CH_WHAT_U_HEAR = 0x06
CHANNELS = range(0x00, 0x07)
LEVEL_MAX = 50

SUB_MIN, SUB_MAX = -10, 6

# Sound-mode store: slot 00 is the live working copy of the active mode, and
# sub 00 / 02 hold its Speakers / Headphones configuration.
LIVE_SLOT = 0x00
MODE_SLOTS = range(0x01, 0x0B)
STORE_SUB_SPEAKERS = 0x00
STORE_SUB_HEADPHONES = 0x02

# Store keys (group, index). Two of them hold a u32 in the 4-byte value slot,
# not a float -- reading or writing them as f32 yields garbage.
KEY_EQ_ENABLE = (0x00, 0x00)
KEY_EQ_SLOT = (0x00, 0x01)
KEY_SURROUND = (0x01, 0x00)
KEY_SURROUND_LEVEL = (0x01, 0x01)
KEY_CRYSTALIZER = (0x01, 0x02)
KEY_CRYSTALIZER_LEVEL = (0x01, 0x03)
KEY_SMART_VOLUME = (0x01, 0x06)
KEY_SMART_VOLUME_LEVEL = (0x01, 0x07)
KEY_SMART_VOLUME_MODE = (0x01, 0x08)
KEY_DIALOG_PLUS = (0x01, 0x09)
KEY_DIALOG_PLUS_LEVEL = (0x01, 0x0A)
KEY_UNKNOWN_02 = (0x02, 0x00)
KEY_LIGHT_POWER = (0x03, 0x00)
KEY_LIGHT_SLOT = (0x03, 0x01)
KEY_DECODER = (0x04, 0x00)
U32_KEYS = frozenset({KEY_EQ_SLOT, KEY_LIGHT_SLOT})
# The two requests the app makes to read a whole configuration (8 + 7 keys).
STORE_READ_KEYS: tuple[tuple[tuple[int, int], ...], ...] = (
    (
        KEY_LIGHT_POWER,
        KEY_LIGHT_SLOT,
        KEY_DECODER,
        KEY_UNKNOWN_02,
        KEY_SURROUND,
        KEY_SURROUND_LEVEL,
        KEY_CRYSTALIZER,
        KEY_CRYSTALIZER_LEVEL,
    ),
    (
        KEY_SMART_VOLUME,
        KEY_SMART_VOLUME_MODE,
        KEY_SMART_VOLUME_LEVEL,
        KEY_DIALOG_PLUS,
        KEY_DIALOG_PLUS_LEVEL,
        KEY_EQ_ENABLE,
        KEY_EQ_SLOT,
    ),
)
# The store keys the integration may write, and what values each accepts.
STORE_WRITABLE: dict[tuple[int, int], tuple[float, float]] = {
    KEY_EQ_ENABLE: (0.0, 1.0),
    KEY_SURROUND: (0.0, 1.0),
    KEY_SURROUND_LEVEL: (0.0, 1.0),
    KEY_CRYSTALIZER: (0.0, 1.0),
    KEY_CRYSTALIZER_LEVEL: (0.0, 1.0),
    KEY_SMART_VOLUME: (0.0, 1.0),
    KEY_SMART_VOLUME_LEVEL: (0.0, 1.0),
    KEY_SMART_VOLUME_MODE: (0.0, 2.0),
    KEY_DIALOG_PLUS: (0.0, 1.0),
    KEY_DIALOG_PLUS_LEVEL: (0.0, 1.0),
    KEY_DECODER: (1.0, 3.0),
}
DECODER_LABELS: dict[int, str] = {2: "Normal", 1: "Full", 3: "Night"}

# Live DSP parameters (0x11 read / 0x12 write), big-endian 16-bit ids.
DSP_MIC_SMART_VOLUME = 0x952C
DSP_MIC_EQ = 0x9513
DSP_MIC_FOCUS = 0x9506
DSP_READ_IDS = (DSP_MIC_SMART_VOLUME, DSP_MIC_EQ, DSP_MIC_FOCUS)
# Only the CrystalVoice switches the app writes through 0x12, each 0.0 or 1.0.
DSP_WRITABLE = frozenset(DSP_READ_IDS)
DSP_MAX_PER_READ = 9

# Lighting (0x3A). The live configuration is slot 00.
LIGHT_SUB_POWER = 0x25
LIGHT_SUB_POWER_QUERY = 0x26
LIGHT_SUB_MODE = 0x29
LIGHT_SUB_MODE_QUERY = 0x2A
LIGHT_SUB_PARAM = 0x2B
LIGHT_SUB_PARAM_QUERY = 0x2C
LIGHT_SUB_NAME = 0x31
LIGHT_SUB_NAME_QUERY = 0x32
LIGHT_SUB_ID = 0x34
LIGHT_SUB_COUNT = 0x37
LIGHT_SUB_MAP_QUERY = 0x24
LIGHT_MODE_MOOD = 0x03  # "Solo" is Mood with a colour count of one.
LIGHT_SLOTS = 7
LIGHT_MODE_LABELS = {0x01: "Cycle", 0x03: "Mood", 0x04: "Wave", 0x05: "Pulsate", 0x07: "Morph", 0x08: "Aurora"}

# Every (opcode, first payload byte) the integration may emit. ``None`` is a
# frame with an empty payload. Each entry is a frame the app sent.
ALLOWED_TX: frozenset[tuple[int, int | None]] = frozenset(
    {
        (OP_PING, None),
        (OP_INFO, 0x02),
        (OP_INFO, 0x03),
        (OP_OUTPUT, 0x00),
        (OP_OUTPUT, 0x01),
        (OP_INPUT, 0x00),
        (OP_INPUT, 0x01),
        (OP_INPUT, 0x02),
        (OP_AUTO_SWITCH, 0x0C),
        (OP_AUTO_SWITCH, 0x0D),
        (OP_LEVEL, 0x00),
        (OP_LEVEL, 0x01),
        (OP_MUTE, 0x00),
        (OP_MUTE, 0x01),
        (OP_SUB, 0x03),
        (OP_SUB, 0x04),
        (OP_SCOUT, 0x07),
        (OP_SCOUT, 0x08),
        (OP_MODE, 0x00),
        (OP_MODE, 0x01),
        (OP_MODE, 0x06),
        (OP_MODE, 0x12),
        (OP_MODE, 0x13),
        (OP_EQ, 0x05),
        (OP_EQ, 0x06),
        (OP_EQ, 0x0B),
        (OP_EQ, 0x10),
        (OP_DSP_WRITE, 0x01),
        *((OP_DSP_READ, n) for n in range(1, DSP_MAX_PER_READ + 1)),
        (OP_LIGHT, LIGHT_SUB_POWER),
        (OP_LIGHT, LIGHT_SUB_POWER_QUERY),
        (OP_LIGHT, LIGHT_SUB_MODE),
        (OP_LIGHT, LIGHT_SUB_MODE_QUERY),
        (OP_LIGHT, LIGHT_SUB_PARAM),
        (OP_LIGHT, LIGHT_SUB_PARAM_QUERY),
        (OP_LIGHT, LIGHT_SUB_NAME),
        (OP_LIGHT, LIGHT_SUB_NAME_QUERY),
        (OP_LIGHT, LIGHT_SUB_ID),
        (OP_LIGHT, LIGHT_SUB_COUNT),
        (OP_LIGHT, LIGHT_SUB_MAP_QUERY),
    }
)


class ForbiddenCommand(ValueError):
    """A frame outside the allowlist, or a write whose payload has a shape the app never sent."""


class ProtocolError(ValueError):
    """A frame that does not parse as what it was expected to be."""


@dataclass(frozen=True, slots=True)
class Command:
    """One frame to send, and how to recognise its answer.

    ``reply_op`` is set for reads: the answer is a data frame with that opcode
    whose payload starts with ``reply_prefix``. ``ack`` is set for writes: the
    answer is an acknowledgement for this frame's opcode.
    """

    frame: bytes
    reply_op: int | None = None
    reply_prefix: bytes = b""
    ack: bool = False

    @property
    def op(self) -> int:
        return self.frame[1]

    @property
    def payload(self) -> bytes:
        return self.frame[3:]


@dataclass(frozen=True, slots=True)
class Frame:
    op: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class Ack:
    op: int
    status: int
    echo: bytes


def encode(op: int, payload: bytes) -> bytes:
    """Build ``5A op len payload``, refusing anything the allowlist does not cover."""
    key = (op, payload[0] if payload else None)
    if key not in ALLOWED_TX:
        raise ForbiddenCommand(f"opcode {op:#04x} / {key[1]!r} is not allowlisted")
    if len(payload) > 0xFF:
        raise ForbiddenCommand("payload too long for a 5A frame")
    _check_payload(op, payload)
    return bytes([MARKER, op, len(payload)]) + payload


def _check_payload(op: int, payload: bytes) -> None:
    """Hold every write to the shapes the capture showed. Reads pass through."""

    def need(condition: bool, what: str) -> None:
        if not condition:
            raise ForbiddenCommand(f"opcode {op:#04x}: {what} ({payload.hex()})")

    sub = payload[0] if payload else None
    if op == OP_LEVEL and sub == 0x00:
        need(len(payload) == 5 and payload[1] in CHANNELS and payload[2] <= LEVEL_MAX, "level write shape")
        need(payload[3:] == b"\x00\x00", "level write padding")
    elif op == OP_MUTE and sub == 0x00:
        need(len(payload) == 3 and payload[1] in CHANNELS and payload[2] in (0, 1), "mute write shape")
    elif op == OP_INPUT and sub == 0x00:
        need(len(payload) == 3 and payload[1] in INPUT_LABELS and payload[2] == 0, "input write shape")
    elif op == OP_OUTPUT and sub == 0x00:
        need(payload in (bytes([0, OUTPUT_SPEAKERS, 0, 0, 0]), bytes([0, OUTPUT_HEADPHONES, 0, 0, 0])), "output id")
    elif op == OP_AUTO_SWITCH and sub == 0x0C:
        need(len(payload) == 2 and payload[1] in (0, 1), "auto-switch value")
    elif op == OP_SCOUT and sub == 0x07:
        need(payload in (bytes.fromhex("0702000000"), bytes.fromhex("0702000100")), "scout write shape")
    elif op == OP_SUB and sub == 0x04:
        need(len(payload) == 4 and payload[1] == 0x01, "subwoofer write shape")
        need(SUB_MIN <= struct.unpack("<h", payload[2:4])[0] <= SUB_MAX, "subwoofer range")
    elif op == OP_MODE and sub == 0x00:
        need(len(payload) == 2 and payload[1] in MODE_SLOTS, "mode slot")
    elif op == OP_MODE and sub == 0x12:
        _check_store_write(payload, need)
    elif op == OP_EQ and sub in (0x05, 0x0B, 0x10):
        # Only ever a captured preset load into the live EQ: "<sub> 00 ff <00|02> ...".
        need(len(payload) >= 4 and payload[1:3] == b"\x00\xff" and payload[3] in (0, 2), "EQ live-load shape")
    elif op == OP_DSP_WRITE:
        need(len(payload) == 7, "DSP write shape")
        need(struct.unpack(">H", payload[1:3])[0] in DSP_WRITABLE, "DSP id not writable")
        need(struct.unpack("<f", payload[3:7])[0] in (0.0, 1.0), "DSP value")
    elif op == OP_DSP_READ:
        need(len(payload) == 1 + 2 * payload[0], "DSP read shape")
    elif op == OP_LIGHT and sub == LIGHT_SUB_POWER:
        need(len(payload) == 2 and payload[1] in (0, 1), "lighting power value")


def _check_store_write(payload: bytes, need) -> None:
    need(len(payload) >= 4, "store write shape")
    slot, sub, count = payload[1], payload[2], payload[3]
    need(slot == LIVE_SLOT, "store writes go to the live slot only")
    need(sub in (STORE_SUB_SPEAKERS, STORE_SUB_HEADPHONES), "store sub")
    need(len(payload) == 4 + 6 * count, "store write length")
    for i in range(count):
        entry = payload[4 + 6 * i : 10 + 6 * i]
        key = (entry[0], entry[1])
        if key == KEY_EQ_SLOT:
            # The app writes 0 here before an EQ preset load; nothing else.
            need(struct.unpack("<I", entry[2:6])[0] == 0, "EQ slot reference may only be cleared")
            continue
        need(key in STORE_WRITABLE, f"store key {key} is not writable")
        low, high = STORE_WRITABLE[key]
        value = struct.unpack("<f", entry[2:6])[0]
        need(low <= value <= high, f"store key {key} out of range")


def _cmd(op: int, *payload: int, reply_prefix: bytes | None = None, ack: bool = False) -> Command:
    frame = encode(op, bytes(payload))
    if ack:
        return Command(frame, ack=True)
    prefix = bytes(payload) if reply_prefix is None else reply_prefix
    return Command(frame, reply_op=op, reply_prefix=prefix)


# --- identity -----------------------------------------------------------------


def ping() -> Command:
    return Command(encode(OP_PING, b""), reply_op=OP_PING, reply_prefix=b"")


def firmware_query() -> Command:
    return _cmd(OP_INFO, 0x02)


def serial_query() -> Command:
    return _cmd(OP_INFO, 0x03)


# --- routing --------------------------------------------------------------------


def output_query() -> Command:
    return _cmd(OP_OUTPUT, 0x01)


def set_output(headphones: bool) -> Command:
    return _cmd(OP_OUTPUT, 0x00, OUTPUT_HEADPHONES if headphones else OUTPUT_SPEAKERS, 0, 0, 0, ack=True)


def input_query() -> Command:
    return _cmd(OP_INPUT, 0x01)


def input_list_query() -> Command:
    return _cmd(OP_INPUT, 0x02)


def set_input(input_id: int) -> Command:
    return _cmd(OP_INPUT, 0x00, input_id, 0x00, ack=True)


def auto_switch_query() -> Command:
    return _cmd(OP_AUTO_SWITCH, 0x0D)


def set_auto_switch(on: bool) -> Command:
    return _cmd(OP_AUTO_SWITCH, 0x0C, int(on), ack=True)


# --- volume -----------------------------------------------------------------------


def level_query(channel: int) -> Command:
    return _cmd(OP_LEVEL, 0x01, channel, 0, 0, 0, reply_prefix=bytes([channel]))


def set_level(channel: int, level: int) -> Command:
    return _cmd(OP_LEVEL, 0x00, channel, level, 0, 0, ack=True)


def mute_query(channel: int) -> Command:
    return _cmd(OP_MUTE, 0x01, channel, reply_prefix=bytes([channel]))


def set_mute(channel: int, muted: bool) -> Command:
    return _cmd(OP_MUTE, 0x00, channel, int(muted), ack=True)


def sub_query() -> Command:
    return _cmd(OP_SUB, 0x03)


def set_sub(level: int) -> Command:
    low, high = struct.pack("<h", level)
    return _cmd(OP_SUB, 0x04, 0x01, low, high, ack=True)


def scout_query() -> Command:
    return _cmd(OP_SCOUT, 0x08, 0xFF, 0xFF)


def set_scout(on: bool) -> Command:
    return _cmd(OP_SCOUT, 0x07, 0x02, 0x00, int(on), 0x00, ack=True)


# --- sound modes ------------------------------------------------------------------


def mode_active_query() -> Command:
    return _cmd(OP_MODE, 0x01)


def select_mode(slot: int) -> Command:
    return _cmd(OP_MODE, 0x00, slot, ack=True)


def mode_name_query(slot: int) -> Command:
    return _cmd(OP_MODE, 0x06, slot, 0x00)


def store_query(slot: int, sub: int, keys: tuple[tuple[int, int], ...]) -> Command:
    flat = [b for key in keys for b in key]
    return _cmd(OP_MODE, 0x13, slot, sub, len(keys), *flat, reply_prefix=bytes([0x13, slot, sub]))


def _store_value(key: tuple[int, int], value: float | int) -> bytes:
    if key in U32_KEYS:
        return struct.pack("<I", int(value))
    return struct.pack("<f", float(value))


def store_write(sub: int, entries: list[tuple[tuple[int, int], float | int]]) -> Command:
    body = bytearray([0x12, LIVE_SLOT, sub, len(entries)])
    for key, value in entries:
        body += bytes(key) + _store_value(key, value)
    return Command(encode(OP_MODE, bytes(body)), ack=True)


def eq_name_query(sub: int) -> Command:
    return _cmd(OP_EQ, 0x06, 0x00, LIVE_SLOT, sub)


# --- live DSP -------------------------------------------------------------------------


def dsp_query(ids: tuple[int, ...]) -> Command:
    if not 1 <= len(ids) <= DSP_MAX_PER_READ:
        raise ForbiddenCommand("a DSP read takes 1-9 ids, so the reply fits one frame")
    body = bytearray([len(ids)])
    for pid in ids:
        body += struct.pack(">H", pid)
    return Command(encode(OP_DSP_READ, bytes(body)), reply_op=OP_DSP_READ, reply_prefix=bytes([len(ids), 0]))


def dsp_write(pid: int, value: float) -> Command:
    return Command(encode(OP_DSP_WRITE, b"\x01" + struct.pack(">H", pid) + struct.pack("<f", value)), ack=True)


# --- lighting ---------------------------------------------------------------------------


def light_power(on: bool) -> Command:
    return _cmd(OP_LIGHT, LIGHT_SUB_POWER, int(on), ack=True)


def light_power_query() -> Command:
    return _cmd(OP_LIGHT, LIGHT_SUB_POWER_QUERY)


def light_mode_query() -> Command:
    return _cmd(OP_LIGHT, LIGHT_SUB_MODE_QUERY, LIVE_SLOT)


def light_colours_query() -> Command:
    return _cmd(
        OP_LIGHT, LIGHT_SUB_PARAM_QUERY, LIVE_SLOT, 0x01, 0x01, LIGHT_SLOTS, reply_prefix=bytes.fromhex("2c000101")
    )


def light_name_query() -> Command:
    return _cmd(OP_LIGHT, LIGHT_SUB_NAME_QUERY, LIVE_SLOT)


def light_map_query() -> Command:
    return _cmd(OP_LIGHT, LIGHT_SUB_MAP_QUERY, LIVE_SLOT)


def solo_prepare() -> list[Command]:
    """Lighting on, one colour slot, Mood mode: what ambience-rgb sends before a solo colour."""
    return [
        light_power(True),
        _cmd(OP_LIGHT, LIGHT_SUB_COUNT, LIVE_SLOT, 0x01, ack=True),
        _cmd(OP_LIGHT, LIGHT_SUB_MODE, LIVE_SLOT, LIGHT_MODE_MOOD, ack=True),
    ]


def solo_colour(rgb: tuple[int, int, int]) -> Command:
    """Set the solo colour. Takes RGB; the device wants ABGR with alpha FF."""
    if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
        raise ValueError(f"colour channels must be 0-255, got {rgb!r}")
    red, green, blue = rgb
    return _cmd(OP_LIGHT, LIGHT_SUB_PARAM, LIVE_SLOT, 0x01, 0x01, 0xFF, blue, green, red, ack=True)


def captured_sequence(frames_hex: tuple[str, ...]) -> list[Command]:
    """Re-encode a sequence the app sent, so every frame still passes the allowlist."""
    commands = []
    for hexframe in frames_hex:
        raw = bytes.fromhex(hexframe)
        frame = parse(raw)
        rebuilt = encode(frame.op, frame.payload)
        if rebuilt != raw:
            raise ProtocolError(f"captured frame does not re-encode identically: {hexframe}")
        commands.append(Command(rebuilt, ack=True))
    return commands


# --- framing ----------------------------------------------------------------------------


class FrameReader:
    """Reassembles frames from notifications that may split or merge them.

    Bytes before a frame marker are skipped. A firmware-transfer frame (``5B``,
    u16 length) is consumed whole so that it can never be misread.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> None:
        self._buffer += data

    def clear(self) -> None:
        self._buffer.clear()

    def frames(self) -> list[bytes]:
        found: list[bytes] = []
        while True:
            start = next((i for i, b in enumerate(self._buffer) if b in (MARKER, MARKER_LONG)), None)
            if start is None:
                self._buffer.clear()
                return found
            del self._buffer[:start]
            length = _frame_length(self._buffer)
            if length is None or len(self._buffer) < length:
                return found
            raw = bytes(self._buffer[:length])
            del self._buffer[:length]
            if raw[0] == MARKER:
                found.append(raw)


def _frame_length(buffer: bytearray) -> int | None:
    if buffer[0] == MARKER:
        return 3 + buffer[2] if len(buffer) >= 3 else None
    return 4 + struct.unpack_from("<H", buffer, 2)[0] if len(buffer) >= 4 else None


def parse(raw: bytes) -> Frame:
    if len(raw) < 3 or raw[0] != MARKER or len(raw) != 3 + raw[2]:
        raise ProtocolError(f"not a whole 5A frame: {raw.hex()}")
    return Frame(raw[1], bytes(raw[3:]))


def parse_ack(frame: Frame) -> Ack | None:
    if frame.op != ACK_OP or len(frame.payload) < 2:
        return None
    return Ack(frame.payload[0], frame.payload[1], frame.payload[2:])


def matches_reply(cmd: Command, frame: Frame) -> bool:
    return cmd.reply_op is not None and frame.op == cmd.reply_op and frame.payload.startswith(cmd.reply_prefix)


def matches_ack(cmd: Command, ack: Ack) -> bool:
    """An acknowledgement names the opcode it answers. Its echo bytes are not a
    reliable copy of the request (most opcodes echo zeros), so only one command
    may be in flight at a time -- the device's writer queue guarantees it."""
    return ack.op == cmd.op


# --- parsers -------------------------------------------------------------------------------


def _expect(frame: Frame, op: int, prefix: bytes, minimum: int) -> bytes:
    if frame.op != op or not frame.payload.startswith(prefix) or len(frame.payload) < minimum:
        raise ProtocolError(f"expected {op:#04x}/{prefix.hex()}, got {frame.op:#04x}/{frame.payload.hex()}")
    return frame.payload


def _utf16(data: bytes) -> str:
    text = data[: len(data) - len(data) % 2].decode("utf-16-le", "replace")
    return text.split("\x00", 1)[0]


def parse_firmware(frame: Frame) -> str:
    p = _expect(frame, OP_INFO, b"\x02", 2)
    return p[2 : 2 + p[1]].split(b"\0", 1)[0].decode("ascii", "replace")


def parse_serial(frame: Frame) -> str:
    p = _expect(frame, OP_INFO, b"\x03", 2)
    return p[1:].split(b"\0", 1)[0].decode("ascii", "replace")


def parse_output(frame: Frame) -> str:
    p = _expect(frame, OP_OUTPUT, b"\x01", 2)
    return "headphones" if p[1] == OUTPUT_HEADPHONES else "speakers"


def parse_input(frame: Frame) -> int:
    return _expect(frame, OP_INPUT, b"\x01", 2)[1]


def parse_input_list(frame: Frame) -> list[int]:
    p = _expect(frame, OP_INPUT, b"\x02", 3)
    return [p[3 + 3 * i] for i in range(p[2]) if 3 + 3 * i < len(p)]


def parse_level(frame: Frame) -> tuple[int, int]:
    p = _expect(frame, OP_LEVEL, b"", 2)
    return p[0], p[1]


def parse_mute(frame: Frame) -> tuple[int, bool]:
    p = _expect(frame, OP_MUTE, b"", 2)
    return p[0], bool(p[1])


def parse_sub(frame: Frame) -> int:
    p = _expect(frame, OP_SUB, b"\x03", 3)
    return struct.unpack("<h", p[1:3])[0]


def parse_scout(frame: Frame) -> bool:
    return bool(_expect(frame, OP_SCOUT, b"\x08\xff\xff", 4)[3])


def parse_auto_switch(frame: Frame) -> bool:
    return bool(_expect(frame, OP_AUTO_SWITCH, b"\x0d", 2)[1])


def parse_mode_active(frame: Frame) -> int:
    return _expect(frame, OP_MODE, b"\x01", 2)[1]


def parse_mode_name(frame: Frame) -> tuple[int, int, str]:
    """``06 slot y len max 00 <UTF-16LE>`` -> (slot, y, name)."""
    p = _expect(frame, OP_MODE, b"\x06", 6)
    return p[1], p[2], _utf16(p[6:])


def parse_store(frame: Frame) -> tuple[int, int, dict[tuple[int, int], float | int]]:
    p = _expect(frame, OP_MODE, b"\x13", 4)
    slot, sub, count = p[1], p[2], p[3]
    values: dict[tuple[int, int], float | int] = {}
    for i in range(count):
        entry = p[4 + 6 * i : 10 + 6 * i]
        if len(entry) < 6:
            break
        key = (entry[0], entry[1])
        if key in U32_KEYS:
            values[key] = struct.unpack("<I", entry[2:6])[0]
        else:
            values[key] = struct.unpack("<f", entry[2:6])[0]
    return slot, sub, values


def parse_eq_name(frame: Frame) -> tuple[int, int, str]:
    """``06 00 slot sub len max 00 <UTF-16LE>`` -> (slot, sub, name)."""
    p = _expect(frame, OP_EQ, b"\x06\x00", 7)
    return p[2], p[3], _utf16(p[7:])


def parse_dsp(frame: Frame) -> dict[int, float]:
    p = _expect(frame, OP_DSP_READ, b"", 2)
    values: dict[int, float] = {}
    for i in range(p[0]):
        entry = p[2 + 6 * i : 8 + 6 * i]
        if len(entry) < 6:
            break
        values[struct.unpack(">H", entry[0:2])[0]] = struct.unpack("<f", entry[2:6])[0]
    return values


def parse_light_power(frame: Frame) -> bool:
    return bool(_expect(frame, OP_LIGHT, bytes([LIGHT_SUB_POWER_QUERY]), 2)[1])


def parse_light_mode(frame: Frame) -> tuple[int, int]:
    p = _expect(frame, OP_LIGHT, bytes([LIGHT_SUB_MODE_QUERY]), 3)
    return p[1], p[2]


def parse_colours(frame: Frame) -> tuple[int, list[tuple[int, int, int]]]:
    """``2c slot 01 01 <ABGR>...`` -> (slot, [RGB...])."""
    p = _expect(frame, OP_LIGHT, bytes([LIGHT_SUB_PARAM_QUERY]), 4)
    if p[2:4] != b"\x01\x01":
        raise ProtocolError(f"not a colour parameter reply: {p.hex()}")
    body = p[4:]
    return p[1], [(body[i + 3], body[i + 2], body[i + 1]) for i in range(0, len(body) - 3, 4)]


def parse_light_name(frame: Frame) -> tuple[int, str]:
    p = _expect(frame, OP_LIGHT, bytes([LIGHT_SUB_NAME_QUERY]), 5)
    return p[1], _utf16(p[5:])


def parse_light_map_is_solid(frame: Frame) -> tuple[int, bool]:
    """``24 slot n n 00 <n slot numbers>``: solid when every LED shows colour slot 1."""
    p = _expect(frame, OP_LIGHT, bytes([LIGHT_SUB_MAP_QUERY]), 5)
    leds = p[5 : 5 + p[2]]
    return p[1], bool(leds) and all(b == 1 for b in leds)
