"""A fake soundbar: answers reads with replies taken from the 2026-10-07 capture
and acknowledges writes, over the same frame interface the BLE transport uses."""

from __future__ import annotations

import asyncio
import struct

from custom_components.sb_katana import protocol as p

FAKE_SERIAL = "Q8MF0000000000000W"
FAKE_ADDRESS = "FF:00:00:00:00:01"

LEVELS = {0: 12, 1: 12, 2: 18, 3: 50, 4: 18, 5: 35, 6: 50}
MUTES = {2: True}
MODE_NAMES = {1: "Music.", 2: "Gaming.", 3: "Voice.", **dict.fromkeys(range(4, 11), "Effects Off")}
STORE = {
    0: {
        p.KEY_LIGHT_POWER: 1.0,
        p.KEY_LIGHT_SLOT: 0x81,
        p.KEY_DECODER: 1.0,
        p.KEY_UNKNOWN_02: 0.0,
        p.KEY_SURROUND: 1.0,
        p.KEY_SURROUND_LEVEL: 1.0,
        p.KEY_CRYSTALIZER: 1.0,
        p.KEY_CRYSTALIZER_LEVEL: 0.5,
        p.KEY_SMART_VOLUME: 0.0,
        p.KEY_SMART_VOLUME_MODE: 0.0,
        p.KEY_SMART_VOLUME_LEVEL: 0.0,
        p.KEY_DIALOG_PLUS: 0.0,
        p.KEY_DIALOG_PLUS_LEVEL: 0.0,
        p.KEY_EQ_ENABLE: 1.0,
        p.KEY_EQ_SLOT: 1,
    },
}
STORE[2] = {**STORE[0], p.KEY_SURROUND_LEVEL: 0.5}
# The live EQ ("Music"): preamp, the ten bands, bass, treble -- as read in the first capture.
EQ_VALUES = {
    0: 0.0,
    1: 0.0,
    2: 0.0,
    3: -1.0,
    4: -1.0,
    5: -1.0,
    6: 1.5,
    7: 1.5,
    8: 0.0,
    9: 2.0,
    10: 2.0,
    11: 0.0,
    12: 2.0,
}


def frame(op: int, payload: bytes) -> bytes:
    return bytes([p.MARKER, op, len(payload)]) + payload


def utf16_field(name: str, width: int = 32) -> bytes:
    data = name.encode("utf-16-le")
    return data + bytes(width - len(data))


def store_reply(slot: int, sub: int, keys, values) -> bytes:
    body = bytearray([0x13, slot, sub, len(keys)])
    for key in keys:
        value = values[key]
        body += bytes(key) + (struct.pack("<I", value) if key in p.U32_KEYS else struct.pack("<f", value))
    return frame(p.OP_MODE, bytes(body))


def ack(op: int, status: int = 0) -> bytes:
    return frame(p.ACK_OP, bytes([op, status]) + bytes(8))


