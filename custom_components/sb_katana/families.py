"""Command families and the confirmation gate.

Every write belongs to a family. A family is enabled by default only once the
owner has seen or heard it work over BLE (the rule agreed on 2026-10-07): bytes
from the app's traffic, a builder with a golden test and a safety review are
necessary but not sufficient. Until then a write raises unless the options
flow's "Allow unconfirmed controls" is on -- which exists for the owner's live
checklist, after which ``confirmed`` flips to True here.

``tier`` records how sure the decode is: "C" = confirmed by readback and a
screenshot, "P" = probable (bytes seen, meaning inferred from timing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Family:
    key: str
    tier: Literal["C", "P"]
    confirmed: bool
    label: str


_ALL = (
    # Proven over BLE on 2026-10-06: the owner watched the bar turn blue.
    Family("light_power", "C", True, "Lighting on/off"),
    Family("light_solo", "C", True, "Lighting solid colour"),
    Family("light_preset", "C", False, "Lighting presets"),
    Family("output", "C", False, "Output (Speakers/Headphones)"),
    Family("input", "C", False, "Input source"),
    Family("auto_switch", "C", False, "Auto switch to TV/HDMI"),
    Family("volume", "C", False, "Speaker volume"),
    Family("mute", "C", False, "Mute"),
    Family("sound_mode", "C", False, "Sound mode"),
    Family("decoder", "C", False, "Decoder"),
    Family("eq_enable", "C", False, "Equalizer on/off"),
    Family("eq_preset", "C", False, "Equalizer presets"),
    Family("acoustic", "C", False, "Acoustic Engine"),
    Family("crystalvoice", "C", False, "CrystalVoice"),
    Family("scout", "C", False, "Scout Mode"),
    Family("mixer", "C", False, "Mixer (Line In, SPDIF In, Microphone)"),
    Family("smart_volume_detail", "P", False, "Smart Volume level and mode"),
    Family("mixer_probable", "P", False, "Mixer (Headphones, What U Hear)"),
    Family("subwoofer", "P", False, "Subwoofer level"),
)

FAMILIES: dict[str, Family] = {f.key: f for f in _ALL}


def is_allowed(key: str, allow_unconfirmed: bool) -> bool:
    family = FAMILIES[key]
    return family.confirmed or allow_unconfirmed


# Labels for the captured presets. The device stores names in at most 16
# UTF-16 characters, so "Footsteps Enhancer" comes back as "Footsteps Enhanc".
LIGHT_PRESET_LABELS: dict[str, str] = {
    "Aurora": "Aurora",
    "Cycle": "Cycle",
    "Mood Orange": "Mood Orange",
    "Morph Cyan": "Morph Cyan",
    "Pulsate Red": "Pulsate Red",
    "Solo White": "Solo White",
    "Wave Green": "Wave Green",
    "Wave Ice Blue": "Wave Ice Blue",
    "Wave Rainbow": "Wave Rainbow",
}
EQ_PRESET_LABELS: dict[str, str] = {
    "Gaming": "Gaming",
    "Music": "Music",
    "Movies": "Movies",
    "Footsteps Enhanc": "Footsteps Enhancer",
}
