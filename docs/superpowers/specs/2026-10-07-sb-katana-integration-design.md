# sb_katana — Home Assistant integration for the Sound Blaster Katana V2X

Sub-project **2 of 3** of "replace the Creative app with HA" (decided by the owner 2026-10-07; recorded in
the KB, `10-jxn-garuda.md`). Sub-project 1, the protocol decode, is `docs/protocol.md`. Sub-project 3 is
ambience-rgb pushing screen colours to this integration; its contract is section 9, and it is built on an
ambience-rgb branch.

> **Status, 2026-10-07 evening: all three sub-projects are done.** Sub-project 3 was merged to ambience-rgb
> `main` and switched over live the same day (the owner's word), verified end to end: frames arriving, the bar
> following, and the hand-over turning it off 10 s after the last one. ambience-rgb's USB driver was then
> removed (its commit `05d0bad`). See "As built" under section 9 for where the build departs from this design.

## 1. What the owner asked for, and what was agreed

**Asked.** HA replaces the Creative app completely, over Bluetooth, because HA is always on and the PC
is not. Scope is **everything the app sends**: lighting, EQ and audio routing, Super X-Fi and sound effects,
volume and input. The integration must not damage the soundbar or wear out its flash.

**Agreed in the design conversation (owner, 2026-10-07 00:2x):**

- HA is the only thing that talks to the soundbar, over BLE. ambience-rgb stops using USB once
  sub-project 3 is proven.
- When the PC sends nothing for **10 s**, the integration turns the lighting **off**. This hand-over does
  not count as a manual change.
- A **"Screen sync" switch** is on by default. A manual lighting change from HA turns it off; switching it
  back on resumes the stream.
- Screen colours arrive as a **custom service over REST**, `sb_katana.stream_frame` with `{"rgb": [r, g, b]}`.
  A frame writes BLE **without** a per-frame entity state change, so the recorder stores nothing per frame.
  (HA has no recorder exclusions, and its database is 195 MB.)
- The default stream rate is **10 Hz** and configurable. The newest frame wins, repeated colours are not
  re-sent, and the PC sends a keepalive at least every 5 s.
- On connect the integration reads state back and never blindly rewrites it. There are no periodic
  refresh writes.
- A single writer queue sends every BLE write; manual commands go ahead of stream frames.
- A missing reply means the state is **unknown**, never assumed.
- Opcodes are allowlisted, and guard tests ban the firmware and debug builders.
- The transport knows **only** the command characteristic.
- On any firmware other than **1.3.230619.1820**, the integration raises a repair issue and refuses
  writes. It never offers a firmware update.
- **A command family is enabled by default only after the owner has confirmed it live.** Before that, it
  needs bytes from the app's traffic, a hypothesis, a builder plus a golden test, and a safety review
  showing it is reversible.

**Success:** everything the owner uses in the Creative app works from HA, screen sync runs through HA with
no recorder churn, and nothing can send a byte sequence the app never sent.

## 2. Scope decisions forced by the capture

The capture (`docs/protocol.md`) settles most of the scope:

| Feature | Decision | Why |
|---|---|---|
| Lighting on/off, solid colour | **In** | Proven over BLE on 2026-10-06, and the owner saw the bar turn blue |
| The app's 9 lighting presets | **In** — replayed verbatim | Every frame captured and ACKed |
| Lighting brightness | **In as software dimming** (scale the solid colour) | The app has no brightness command, so a `3a 27` write would be a byte sequence it never sent |
| Output, input, auto-switch, volume, mute, sound mode, decoder, scout, acoustic engine, EQ on/off, CrystalVoice toggles, mixer levels | **In** | Captured with readback |
| EQ preset select | **In, the 4 captured presets** (Gaming, Music, Movies, Footsteps Enhancer) | Preset curves live in the app, and only these four were captured whole |
| Subwoofer level, headphones level, What U Hear level, Smart Volume level and mode | **In, as "probable"** | The bytes are captured; the meaning is inferred from timing |
| Main EQ band sliders, bass, treble | **Out (read-only later)** | No band drag was captured |
| Super X-Fi | **Out** | Zero frames — greyed on Speakers and never toggled |
| Focus wedge angle | **Out** | Range unknown (seen 29.6–55°) |
| Microphone EQ presets, mic priority | **Out** | App-side curves; priority semantics unclear |
| Sound-mode create, rename, delete; app-side mode templates | **Out** | Editor path; the device stores only its own slots, and selecting those is in |
| Custom Buttons | **Out** | Not captured |

Each "Out" row is a checklist item for a future capture, not a dead end.

## 3. Architecture

```
custom_components/sb_katana/
  __init__.py       setup/unload, KatanaDevice per entry, service registration
  manifest.json     bluetooth matcher local_name "Control for MF8400*", deps bluetooth_adapters
  const.py          domain, UUIDs, defaults, option keys
  protocol.py       PURE: framing, reassembly, ACK parsing, every builder + parser, the allowlist
  captured.py       GENERATED: the app's preset sequences (tools/extract_sequences.py)
  families.py       command families: tier, confirmed flag, the builders each family may use
  transport.py      bleak via HA's bluetooth stack; one write char, one notify char; request/reply matching
  device.py         KatanaDevice: state model, connect + read-back, notification→state, writer queue, gate
  stream.py         StreamController: stream_frame intake, rate limit, dedup, 10 s hand-over
  entity.py         KatanaEntity base (device info, availability, listener)
  light.py  media_player.py  switch.py  select.py  number.py  sensor.py  binary_sensor.py  button.py
  config_flow.py    bluetooth discovery + user step + options flow
  diagnostics.py    redacted state dump
  services.yaml  strings.json  translations/en.json
```

Each unit has one purpose:

- **`protocol.py`** knows bytes and nothing about HA or BLE. Every frame the integration can send is
  built here, and the encoder refuses any frame whose opcode/sub-command is not in `ALLOWED_TX`.
- **`transport.py`** knows BLE and nothing about meaning. It writes whole frames to `9e9daaec`
  (Write Command), subscribes to `9e9daaeb`, reassembles notifications into frames, and lets a caller
  await "the next frame matching this predicate" with a timeout. It holds exactly one characteristic
  UUID for writing, and a guard test fails if any other UUID appears in it.
- **`device.py`** owns state. Callers ask for intents (`set_volume(30)`); it checks the family gate,
  queues the frames, and updates state **only** from what the device says (ACK status `00`, or the state
  notification that follows). No reply means unknown, and the field re-reads.
- **`stream.py`** turns REST frames into at most N solid-colour writes per second, and owns the 10 s
  timer.

### 3.1 Connection

`bluetooth.async_ble_device_from_address(hass, addr, connectable=True)` →
`bleak_retry_connector.establish_connection(BleakClientWithServiceCache, …)`. The connection is held
persistently, because streaming needs it, and reconnects with backoff after a drop (the disconnect callback
marks entities unavailable). A **"Hold connection"** config switch, on by default, releases the link so the
Creative app can connect: the soundbar takes one central at a time. HA's bluetooth stack gives the
advertisement, so the device needs no pairing.

At connect the integration reads, in this order:

1. `03`
2. firmware `09 02` (gate)
3. serial `09 03`
4. output `2c 01`
5. input `9c 01`, `9c 02`
6. auto-switch `67 0d`
7. levels `23 01 ch` and mutes `24 01 ch` for every channel
8. subwoofer `40 03`
9. scout `26 08 ff ff`
10. active mode `a7 01`, mode names `a7 06 01–0a 00`
11. live mode params `a7 13 00 <sub> …` for the current output's sub
12. live EQ name `a8 06 00 00 <sub>`
13. CrystalVoice `11 …` (`952c 9513 9506`)
14. lighting `3a 26`, `3a 2a 00`, `3a 37`/count, `3a 2c 00 01 01 07`, `3a 32 00`

Reads only.

**MTU.** The transport logs `mtu_size`. It refuses (and logs) any frame longer than `mtu − 3` rather than
fragmenting, because the protocol has no fragmentation for `5A` frames.

### 3.2 The writer queue

One asyncio task drains a two-level queue:

- **manual** — FIFO, always first;
- **stream** — a single slot overwritten by each new frame.

A write is one or more frames. For a multi-frame preset load, the frames are sent back to back, with the
app's own spacing floor of 30 ms. A manual command waits for its ACK, with a 2 s timeout. Stream writes
await the ACK when one is already due, but never queue behind each other.

### 3.3 State and notifications

`KatanaState` is a dataclass of `| None` fields (`None` = unknown). Every inbound frame passes through
`apply_frame(state, frame)` in `device.py`, a pure function covered by tests. Unsolicited notifications
(the volume knob, if it sends them) therefore update HA for free. Unknown opcodes are ignored.

A **60 s poll re-reads** output, input, level and mute for ch00, the active mode and lighting power. It is
cheap, read-only, and catches knob or remote changes in case they do not notify.

## 4. Entities

One device, "Sound Blaster Katana V2X" (model MF8400, firmware and serial from the reads). In the table,
**tier** marks write confidence: **C** = confirmed by readback and screenshot, **P** = probable.
**Confirmed live** marks families the owner has already seen working over BLE.

| Entity | Reads | Writes | Tier | Confirmed live |
|---|---|---|---|---|
| `light` Lighting — on/off, RGB, brightness (software), effect = the 9 presets | `3a 26/2a/2c/32` | `3a 25`; solo colour via `25 01, 37 00 01, 29 00 03, 2b 00 01 01 <abgr>`; preset = captured sequence | C | **power + solid colour: yes**; presets: no |
| `switch` Screen sync | — (integration state, restored) | — | — | n/a |
| `binary_sensor` Screen sync receiving | stream activity (changes at start/stop only) | — | — | n/a |
| `media_player` Katana — volume (ch00 ÷ 50), mute, source, sound mode | `23/24 ch00`, `9c`, `a7 01/06` | `23 00 00 v 00 00`, `24 00 00 m`, `9c 00 id 00`, `a7 00 slot` | C (USB source certain; other labels probable-high) | no |
| `select` Output | `2c 01` | `2c 00 {02,24} 00 00 00` | C | no |
| `select` Decoder (Normal/Full/Night) | `a7 13 … 04.00` | `a7 12 00 sub 01 04 00 f32` | C | no |
| `select` EQ preset | `a8 06 00 00 sub` | captured EQ sequence | C | no |
| `select` Smart Volume mode (Mode 1–3) | `01.08` | `a7 12 … 01 08` | P | no |
| `switch` Auto switch to TV/HDMI | `67 0d` | `67 0c b` | C | no |
| `switch` Scout Mode | `26 08 ff ff` | `26 07 02 00 b 00` | C | no |
| `switch` Equalizer | `00.00` | `a7 12 … 00 00` | C | no |
| `switch` Surround / Crystalizer / Smart Volume / Dialog+ | `01.00/.02/.06/.09` | `a7 12 …` | C | no |
| `switch` Mic Smart Volume / Mic Equalizer / Mic Focus | `11 952c/9513/9506` | `12 01 <id> f32` | C | no |
| `switch` Hold connection (config) | — | — | — | n/a |
| `number` Surround / Crystalizer / Dialog+ level (0–100) | `01.01/.03/.0a` | `a7 12 …` | C | no |
| `number` Smart Volume level (0–100) | `01.07` | `a7 12 …` | P | no |
| `number` Line In / SPDIF In / Microphone level (0–100 %, step 2) | `23 01 04/03/05` | `23 00 ch v 00 00` | C | no |
| `number` Headphones / What U Hear level | `23 01 01/06` | same | P | no |
| `number` Subwoofer (−10…+6) | `40 03` | `40 04 01 <i16>` | P | no |
| `sensor` Firmware (diagnostic) | `09 02` | — | — | n/a |
| `button` Re-read state (diagnostic) | runs the connect read set | — | — | n/a |

**Acoustic engine, decoder and EQ-enable writes** go to live slot `00`, sub `00` while the output is
Speakers and sub `02` while it is Headphones, exactly as the app does on each tab. The store's 4-byte
values are typed per key: `00.01` and `03.01` are **u32**, everything else is f32. A guard test fails if a
u32 key is ever encoded as a float.

**Light effects.** Effect = the live preset name (`3a 32 00`) when the live mode and colour count match that
preset; a solid colour (mode `03`, count 1) shows no effect. The light entity's state does not change per
stream frame.

## 5. Safety

1. **The allowlist** (`protocol.ALLOWED_TX`) lists every `(opcode, first payload byte)` the integration can
   emit, and every entry has a golden test against bytes from the capture.
2. **Guard tests**, each with a positive control that proves the pattern bites:
   - no builder or captured sequence emits `0x53`, `0x54` or `0x98`, or starts with `0x5B`;
   - every frame in `captured.py` passes the allowlist;
   - `transport.py` names no UUID but the two command-channel ones, and writes only `9e9daaec`;
   - no f32 encoding of `00.01`/`03.01`.
3. **The family gate.** Every write belongs to a family in `families.py` with `confirmed: bool`. An
   unconfirmed family raises `HomeAssistantError` ("not yet confirmed live — see the checklist")
   unless the options flow's **"Allow unconfirmed controls"** is on. That toggle exists for the owner's
   morning checklist. After it, confirmed families flip to `True` in code.
4. **Firmware gate.** On anything other than `1.3.230619.1820`, all writes refuse and a repair issue
   explains why. There is no update entity, ever.
5. **ACK status.** Any non-zero status raises and marks the field unknown.
6. **Flash.** Writes go out only on intent or stream change, never on a timer. The firmware saves after
   it goes idle (measured 2026-10-07), so wear follows how often a value settles, not the write rate.

## 6. Stream

**Transport change from the conversation, made during the build (2026-10-07 03:1x):** the PC does **not**
call the `sb_katana.stream_frame` *service* per frame. `ServiceRegistry.async_call` fires a `call_service`
bus event for every call (`homeassistant/core.py`), and with no recorder exclusions every event becomes a
row in the `events` table. At 10 Hz that is ~36,000 rows an hour — exactly the churn the design ruled out,
just in a different table. So the PC posts to an **authenticated REST endpoint** instead, which fires no bus
event. It is still REST, still a Bearer token, still matterlights' `requests` pattern:

```
POST /api/sb_katana/stream          Authorization: Bearer <long-lived token>
{"rgb": [r, g, b]}                  optional "config_entry_id"
-> 200 {"accepted": true|false}     false while Screen sync is off
-> 400 on a bad body, 404 if no soundbar is set up
```

The `sb_katana.stream_frame` service still exists, with the same fields, for automations and manual tests.
Both paths call the same `StreamController.handle_frame`.

- The handler validates the frame, records `last_frame_at`, and stores the colour in the stream slot. It
  never touches entity state.
- If Screen sync is off, the frame is dropped silently, and only counted for diagnostics.
- The writer sends at most `stream_rate_hz` frames per second (option, default 10, range 1–20), newest
  first, and skips a colour equal to the last one sent.
- The first frame after idle or a hand-over sends `prepare` (lighting power on, colour count 1, solo
  mode), then the colour. This is the same sequence ambience-rgb uses.
- **Prepare is re-sent** whenever a batch fails to reach the soundbar and after every (re)connect, and it is
  carried into a batch that replaces it before it went out (review finding, 2026-10-07).
- **Hand-over.** With no frame for `stream_timeout_s` (option, default 10, range 10–120 so it never undercuts the
  PC's 5 s keepalive), the integration sends lighting
  power off once and marks the stream idle. Screen sync stays on, so the next frame resumes.
- **Manual change.** Any light service call (`turn_on`, `turn_off`, effect, colour) switches Screen sync off
  first, then executes.
- **Switching Screen sync off** stops applying frames and cancels the hand-over timer. It does **not** turn
  the lighting off: the light keeps its last colour until something else changes it.
- The binary sensor flips on the first frame and at the hand-over, so it adds two recorder rows per
  session.

## 7. Errors

| Situation | Behaviour |
|---|---|
| Not reachable | entities unavailable; reconnect with backoff (5 s → 5 min) |
| ACK timeout | field unknown, re-read queued, error raised to the caller |
| Status ≠ 00 | `HomeAssistantError` with the status byte |
| Unknown frame | debug log, ignored |
| Frame > MTU | refused before sending, with an error |
| Firmware mismatch | repair issue, writes refused |
| Unconfirmed family | `HomeAssistantError` naming the checklist |

## 8. Testing

- **`tests/test_protocol.py`** — golden vectors: every builder matches the capture's bytes. Parsers decode
  the capture's replies to the expected values. The reassembler handles split and joined frames. ACK
  parsing covers each status.
- **`tests/test_guards.py`** — the guards in §5, each with a positive control.
- **`tests/test_captured.py`** — every captured sequence parses, passes the allowlist, and matches its
  generator's expectations (names, frame counts).
- **`tests/test_state.py`** — `apply_frame` over recorded notification runs from the capture.
- **`tests/test_stream.py`** — rate limit, dedup, newest-wins, the hand-over timer, and manual change
  turning Screen sync off, with a fake clock and a fake writer. **A 100-frame stream produces exactly one
  light state change** (the first on), checked against the HA state machine.
- **`tests/test_integration.py`** — `pytest-homeassistant-custom-component` with a fake transport replaying
  capture replies: config flow (discovery and user), setup, every entity's state after the read-back, every
  write emitting the expected frames, and the family gate refusing then allowing.
- **CI** — ruff check + format, pytest, hassfest, HACS validation (ha-petkit's workflows).
- **Live checks** — the morning checklist (owner's eyes and ears); see the KB.

## 9. Contract for sub-project 3 (ambience-rgb)

- A new sink in ambience-rgb POSTs `/api/sb_katana/stream` (§6; not the service URL) with
  `{"rgb": [r, g, b]}` and a long-lived token. On Linux the token lives in `.env.linux`, on Windows in `.env.windows`, both
  gitignored.
- It sends on colour change, and at least every 5 s as a keepalive.
- It never talks to the soundbar.
- When ambience-rgb stops, it simply stops posting, and the integration hands over after 10 s. On a clean
  stop the sink does not send black: the hand-over turns the lights off.
- It is built on a branch, and **the running daemon is not switched over** until the owner says so.

**As built (2026-10-07):**

- The token is read from `$AMBIENCE_RGB_HA_TOKEN`, else the config's `token_file`, else **`.ha-token` at the
  root of the ambience-rgb checkout**: gitignored and guarded by a hygiene test. One file serves both
  halves of the rig, because the checkout is on the drive both operating systems share. The owner ruled the
  same day that secrets may live on that drive as long as they never go public. The `.env.linux` /
  `.env.windows` split above was not needed.
- On a stop the sink **does** post black once, then falls silent. The integration writes black and turns the
  bar off at the hand-over. A dark screen ends the same way, instead of keeping the bar lit black.
- `accepted: false` (Screen sync off) is logged once per change by the sink, not treated as a failure.
- A `GET` on the endpoint answers the stream's status (README, "Screen sync from a PC") for ambience-rgb's
  `devices` command. Diagnostics report the same dictionary.
- ambience-rgb's USB driver is gone. `[katana] enabled = true` is refused with a pointer to `[katana_ha]`.

## 10. Deployment and overnight verification (without the owner)

Copy `custom_components/sb_katana` to HA's `/config/custom_components/` and restart Core. Add the entry
through the discovery flow over REST (the flow-driving pattern is in the KB, `13-haos.md`).

Overnight, without the owner:

- **all reads**, with every entity's state checked against `protocol.md`'s known values;
- the MTU logged;
- a recorder row count before and after a synthetic 100-frame stream of **the colour just read back**
  (ambience-rgb is still driving the bar over USB, so this is at most a sub-second revert), ending with
  Screen sync switched off before the 10 s hand-over so the lighting is never turned off;
- **no audio writes**, and **no preset loads**.

Everything that needs eyes or ears goes on the morning checklist.
