# Sound Blaster Katana V2X for Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-custom%20integration-18BCF2?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Bluetooth LE](https://img.shields.io/badge/Bluetooth-LE-0082FC?style=for-the-badge&logo=bluetooth&logoColor=white)](https://www.bluetooth.com/)
[![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)

A custom integration (`sb_katana`) that drives a **Creative Sound Blaster Katana V2X** over **Bluetooth LE**,
directly from Home Assistant. It replaces Creative's mobile app: lighting (including screen sync from a PC),
volume, input/output, sound modes, the Acoustic Engine, EQ, CrystalVoice, Scout Mode and the mixer.

Every command it can send is a byte sequence that Creative's own app was **captured** sending to this
soundbar (firmware `1.3.230619.1820`). The decode, with evidence for every opcode, is in
[`docs/protocol.md`](docs/protocol.md).

> Tested against one unit on firmware **1.3.230619.1820** only. On any other firmware the integration
> refuses every write and raises a repair issue. **Do not install Creative's firmware updates** if you want
> to keep control from Home Assistant.

## Requirements

- Home Assistant **2026.9** or newer, with a working Bluetooth adapter or proxy within range of the soundbar.
- The soundbar's BLE control device, which advertises the command service `9e9daaea-…` (in a scan response,
  it is named `Control for MF8400`). It answers on any input; pairing mode is not needed.
- **One central at a time.** While Home Assistant holds the connection, Creative's app cannot connect. Turn
  off **Hold connection** to let the app in.

## Install

1. Copy `custom_components/sb_katana` into your HA config's `custom_components/` (or add this repository to
   HACS as a custom integration repository).
2. Restart Home Assistant.
3. The soundbar is discovered automatically (**Settings → Devices & services → Discovered**). Otherwise add
   **Sound Blaster Katana V2X** by hand and pick it from the list.

HA's local adapter in passive scanning mode does not hear the soundbar well enough to connect: its flags
byte (`0x0A`) is not in habluetooth's passive patterns. The integration handles this itself by asking HA for
an on-demand active sweep before connecting.

## What you get

One device, **Sound Blaster Katana V2X**, with:

- a **light** for the light bar — on/off, colour, brightness and the app's nine effect presets;
- a **media player** — volume, mute, source and sound mode;
- switches, selects and numbers for the Acoustic Engine, the EQ (ten bands and the presets), CrystalVoice, Scout Mode,
  the mixer, the decoder, the output, standby and the display;
- diagnostics: the firmware version, whether screen sync is receiving, and a button to re-read every value.

Every entity, its options and the command family behind it are listed in [docs/reference.md](docs/reference.md).
Options: **Allow unconfirmed controls** (off), **Screen sync rate** (10 writes/s) and **Screen sync hand-over** (10 s).

## Screen sync from a PC

A PC can stream colours to the light bar, for example [ambience-rgb](https://github.com/Jxn01/ambience-rgb):

```
POST /api/sb_katana/stream
Authorization: Bearer <long-lived access token>

{"rgb": [r, g, b]}
```

Send on every colour change and at least every 5 s; after 10 s without a frame the light bar is turned off once. Any
manual lighting change in Home Assistant switches **Screen sync** off, and frames are then answered with
`accepted: false`. It is an HTTP endpoint rather than a service so a 10 Hz stream does not fill the recorder with
events. Responses, the status `GET` and the equivalent service are in [docs/reference.md](docs/reference.md).

## Safety

- **An allowlist.** The encoder refuses any `(opcode, sub-command)` outside a fixed list. It checks the payload
  of every write that carries a parameter against the shapes the app sent: volume and mute (channel and level
  ranges), input, output, auto-switch, scout, subwoofer, sound-mode slot, the sound-mode store (live slot only,
  the Speakers/Headphones sub-configurations only, writable keys and ranges, integer encoding for the two
  integer keys), the CrystalVoice DSP ids, lighting power. The remaining writes have no free parameters: the solid-colour
  frames come from fixed builders, and the lighting and EQ presets are the app's own frames replayed
  verbatim. Those are checked by golden tests rather than by shape.
- **No dangerous builders.** There is no builder for firmware transfer (`5B`/`0x98`), firmware apply
  (`0x53`) or device-memory access (`0x54`). The soundbar's second GATT service is never touched. Guard
  tests fail the build if any of that appears, and each guard has a positive control.
- **The confirmation gate.** A command family is enabled by default only once it has been seen or heard working on
  the real soundbar over BLE. That is every family except **Headphones level** (reported not working, so its entity is
  also disabled by default); **Allow unconfirmed controls** enables it.
- **State comes only from the soundbar.** A value changes when the soundbar reports it or acknowledges a
  write. A refusal (status ≠ 0) keeps the old value. No answer means the outcome is unknown: the value is
  cleared and re-read. The firmware (and so the write gate) is re-read on every reconnect. Nothing is written
  on a timer. The 60 s poll is reads only, and it also re-reads anything still unknown.
- **Flash.** The soundbar saves settings to flash only after it has been idle, so wear scales with how often a value
  settles, not with how fast it is written.

## Look and language

Brand images in `custom_components/sb_katana/brand/` (the public-domain Sound Blaster logo from Wikimedia Commons),
icons for every entity, and English and Hungarian translations for everything a user sees. `tests/test_ui.py` keeps
icons, names and both languages complete.

## Development

```bash
python3.14 -m venv ~/.local/share/venvs/ha-katana
~/.local/share/venvs/ha-katana/bin/pip install -r requirements_test.txt
~/.local/share/venvs/ha-katana/bin/pytest -q tests
~/.local/share/venvs/ha-katana/bin/ruff check custom_components tests tools
```

`protocol.py` is the pure byte layer (framing, the allowlist, every builder and parser); `captured.py` is generated
by `tools/extract_sequences.py` from a capture; `device.py` holds state and the one-exchange-at-a-time I/O. The tests
use golden vectors and a fake soundbar that answers with captured replies. CI runs ruff, pytest on Python 3.14, and
hassfest.

## Licence

MIT (`LICENSE`); attribution in `NOTICE`. "Sound Blaster", "Katana" and "Creative" are trademarks of
Creative Technology Ltd; the logo is used only to identify the device this integration talks to, and this
project is not affiliated with or endorsed by Creative. Parts of `protocol.py` are translated from the [`v2x`](https://git.dog/xx/v2x) crate by Rasmus Moorats
(MIT).
