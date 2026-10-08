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
| **Lighting** (`light`) | On/off. RGB colour, which sets the bar to one solid colour (the "Solo" effect). Brightness is the soundbar's own **Global Brightness**. Effects: the app's nine presets — Aurora, Cycle, Mood Orange, Morph Cyan, Pulsate Red, Solo White, Wave Green, Wave Ice Blue, Wave Rainbow. | on/off `light_power`, colour `light_solo`, effects `light_preset`, brightness `light_brightness` |

The light's state does **not** follow screen-sync frames, and a colour change Home Assistant did not cause
(Creative's app, the remote) is published at most once every 30 s. On/off is always published at once.

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
| **Screen sync** | On by default. While on, colours posted by the PC are shown. A manual lighting choice turns it off — a colour, an effect, or switching the bar on from off; switch it back on to resume. Changing only the **brightness** of a lit bar does not (Global Brightness is the soundbar's own setting and screen-sync colours keep flowing under it). Switching it off does not turn the lighting off. Restored across restarts. | — |
| **Hold connection** (config) | On: keep the BLE link up and reconnect after drops (backoff 5 s → 5 min). Off: release the link so Creative's app can connect; entities become unavailable. Restored across restarts: setup connects once to read the firmware, then lets go again. | — |
| **Scout Mode** | Scout Mode on/off | `scout` |
| **Auto switch to TV/HDMI** (config) | Switch to TV/HDMI automatically when it requests | `auto_switch` |
| **Equalizer** | EQ on/off for the current output | `eq_enable` |
| **Surround** / **Crystalizer** / **Smart Volume** / **Dialog+** | Acoustic Engine effects on/off for the current output | `acoustic` |
| **Microphone Smart Volume** / **Microphone Equalizer** / **Microphone Focus** | CrystalVoice on/off | `crystalvoice` |
| **Energy saving** (config) | Network standby after 15 min of no operation | `energy_saving` |
| **HDMI CEC standby link** (config) | Follow the TV's standby over HDMI CEC | `cec_link` |

### Selects

| Entity | Options | Gate |
|---|---|---|
| **Input** | Read from the soundbar: TV, USB Audio, Optical, Aux, Bluetooth. Also on the media player | `input` |
| **Sound mode** | The modes stored on the soundbar, e.g. "Music.", "Gaming.", "Voice.", "Effects Off". Also on the media player. After a setting is changed live, the soundbar reports its live copy, which it renames **"Onboard"**: that name is then the current option, with attribute `modified: true`. Picking a stored mode loads it (and drops the live changes); picking "Onboard" sends nothing | `sound_mode` |
| **Output** | Speakers, Headphones | `output` |
| **Decoder** | Normal, Full, Night (Dolby dynamic range control) | `decoder` |
| **EQ preset** | Gaming, Music, Movies, Footsteps Enhancer, Flat: the presets whose full curves were captured from the app. After a band edit the live EQ is called "Onboard", which is then shown as the current option | `eq_preset` |
| **Smart Volume mode** | Manual (the level slider), Loud, Night | `smart_volume_detail` |
| **Microphone priority** | Auto, Headset Microphone, Microphone Array (labels inferred from tap order) | `mic_priority` |
| **Microphone equalizer** | Off, or one of the app's eleven presets (labels inferred from tap order) | `mic_eq_preset` |
| **Auto standby** (config) | 28 hours, 8 hours, 2 hours, 1 hour, 30 minutes, Never — time to full standby | `auto_standby` |
| **Display** (config) | Bright, Dark, Off (Dark/Off inferred from tap order) | `display` |

**Option keys.** Since 0.2.0 the selects with a fixed list report a *key* as their state, and the UI shows
it translated (English, Hungarian). Use the key in automations and in `select.select_option`:

| Select | Keys (in order) |
|---|---|
| Input | `tv`, `usb_audio`, `optical`, `aux`, `bluetooth` (only those the soundbar lists) |
| Output | `speakers`, `headphones` |
| Decoder | `normal`, `full`, `night` |
| Smart Volume mode | `manual`, `loud`, `night` |
| Microphone priority | `auto`, `headset_microphone`, `microphone_array` |
| Microphone equalizer | `off`, `reduce_bass_harshness_improve_clarity`, `reduce_bass_improve_vocal_and_clarity`, `reduce_harshness_improve_vocal`, `reduce_bass_improve_vocal`, `improve_vocal_reduce_harshness`, `reduce_bass_improve_clarity`, `reduce_vocal_improve_bass_and_clarity`, `reduce_harshness_improve_vocal_and_clarity`, `reduce_harshness_improve_clarity`, `improve_clarity`, `improve_vocal_and_clarity` |
| Auto standby | `28_hours`, `8_hours`, `2_hours`, `1_hour`, `30_minutes`, `never` |
| Display | `bright`, `dark`, `off` |

A key is the English label in lower case with every other run of characters turned into one `_`
(`select.option_key`). **Sound mode** and **EQ preset** keep the names the soundbar itself uses ("Music.",
"Gaming.", "Onboard", "Footsteps Enhancer"), because the soundbar names them; the media player's source list
also keeps the plain labels.

### Numbers

| Entity | Range | Gate |
|---|---|---|
| **Surround level**, **Crystalizer level**, **Dialog+ level** | 0–100 | `acoustic` |
| **Smart Volume level** | 0–100 | `smart_volume_detail` |
| **Line In level**, **SPDIF In level**, **Microphone level** | 0–100 % in steps of 2 | `mixer` |
| **What U Hear level** | 0–100 % in steps of 2 | `what_u_hear` |
| **Headphones level** | 0–100 % in steps of 2. **Disabled by default**: reported not working, and not verifiable without headphones | `headphones_level` |
| **Subwoofer** | −10 … +6 dB ("Bass (dB)" in the app) | `subwoofer` |
| **EQ 31 Hz** … **EQ 16 kHz** | −9 … +9 dB in steps of 0.5, for the current output. Each change writes all ten bands, as the app does, and marks the live EQ custom ("Onboard") | `eq_bands` |
| **Microphone focus angle** | 20 … 180° | `focus_angle` |

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

The PC side is [ambience-rgb](https://github.com/Jxn01/ambience-rgb)'s `[katana_ha]` sink, live since
2026-10-07 on both halves of the owner's rig (it replaced ambience-rgb's own USB driver for the soundbar,
which was then removed). Any other program can do the same. The PC posts colours to an authenticated HTTP
endpoint:

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

`accepted: false` is normal, not an error: **any manual colour, effect or power-on in Home Assistant switches Screen
sync off**, on purpose, and frames are dropped until it is switched back on. A sender should say so once
rather than retry (ambience-rgb logs a warning).

`GET` on the same path, with the same token, answers the stream's status and changes nothing — no write, no
event, no state change. ambience-rgb's `devices` command prints it.

```
GET /api/sb_katana/stream[?config_entry_id=<id>]
```

| Field | Meaning |
|---|---|
| `screen_sync` | The **Screen sync** switch. `false`: every frame is dropped |
| `receiving` | Frames are arriving (the **Screen sync receiving** sensor) |
| `available` | The soundbar's Bluetooth link is up |
| `rate_hz` | The **Screen sync rate** option |
| `timeout_s` | The **Screen sync hand-over** option, in seconds |
| `frames_received` | Frames accepted since the integration loaded |
| `frames_dropped` | Frames dropped because Screen sync was off |
| `writes_sent` | Colour batches sent to the soundbar |
| `write_errors` | Batches that did not reach it |

It answers `401` without a valid token and `404` like the `POST`.

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
  work over BLE. Since 2026-10-08 that is **every family except Headphones level** (reported not working;
  headphones are not used with this soundbar, so its entity is also disabled by default). The third capture's
  families — `light_brightness`, `eq_bands`, `focus_angle`, `energy_saving`, `auto_standby`, `cec_link`,
  `mic_priority`, `mic_eq_preset`, `display` — were tried from HA by the owner and confirmed on 2026-10-08,
  including the labels that had been inferred from tap order. **Allow unconfirmed controls** now only matters for
  Headphones level.
- **State comes only from the soundbar.** A value changes when the soundbar reports it or acknowledges a
  write. A refusal (status ≠ 0) keeps the old value. No answer means the outcome is unknown: the value is
  cleared and re-read. The firmware (and so the write gate) is re-read on every reconnect. Nothing is written
  on a timer. The 60 s poll is reads only, and it also re-reads anything still unknown.
- **Flash.** The soundbar saves settings to flash only after it has been idle (measured), so wear scales
  with how often a value settles, not with how fast it is written.

## Look and language

- **Brand images** in `custom_components/sb_katana/brand/` (`icon.png` 256², `icon@2x.png` 512²,
  `logo.png` 512×256, `logo@2x.png` 1024×512). Home Assistant 2026.9+ serves a custom integration's own
  `brand/` folder, so the integrations page, the device page and the config flow show the Sound Blaster mark
  instead of the placeholder. Source: the classic Sound Blaster logo,
  [`File:Sound Blaster logo.svg`](https://commons.wikimedia.org/wiki/File:Sound_Blaster_logo.svg) on Wikimedia
  Commons, marked public domain (simple text and shapes). The square icon is the same two bands, made taller,
  with the original lettering; nothing was redrawn. It is opaque on purpose, so no `dark_` variant is needed.
- **Icons** for every entity, state-dependent where useful (screen sync on/off, input, output, display,
  standby), and for the `stream_frame` service: `icons.json`.
- **Languages:** English and **Hungarian** (`translations/hu.json`): entity names, select options, the
  config and options flows, the repair issue, the service, and every error a user can see. Errors keep an
  English message for logs; the UI shows the translated one.
- `tests/test_ui.py` fails the build if an entity lacks an icon or a name in either language, a select option
  lacks a translation, Hungarian and English drift apart (keys or placeholders), a user-visible `raise` has no
  translation key, or a brand image breaks the brands spec. hassfest checks only the format of `strings.json`,
  `translations/en.json` and `icons.json` (an icon must start with `mdi:`); whether an MDI name exists, and every
  other language, are this test's job.

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
| `custom_components/sb_katana/icons.json`, `translations/`, `brand/` | Icons, English + Hungarian text, brand images |
| `tests/` | Golden vectors, guards, a fake soundbar answering with captured replies, HA-harness tests |

CI runs ruff and pytest on Python 3.14 and hassfest. HACS validation is left out while the repository is
private, because it reads the repository through the API and cannot see a private one. Add
`hacs/action` back if the repository is made public.

## Licence

MIT (`LICENSE`); attribution in `NOTICE`. "Sound Blaster", "Katana" and "Creative" are trademarks of
Creative Technology Ltd; the logo is used only to identify the device this integration talks to, and this
project is not affiliated with or endorsed by Creative. Parts of `protocol.py` are translated from the [`v2x`](https://git.dog/xx/v2x) crate by Rasmus Moorats
(MIT).
