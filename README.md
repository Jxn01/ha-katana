# Sound Blaster Katana V2X for Home Assistant

A custom integration (`sb_katana`) that drives a **Creative Sound Blaster Katana V2X** over **Bluetooth LE**,
directly from Home Assistant. It replaces Creative's mobile app: lighting (including screen sync from a PC),
volume, input/output, sound modes, the Acoustic Engine, EQ, CrystalVoice, Scout Mode and the mixer.

Every command it can send is a byte sequence that Creative's own app was **captured** sending to this
soundbar (firmware `1.3.230619.1820`). The decode, with evidence for every opcode, is in
[`docs/protocol.md`](docs/protocol.md). The design is in
[`docs/superpowers/specs/`](docs/superpowers/specs/2026-10-07-sb-katana-integration-design.md).

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

## Entities

One device, **Sound Blaster Katana V2X**. "Gate" names the command family each write belongs to. See
[Safety](#safety) for what an unconfirmed family means.

### Light

| Entity | What it does | Gate |
|---|---|---|
| **Lighting** (`light`) | On/off. RGB colour, which sets the bar to one solid colour (the "Solo" effect). Brightness, done by scaling the colour, because the soundbar has no brightness control of its own and the app never sends one. Effects: the app's nine presets — Aurora, Cycle, Mood Orange, Morph Cyan, Pulsate Red, Solo White, Wave Green, Wave Ice Blue, Wave Rainbow. | on/off `light_power`, colour/brightness `light_solo` — **confirmed**; effects `light_preset` |

The light's state does **not** follow screen-sync frames, and a colour change Home Assistant did not cause
(ambience-rgb over USB, the remote) is published at most once every 30 s. On/off is always published at once.

### Media player

| Entity | What it does | Gate |
|---|---|---|
| **Sound Blaster Katana V2X** (`media_player`) | Volume (speaker level 0–50 shown as 0–1, step 2 %), mute, source (TV, USB Audio, Optical, Aux, Bluetooth), sound mode (the modes stored on the soundbar, e.g. "Music.", "Gaming.", "Voice.", "Effects Off") | `volume`, `mute`, `input`, `sound_mode` |

Changing the volume also unmutes, as it does on the soundbar itself. The source list is read from the
soundbar. USB Audio is certain; the other four labels follow the order in which the soundbar lists its
inputs. The long list of game presets in Creative's app lives in the app, not on the soundbar, so it is not
offered.

### Switches

| Entity | What it does | Gate |
|---|---|---|
| **Screen sync** | On by default. While on, colours posted by the PC are shown. Any manual lighting change turns it off; switch it back on to resume. Switching it off does not turn the lighting off. Restored across restarts. | — |
| **Hold connection** (config) | On: keep the BLE link up and reconnect after drops (backoff 5 s → 5 min). Off: release the link so Creative's app can connect; entities become unavailable. Restored across restarts: setup connects once to read the firmware, then lets go again. | — |
| **Scout Mode** | Scout Mode on/off | `scout` |
| **Auto switch to TV/HDMI** (config) | Switch to TV/HDMI automatically when it requests | `auto_switch` |
| **Equalizer** | EQ on/off for the current output | `eq_enable` |
| **Surround** / **Crystalizer** / **Smart Volume** / **Dialog+** | Acoustic Engine effects on/off for the current output | `acoustic` |
| **Microphone Smart Volume** / **Microphone Equalizer** / **Microphone Focus** | CrystalVoice on/off | `crystalvoice` |

### Selects

| Entity | Options | Gate |
|---|---|---|
| **Input** | Read from the soundbar: TV, USB Audio, Optical, Aux, Bluetooth. Also on the media player | `input` |
| **Sound mode** | The modes stored on the soundbar, e.g. "Music.", "Gaming.", "Voice.", "Effects Off". Also on the media player. After a setting is changed live, the soundbar reports its live copy, which it renames **"Onboard"**: that name is then the current option, with attribute `modified: true`. Picking a stored mode loads it (and drops the live changes); picking "Onboard" sends nothing | `sound_mode` |
| **Output** | Speakers, Headphones | `output` |
| **Decoder** | Normal, Full, Night (Dolby dynamic range control) | `decoder` |
| **EQ preset** | Gaming, Music, Movies, Footsteps Enhancer: the four presets whose full curves were captured from the app | `eq_preset` |
| **Smart Volume mode** | Mode 1, Mode 2, Mode 3. The soundbar stores 0/1/2; the app's labels for them were not captured | `smart_volume_detail` |

### Numbers

| Entity | Range | Gate |
|---|---|---|
| **Surround level**, **Crystalizer level**, **Dialog+ level** | 0–100 | `acoustic` |
| **Smart Volume level** | 0–100 | `smart_volume_detail` |
| **Line In level**, **SPDIF In level**, **Microphone level** | 0–100 % in steps of 2 | `mixer` |
| **What U Hear level** | 0–100 % in steps of 2 | `what_u_hear` |
| **Headphones level** | 0–100 % in steps of 2. **Disabled by default**: reported not working, and not verifiable without headphones | `headphones_level` |
| **Subwoofer** | −10 … +6 dB | `subwoofer` |

Acoustic Engine, Decoder and EQ settings exist separately for Speakers and Headphones. These entities show
and change the side that matches the current **Output**, exactly as the app's two tabs do.

### Diagnostics

| Entity | What it does |
|---|---|
| **Firmware** (`sensor`) | The soundbar's firmware version |
| **Screen sync receiving** (`binary_sensor`) | On while the PC is streaming. It changes only at the first frame and at the hand-over |
| **Re-read state** (`button`) | Reads every value back from the soundbar (reads only) |

Downloadable diagnostics redact the address and serial number.

## Options

| Option | Default | Range | Meaning |
|---|---|---|---|
| **Allow unconfirmed controls** | off | — | Allows writes in families the owner has not yet confirmed live (see [Safety](#safety)). Turn it on to run the live checklist. |
| **Screen sync rate** | 10 | 1–20 writes/s | The most colours per second sent to the soundbar. The newest colour always wins, and a colour equal to the last one is not re-sent. |
| **Screen sync hand-over** | 10 s | 10–120 s | With no frame for this long, the lighting is turned off once. Screen sync stays on, so the next frame resumes. The minimum stays above the PC's 5 s keepalive, so a static screen never blinks off and on. |

Changing an option reloads the integration, which briefly reconnects.

## Screen sync from a PC

The PC posts colours to an authenticated HTTP endpoint:

```
POST /api/sb_katana/stream
Authorization: Bearer <long-lived access token>
Content-Type: application/json

{"rgb": [r, g, b]}                    # 0-255 each
{"rgb": [r, g, b], "config_entry_id": "<id>"}   # only with more than one soundbar
```

| Response | Meaning |
|---|---|
| `200 {"accepted": true}` | Taken: it will be shown, subject to the rate limit |
| `200 {"accepted": false}` | Screen sync is off; the frame was dropped |
| `400` | Bad body: not JSON, not three integers 0–255 |
| `401` | Missing or bad token |
| `404` | No loaded soundbar, or several and no `config_entry_id` |

Send on every colour change, and **at least every 5 s** even when nothing changes, so the 10 s hand-over
does not fire. On a clean stop simply stop sending; the hand-over turns the lights off.

Why an endpoint and not a service: every HA service call fires a `call_service` event, and the recorder
stores events. At 10 Hz that is about 36,000 rows an hour. The endpoint fires nothing. The equivalent
service, **`sb_katana.stream_frame`**, exists for automations and tests:

| Field | Required | Meaning |
|---|---|---|
| `rgb` | yes | `[r, g, b]`, 0–255 each |
| `config_entry_id` | no | Only needed with more than one soundbar |

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
- **The confirmation gate.** A command family is enabled by default only once the owner has seen or heard it
  work over BLE. As of 2026-10-07 that is every family except **Input**, **Sound mode** (not yet tried) and
  **Headphones level** (reported not working). Those three work only with **Allow unconfirmed controls** on,
  until they are confirmed and enabled in `families.py`.
- **State comes only from the soundbar.** A value changes when the soundbar reports it or acknowledges a
  write. A refusal (status ≠ 0) keeps the old value. No answer means the outcome is unknown: the value is
  cleared and re-read. The firmware (and so the write gate) is re-read on every reconnect. Nothing is written
  on a timer. The 60 s poll is reads only, and it also re-reads anything still unknown.
- **Flash.** The soundbar saves settings to flash only after it has been idle (measured), so wear scales
  with how often a value settles, not with how fast it is written.

## Development

```bash
python3.14 -m venv ~/.local/share/venvs/ha-katana      # never a venv inside the repo
~/.local/share/venvs/ha-katana/bin/pip install -r requirements_test.txt
~/.local/share/venvs/ha-katana/bin/pytest -q tests
~/.local/share/venvs/ha-katana/bin/ruff check custom_components tests tools
```

| Path | What |
|---|---|
| `custom_components/sb_katana/protocol.py` | Pure byte layer: framing, the allowlist, every builder and parser |
| `custom_components/sb_katana/captured.py` | **Generated** by `tools/extract_sequences.py` from a capture: the app's preset loads, verbatim |
| `custom_components/sb_katana/families.py` | Command families and the confirmation gate |
| `custom_components/sb_katana/device.py` | State, the one-exchange-at-a-time I/O, the writer queue, intents |
| `custom_components/sb_katana/transport.py` | bleak through HA's Bluetooth stack |
| `custom_components/sb_katana/stream.py`, `api.py` | Screen sync, the HTTP endpoint and the service |
| `tools/` | Capture decoders (`frames.py`, `pairs.py`) and the sequence generator |
| `tests/` | Golden vectors, guards, a fake soundbar answering with captured replies, HA-harness tests |

CI runs ruff and pytest on Python 3.14 and hassfest. HACS validation is left out while the repository is
private, because it reads the repository through the API and cannot see a private one. Add
`hacs/action` back if the repository is made public.

## Licence

MIT (`LICENSE`); attribution in `NOTICE`. Parts of `protocol.py` are translated from the [`v2x`](https://git.dog/xx/v2x) crate by Rasmus Moorats
(MIT).
