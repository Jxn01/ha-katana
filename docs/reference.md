# Reference

Every entity, option and the screen-sync endpoint of the `sb_katana` integration.

## Entities

One device, **Sound Blaster Katana V2X**. "Gate" names the command family each write belongs to. See
[Safety](../README.md#safety) for what an unconfirmed family means.

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
| **Hold connection** (config) | On: keep the BLE link up and reconnect after drops — backoff 5 s → 5 min, then a blind retry every 15 min, and **at once** when screen-sync colours arrive or the soundbar is heard advertising (at most once a minute). In standby the soundbar turns its Bluetooth off, so it is *unavailable* at night by design; frequent blind retries (each an active scan) measurably knocked other BLE devices on the same adapter off their links. Off: release the link so Creative's app can connect; entities become unavailable. Restored across restarts: setup connects once to read the firmware, then lets go again. | — |
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
| **Allow unconfirmed controls** | off | — | Allows writes in command families not yet confirmed working on a real soundbar (see [Safety](../README.md#safety)). |
| **Screen sync rate** | 10 | 1–20 writes/s | The most colours per second sent to the soundbar. The newest colour always wins, and a colour equal to the last one is not re-sent. |
| **Screen sync hand-over** | 10 s | 10–120 s | With no frame for this long, the lighting is turned off once. Screen sync stays on, so the next frame resumes. The minimum stays above the PC's 5 s keepalive, so a static screen never blinks off and on. |

Changing an option reloads the integration, which briefly reconnects.

## Screen sync from a PC

The PC side is [ambience-rgb](https://github.com/Jxn01/ambience-rgb)'s `[katana_ha]` sink; any other program can do
the same. The PC posts colours to an authenticated HTTP endpoint:

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
