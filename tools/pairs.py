"""Pair each TX with the RX frames that follow it until the next TX."""
import sys; sys.path.insert(0, "/home/jxn/Downloads/katana-capture/decode")
from frames import load, hms
def pairs():
    F = load(); out=[]; cur=None
    for f in F:
        if f["dir"]=="TX":
            cur={"tx":f,"rx":[]}; out.append(cur)
        elif cur is not None:
            cur["rx"].append(f)
    return out
