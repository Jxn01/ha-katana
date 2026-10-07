"""Extract the app's preset-load command sequences from the BLE capture.

Usage: python -I tools/extract_sequences.py <frames.tsv> > custom_components/sb_katana/captured.py

The output is the single source of truth for the preset sequences the
integration replays. Every frame in it was sent by Creative's own app to this
soundbar (firmware 1.3.230619.1820) on 2026-10-07 and acknowledged with
status 0x00 -- nothing here is synthesised.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frames import load


def utf16(b: bytes) -> str:
    return b.decode("utf-16-le").rstrip("\x00")


def main(path: str) -> None:
    tx = [f for f in load(path) if f["dir"] == "TX"]
    lighting: dict[str, list[str]] = {}
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
            lighting[name] = [s["raw"].hex() for s in seq]
            i = j + 1
            continue
        i += 1

    eq: dict[str, list[str]] = {}
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
            eq[name] = [s["raw"].hex() for s in seq]
            i = j
            continue
        i += 1

    print('"""Command sequences captured from Creative\'s app -- GENERATED, do not edit.')
    print()
    print("Regenerate with tools/extract_sequences.py. Firmware 1.3.230619.1820, 2026-10-07.")
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


if __name__ == "__main__":
    main(sys.argv[1])
