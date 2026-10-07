"""Shared loader for the Katana BLE capture (frames.tsv)."""
import datetime as dt

OFFSET = 2 * 3600  # pklg stores local time; tshark presents it as UTC -> recorded = real + 2h

def load(path="/home/jxn/Downloads/katana-capture/frames.tsv"):
    out = []
    for line in open(path):
        t, op, h, v = line.rstrip("\n").split("\t")
        b = bytes.fromhex(v.replace(":", ""))
        out.append({"t": float(t) - OFFSET, "dir": "TX" if op == "0x52" else "RX", "raw": b,
                    "op": b[1] if len(b) > 1 else None, "len": b[2] if len(b) > 2 else None,
                    "pl": b[3:] if len(b) > 3 else b""})
    return out

def hms(t):
    return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]