class FakeKatana:
    """Implements the device module's Transport protocol."""

    def __init__(self, *, firmware: str = p.TESTED_FIRMWARE) -> None:
        self.on_frame = None
        self.on_disconnect = None
        self.connected = False
        self.write_limit = 182
        self.writes: list[str] = []
        self.firmware = firmware
        self.fail_connect = False
        self.silent: set[str] = set()  # frames (hex) that get no answer
        self.status: dict[str, int] = {}  # frames (hex) answered with this ACK status
        self.replies = self._build_replies()

    def _build_replies(self) -> dict[str, list[bytes]]:
        fw = self.firmware.encode()
        r: dict[str, list[bytes]] = {
            "5a0300": [frame(0x03, b"\x3b\x00")],
            "5a090102": [frame(0x09, bytes([0x02, len(fw) + 1]) + fw + b"\x00")],
            "5a090103": [frame(0x09, b"\x03" + FAKE_SERIAL.encode() + b"\x00")],
            "5a2c0101": [bytes.fromhex("5a2c050102000000")],
            "5a9c0101": [bytes.fromhex("5a9c07010c590b000000")],
            "5a9c0102": [bytes.fromhex("5a9c120205050a00010c0001070001040001010001")],
            "5a67010d": [bytes.fromhex("5a67020d01")],
            "5a400103": [bytes.fromhex("5a4003030300")],
            "5a260308ffff": [bytes.fromhex("5a260b08ffff0000000000000000")],
            "5aa70101": [bytes.fromhex("5aa7020101")],
            "5a3a0126": [bytes.fromhex("5a3a022601")],
            "5a3a022a00": [bytes.fromhex("5a3a032a0003")],
            "5a3a052c00010107": [
                bytes.fromhex("5a3a202c000101ff000000ff037804ff037804ff000000ff000000ff000000ff000000")
            ],
            "5a3a023200": [frame(p.OP_LIGHT, bytes.fromhex("3200101000") + utf16_field("Onboard"))],
            "5a3a022400": [frame(p.OP_LIGHT, bytes.fromhex("24001a1a00") + b"\x01" * 26)],
        }
        for ch in p.CHANNELS:
            r[p.level_query(ch).frame.hex()] = [frame(p.OP_LEVEL, bytes([ch, LEVELS[ch], 0]))]
            r[p.mute_query(ch).frame.hex()] = [frame(p.OP_MUTE, bytes([ch, int(MUTES.get(ch, False))]))]
        for slot, name in {0: "Music.", **MODE_NAMES}.items():
            r[p.mode_name_query(slot).frame.hex()] = [
                frame(p.OP_MODE, bytes([0x06, slot, 0x00, 0x10, 0x10, 0x00]) + utf16_field(name))
            ]
        for sub, values in STORE.items():
            for keys in p.STORE_READ_KEYS:
                r[p.store_query(0, sub, keys).frame.hex()] = [store_reply(0, sub, keys, values)]
            r[p.eq_name_query(sub).frame.hex()] = [
                frame(p.OP_EQ, bytes([0x06, 0x00, 0x00, sub, 0x10, 0x10, 0x00]) + utf16_field("Music"))
            ]
        dsp = b"".join(
            struct.pack(">H", pid) + struct.pack("<f", v) for pid, v in ((0x952C, 1.0), (0x9513, 0.0), (0x9506, 1.0))
        )
        r[p.dsp_query(p.DSP_READ_IDS).frame.hex()] = [frame(p.OP_DSP_READ, b"\x03\x00" + dsp)]
        dsp2 = struct.pack(">H", 0x9508) + struct.pack("<f", 30.0)
        dsp2 += b"".join(struct.pack(">H", pid) + struct.pack("<f", 0.0) for pid in p.DSP_MIC_EQ_BANDS)
        r[p.dsp_query(p.DSP_READ_IDS_2).frame.hex()] = [frame(p.OP_DSP_READ, b"\x09\x00" + dsp2)]
        for sub in (0, 2):
            first, second = p.eq_values_queries(sub)
            for cmd, idxs in ((first, range(0, 10)), (second, (10, 11, 12))):
                body = bytes([0x11, 0x00, 0x00, sub, len(idxs)])
                body += b"".join(bytes([i]) + struct.pack("<f", EQ_VALUES[i]) for i in idxs)
                r[cmd.frame.hex()] = [frame(p.OP_EQ, body)]
        r[p.light_brightness_query().frame.hex()] = [bytes.fromhex("5a3a0228ff")]
        r[p.mic_priority_query().frame.hex()] = [bytes.fromhex("5a2d0401020001")]
        r[p.settings_query().frame.hex()] = [bytes.fromhex("5a39050100000601")]
        r[p.auto_standby_query().frame.hex()] = [bytes.fromhex("5a391206110f000000810600000000000001000000")]
        r[p.display_query().frame.hex()] = [bytes.fromhex("5a390406120700")]
        return r

    async def connect(self) -> None:
        if self.fail_connect:
            raise TimeoutError("fake soundbar out of range")
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def write(self, data: bytes) -> None:
        h = data.hex()
        self.writes.append(h)
        if h in self.silent:
            return
        answers = self.replies[h] if h in self.replies else [ack(data[1], self.status.get(h, 0))]
        loop = asyncio.get_running_loop()
        for answer in answers:
            loop.call_soon(self._deliver, answer)

    def _deliver(self, raw: bytes) -> None:
        if self.on_frame is not None and self.connected:
            self.on_frame(raw)

    def notify(self, hexframe: str) -> None:
        """Inject an unsolicited notification."""
        self._deliver(bytes.fromhex(hexframe))

    def drop(self) -> None:
        self.connected = False
        if self.on_disconnect is not None:
            self.on_disconnect()

    def writes_since(self, index: int) -> list[str]:
        return self.writes[index:]
