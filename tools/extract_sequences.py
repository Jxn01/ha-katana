"""Extract the app's preset-load command sequences from the BLE capture.

Usage: python -I tools/extract_sequences.py <frames.tsv>... > custom_components/sb_katana/captured.py

The output is the single source of truth for the preset sequences the
integration replays. Every frame in it was sent by Creative's own app to this
soundbar (firmware 1.3.230619.1820) on 2026-10-07 and acknowledged with
status 0x00 -- nothing here is synthesised. With several captures, the first
occurrence of a name wins. EQ presets are kept only when they carry one of the
app's built-in identities (00000000-0000-1000-8000-0000000000NN): a preset the
owner saved under a made-up name is not a factory preset.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frames import load


def utf16(b: bytes) -> str:
    return b.decode("utf-16-le").rstrip("\x00")


# The microphone EQ presets, in the order of the app's list (screenshot, 2026-10-07 12:36).
# The first capture tapped them top to bottom, so its eleven 8-band writes map to these in
# order -- inferred from the tap order, not read back, so the labels are probable.
MIC_EQ_NAMES = (
    "Reduce Bass, Harshness; Improve Clarity",
    "Reduce Bass; Improve Vocal and Clarity",
    "Reduce Harshness; Improve Vocal",
    "Reduce Bass; Improve Vocal",
    "Improve Vocal; Reduce Harshness",
    "Reduce Bass; Improve Clarity",
    "Reduce Vocal, Improve Bass and Clarity",
    "Reduce Harshness; Improve Vocal and Clarity",
    "Reduce Harshness; Improve Clarity",
    "Improve Clarity",
    "Improve Vocal and Clarity",
)


def _builtin_uuid(seq) -> bool:
    for s in seq:
        if s["op"] == 0xA8 and s["pl"][:1] == b"\x0b":
            uuid = s["pl"][4:20]
            return uuid[:6] == bytes(6) and uuid[6:8] == b"\x10\x00"
    return False


def extract(path: str, lighting: dict, eq: dict, mic_eq: dict) -> None:
    tx = [f for f in load(path) if f["dir"] == "TX"]
    i = 0
    while i < len(tx):
        f = tx[i]
        # A lighting preset load starts with 3a/34 ff <uuid> and ends with 3a/25 01.
        if f["op"] == 0x3A and f["pl"][:2] == b"\x34\xff":
            seq = [f]
            j = i + 1
            while j < len(tx) and not (tx[j]["op"] == 0x3A and tx[j]["pl"] == b"\x25\x01"):
                seq.append(tx[j])
                j += 1
            seq.append(tx[j])
            name = next(utf16(s["pl"][5:]) for s in seq if s["pl"][:2] == b"\x31\xff")
            lighting.setdefault(name, [s["raw"].hex() for s in seq])
            i = j + 1
            continue
        i += 1

    i = 0
    while i < len(tx):
        f = tx[i]
        # An EQ-page preset pick: a7/12 00 02 01 (00,01)=0, a7/12 00 00 01 (00,01)=0,
        # then a8/0b+a8/05 for sub 02 and sub 00, then four a8/10 band writes.
        if f["op"] == 0xA7 and f["pl"].hex() == "12000201000100000000":
            seq = tx[i : i + 2]
            j = i + 2
            while j < len(tx) and tx[j]["op"] == 0xA8 and tx[j]["pl"][0] in (0x0B, 0x05, 0x10):
                seq.append(tx[j])
                j += 1
            name = next(utf16(s["pl"][7:]) for s in seq if s["op"] == 0xA8 and s["pl"][0] == 0x05)
            if _builtin_uuid(seq):
                eq.setdefault(name, [s["raw"].hex() for s in seq])
            i = j
            continue
        i += 1

    bands = [f for f in tx if f["op"] == 0x12 and f["pl"][:1] == b"\x08"]
    if len(bands) >= len(MIC_EQ_NAMES) and not mic_eq:
        for name, f in zip(MIC_EQ_NAMES, bands, strict=False):
            mic_eq[name] = f["raw"].hex()


def main(paths: list[str]) -> None:
    lighting: dict[str, list[str]] = {}
    eq: dict[str, list[str]] = {}
    mic_eq: dict[str, str] = {}
    for path in paths:
        extract(path, lighting, eq, mic_eq)

    print('"""Command sequences captured from Creative\'s app -- GENERATED, do not edit.')
    print()
    print("Regenerate with tools/extract_sequences.py. Firmware 1.3.230619.1820, 2026-10-07.")
    print("Mic EQ preset labels follow the first capture's tap order (probable).")
    print('"""')
    print()
    print("LIGHTING_PRESETS: dict[str, tuple[str, ...]] = {")
    for name, seq in lighting.items():
        print(f"    {name!r}: (")
        for h in seq:
            print(f'        "{h}",')
        print("    ),")
    print("}")
    print()
    print("EQ_PRESETS: dict[str, tuple[str, ...]] = {")
    for name, seq in eq.items():
        print(f"    {name!r}: (")
        for h in seq:
            print(f'        "{h}",')
        print("    ),")
    print("}")
    print()
    print("MIC_EQ_PRESETS: dict[str, str] = {")
    for name, h in mic_eq.items():
        print(f"    {name!r}: \"{h}\",")
    print("}")


if __name__ == "__main__":
    main(sys.argv[1:])
