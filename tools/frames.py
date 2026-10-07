"""Load a Katana BLE capture exported as frames.tsv (epoch, ATT op, handle, value).

Export from an iOS .pklg with tshark; see docs/protocol.md. Commands are ATT
Write Command 0x52 to handle 0x000b, replies Notification 0x1b from 0x0008.
"""

import datetime as dt

# iOS stores pklg timestamps in local time and tshark presents them as UTC.
OFFSET = 2 * 3600


def load(path: str) -> list[dict]:
    out = []
    with open(path) as fh:
        for line in fh:
            t, op, _handle, value = line.rstrip("\n").split("\t")
            raw = bytes.fromhex(value.replace(":", ""))
            out.append(
                {
                    "t": float(t) - OFFSET,
                    "dir": "TX" if op == "0x52" else "RX",
                    "raw": raw,
                    "op": raw[1] if len(raw) > 1 else None,
                    "len": raw[2] if len(raw) > 2 else None,
                    "pl": raw[3:] if len(raw) > 3 else b"",
                }
            )
    return out


def hms(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]
