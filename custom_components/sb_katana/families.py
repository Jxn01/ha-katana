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
    # Confirmed live by the owner on 2026-10-07 (morning checklist).
    Family("light_preset", "C", True, "Lighting presets"),
    Family("output", "C", True, "Output (Speakers/Headphones)"),
    Family("auto_switch", "C", True, "Auto switch to TV/HDMI"),
    Family("volume", "C", True, "Speaker volume"),
    Family("mute", "C", True, "Mute"),
    Family("decoder", "C", True, "Decoder"),
    Family("eq_enable", "C", True, "Equalizer on/off"),
    Family("eq_preset", "C", True, "Equalizer presets"),
    Family("acoustic", "C", True, "Acoustic Engine"),
    Family("crystalvoice", "C", True, "CrystalVoice"),
    Family("scout", "C", True, "Scout Mode"),
    Family("mixer", "C", True, "Mixer (Line In, SPDIF In, Microphone)"),
    Family("smart_volume_detail", "C", True, "Smart Volume level and mode"),
    Family("what_u_hear", "C", True, "Mixer (What U Hear)"),
    Family("subwoofer", "C", True, "Subwoofer level"),
    # Confirmed later the same day, once they were also exposed as selects.
    Family("input", "C", True, "Input source"),
    Family("sound_mode", "C", True, "Sound mode"),
    # Reported not working (2026-10-07). Headphones are not used with this soundbar,
    # so it stays unconfirmed and its entity is disabled by default.
    Family("headphones_level", "P", False, "Headphones level"),
    # From the third capture (2026-10-07 12:54-12:58), tried from HA by the owner on
    # 2026-10-08 ~00:50: "they are all correct" -- the labels inferred from tap order too.
    Family("light_brightness", "C", True, "Lighting brightness"),
    Family("eq_bands", "C", True, "Equalizer bands"),
    Family("focus_angle", "C", True, "Microphone Focus angle"),
    Family("energy_saving", "C", True, "Energy Saving"),
    Family("auto_standby", "C", True, "Auto Standby"),
    Family("cec_link", "C", True, "HDMI CEC Standby Link"),
    Family("mic_priority", "C", True, "Microphone Priority"),
    Family("mic_eq_preset", "C", True, "Microphone Equalizer presets"),
    Family("display", "C", True, "Display brightness"),
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
    "Flat": "Flat",
}
