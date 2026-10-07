"""Pair each command in a capture with the notifications that follow it until the next command."""

from frames import load


def pairs(path: str) -> list[dict]:
    out: list[dict] = []
    current = None
    for f in load(path):
        if f["dir"] == "TX":
            current = {"tx": f, "rx": []}
            out.append(current)
        elif current is not None:
            current["rx"].append(f)
    return out
