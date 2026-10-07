# sb_katana Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Home Assistant custom integration (`sb_katana`) that drives the Katana V2X over BLE with every
captured app feature, plus the `stream_frame` service for screen sync.

**Architecture:**

- `protocol.py` is a pure byte layer: builders return `Command` objects that carry their own reply matcher,
  and an allowlist gates the encoder.
- `transport.py` is a thin bleak wrapper through HA's bluetooth stack.
- `device.py` owns state, the writer queue and the family gate.
- `stream.py` owns rate, dedup and the hand-over.
- Entities are thin views over `KatanaDevice`.

**Tech Stack:** Python 3.14, Home Assistant 2026.9.3, bleak + bleak-retry-connector (shipped with HA),
pytest-homeassistant-custom-component 0.13.366, ruff.

**Spec:** `docs/superpowers/specs/2026-10-07-sb-katana-integration-design.md` (the protocol facts are in
`docs/protocol.md`).

## Global Constraints

- Domain `sb_katana`; device name "Sound Blaster Katana V2X"; model "MF8400".
- Write characteristic `9e9daaec-3a10-4fe8-b69f-7397aff77886`, notify `9e9daaeb-3a10-4fe8-b69f-7397aff77886`.
  No other UUID is used for I/O.
- Tested firmware `1.3.230619.1820`. On any other firmware, every write refuses.
- Never emit opcode `0x53`, `0x54` or `0x98`, nor a frame starting `0x5B`.
- The stream defaults to 10 Hz (range 1–20), with a 10 s hand-over.
- The store's u32 keys are `00.01` and `03.01`.
- Commits: `-c user.name='Norbert Olah' -c user.email='jxn.personal@gmail.com'` plus the session trailers.
- The venv lives at `~/.local/share/venvs/ha-katana`, **never in the repo**. Run tests with
  `~/.local/share/venvs/ha-katana/bin/pytest`.
- No real serial number or address in committed tests: use `Q8MF0000000000000W` and `FF:00:00:00:00:01`.

## Review Focus

1. **A reply split across two notifications**, or two replies in one: the reassembler yields whole frames
   either way (Task 1 test `test_reader_split_and_joined`).
2. **The soundbar out of range at HA start:** setup raises `ConfigEntryNotReady`, and HA retries without an
   error storm (Task 5 test `test_setup_not_ready_when_unreachable`).
3. **A stream frame arriving while a manual preset load is mid-sequence:** the preset's frames stay
   contiguous and the stream waits (Task 4 test `test_manual_sequence_not_interleaved`).
4. **The output switched to Headphones** (by the app or by HA): acoustic-engine reads and writes then target
   sub `02`, never sub `00` (Task 4 test `test_store_sub_follows_output`).
5. **`stream_frame` with bad input** (`[300, 0, 0]`, a missing key, 2 elements): a validation error, not a
   crash or a BLE write (Task 6 test `test_stream_frame_validation`).

---

### Task 1: protocol.py — framing, reassembly, ACKs, allowlist

**Files:**
- Create: `custom_components/sb_katana/__init__.py` (empty for now), `custom_components/sb_katana/protocol.py`,
  `pyproject.toml`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_protocol.py`

**Interfaces — Produces:**

- `MARKER = 0x5A`
- `@dataclass(frozen=True) Command(frame: bytes, reply_op: int | None, reply_prefix: bytes, ack: bool)` —
  `reply_op=None` means "no data reply expected"; `ack=True` means "an ACK is expected".
- `encode(op: int, payload: bytes) -> bytes` raises `ForbiddenCommand` unless `(op, payload[0] if payload
  else None)` is in `ALLOWED_TX`.
- `class FrameReader` with `feed(bytes)` and `frames() -> list[bytes]` — the ambience-rgb reader, plus the
  `0x5B` skip.
- `@dataclass Frame(op: int, payload: bytes)` and `parse(raw: bytes) -> Frame`.
- `@dataclass Ack(op: int, status: int, echo: bytes)` and `parse_ack(frame: Frame) -> Ack | None`.
- `matches_reply(cmd: Command, frame: Frame) -> bool` and `matches_ack(cmd: Command, ack: Ack) -> bool` —
  the ACK echo equals the first `min(8, len(payload))` command payload bytes.

- [ ] Write the tests:
  - `encode(0x3A, b"\x25\x01") == bytes.fromhex("5a3a022501")`;
  - `encode(0x54, b"\x00")` raises;
  - `encode(0x53, b"\x01")` raises;
  - `FrameReader` split and joined (`5a03 | 023b00 5a0102 0104` yields two frames);
  - leading junk skipped;
  - a `5B` long frame skipped whole;
  - `parse_ack(parse(bytes.fromhex("5a020aa7000002000000000000")))` → `Ack(0xa7, 0, 00 02 00…)`;
  - status `0x81` parsed.
- [ ] Run them and see them fail.
- [ ] Implement `protocol.py`.
- [ ] Run them and see them pass. Commit.

### Task 2: protocol.py — every builder and parser (golden vectors from the capture)

**Files:**
- Modify: `custom_components/sb_katana/protocol.py`
- Test: `tests/test_protocol_commands.py`

**Interfaces — Produces** (each returns a `Command`, and the frame is exactly the capture's bytes):

| Builder | Frame | Reply op / prefix | ACK |
|---|---|---|---|
| `ping()` | `5a0300` | `03` / `b""` | no |
| `firmware_query()` | `5a090102` | `09` / `02` | no |
| `serial_query()` | `5a090103` | `09` / `03` | no |
| `output_query()` | `5a2c0101` | `2c` / `01` | no |
| `set_output(headphones: bool)` | `5a2c0500{24 or 02}000000` | – | yes |
| `input_query()` | `5a9c0101` | `9c` / `01` | no |
| `input_list_query()` | `5a9c0102` | `9c` / `02` | no |
| `set_input(id)` | `5a9c0300{id}00`, id ∈ `{0a, 0c, 07, 04, 01}` | – | yes |
| `auto_switch_query()` | `5a67010d` | `67` / `0d` | no |
| `set_auto_switch(b)` | `5a67020c0{b}` | – | yes |
| `level_query(ch)` | `5a230501{ch}000000` | `23` / `{ch}` | no |
| `set_level(ch, v)` | `5a230500{ch}{v}0000`, v 0–50 | – | yes |
| `mute_query(ch)` | `5a240201{ch}` | `24` / `{ch}` | no |
| `set_mute(ch, b)` | `5a240300{ch}0{b}` | – | yes |
| `sub_query()` | `5a400103` | `40` / `03` | no |
| `set_sub(i)` | `5a40040401` + int16 LE, −10…6 | – | yes |
| `scout_query()` | `5a260308ffff` | `26` / `08ffff` | no |
| `set_scout(b)` | `5a260507020001` / `…0000` (`07 02 00 b 00`) | – | yes |
| `mode_active_query()` | `5aa70101` | `a7` / `01` | no |
| `select_mode(slot)` | `5aa70200{slot}` | – | yes |
| `mode_name_query(slot)` | `5aa70306{slot}00` | `a7` / `06{slot}00` | no |
| `store_query(slot, sub, keys)` | `5aa7 len 13 slot sub n (g i)…` | `a7` / `13{slot}{sub}` | no |
| `store_write(slot, sub, [(g, i, value)])` | `5aa7 len 12 slot sub n (g i val4)…` — u32 for `00.01`/`03.01`, f32 otherwise | – | yes |
| `eq_name_query(sub)` | `5aa80406000000{sub}` | `a8` / `060000{sub}` | no |
| `dsp_query(ids)` | `5a11 len n id16…` (≤9 ids) | `11` / `b""` | no |
| `dsp_write(id, f)` | `5a1207 01 id16 f32` | – | yes |
| `light_power(b)` | `5a3a02250{b}` | – | yes |
| `light_power_query()` | `5a3a0126` | `3a` / `26` | no |
| `light_mode_query()` | `5a3a022a00` | `3a` / `2a00` | no |
| `light_colours_query()` | `5a3a052c00010107` | `3a` / `2c000101` | no |
| `light_name_query()` | `5a3a023200` | `3a` / `3200` | no |
| `light_map_query()` | `5a3a022400` | `3a` / `2400` | no |
| `solo_prepare()` | the three frames `5a3a022501`, `5a3a03370001`, `5a3a03290003` | – | yes |
| `solo_colour(rgb)` | `5a3a082b000101ff{b}{g}{r}` | – | yes |
| `captured_sequence(hexes)` | a `Command` per hex frame, each through the allowlist | – | yes |

Parsers:

| Parser | Returns |
|---|---|
| `parse_firmware(f)` | `str` |
| `parse_serial(f)` | `str` |
| `parse_output(f)` | `"speakers" \| "headphones"` |
| `parse_input(f)` | `int` |
| `parse_input_list(f)` | `list[int]` |
| `parse_level(f)` | `(ch, v)` |
| `parse_mute(f)` | `(ch, bool)` |
| `parse_sub(f)` | `int` (signed) |
| `parse_scout(f)` | `bool` (byte 3 non-zero) |
| `parse_auto_switch(f)` | `bool` |
| `parse_mode_active(f)` | `int` |
| `parse_mode_name(f)` | `(slot, str)` — UTF-16LE after `len len 00` |
| `parse_store(f)` | `(slot, sub, {(g, i): float \| int})` |
| `parse_eq_name(f)` | `(sub, str)` |
| `parse_dsp(f)` | `{id: float}` |
| `parse_light_power(f)` | `bool` |
| `parse_light_mode(f)` | `int` |
| `parse_colours(f)` | `list[rgb]` |
| `parse_light_name(f)` | `str` |
| `parse_light_map_is_solid(f)` | `bool` — every LED maps to slot 1 |

- [ ] Write the golden tests. Builders are compared against the hex in the table. Parsers decode real
  capture replies: `5a09120210312e332e3233303631392e3138323000` is the firmware reply; `5a23 03 000c00` → `(0, 12)`; `5aa7` + `13000008…` from `protocol.md`; the a7/06 reply for
  "Music."; the `11` reply decoding `9608` to 0.5. Also a `store_write` u32 case:
  `(0, 1, 0)` → `000100000000`.
- [ ] See them fail. Implement. See them pass. Commit.

### Task 3: captured.py checks, families.py, guard tests

**Files:**
- Create: `custom_components/sb_katana/families.py`, `tests/test_guards.py`, `tests/test_captured.py`

**Interfaces — Produces:**

- `@dataclass(frozen=True) Family(key: str, tier: Literal["C", "P"], confirmed: bool, label: str)`
- `FAMILIES: dict[str, Family]` with keys:
  - `light_power`, `light_solo` — confirmed=**True**;
  - `light_preset`, `output`, `input`, `auto_switch`, `volume`, `mute`, `sound_mode`, `decoder`,
    `eq_enable`, `eq_preset`, `acoustic`, `crystalvoice`, `scout`, `mixer` — tier C, confirmed=False;
  - `smart_volume_detail`, `mixer_probable`, `subwoofer` — tier P, confirmed=False.
- `LIGHT_PRESET_LABELS`: captured name → UI label (identity).
- `EQ_PRESET_LABELS = {"Footsteps Enhanc": "Footsteps Enhancer", …}`.

- [ ] Guard tests, each with a positive control:
  - Scan every `Command` from every builder plus every captured frame; none has op `0x53`, `0x54` or
    `0x98`, nor a leading `0x5B`. Positive control: the scanner flags a synthetic `5a5400…`.
  - Every captured frame decodes and passes `encode`'s allowlist.
  - The `transport.py` source contains exactly the two command-channel UUIDs (regex over the 128-bit UUID
    pattern). Positive control: the regex finds the second-service UUID in a sample string.
  - `store_write` never encodes `00.01`/`03.01` as f32. Positive control: a float encoding of 1 differs
    from the u32 one.
  - `captured.py` holds 9 lighting presets and 4 EQ presets, with frame counts
    8/8/8/10/9/8/10/10/10 and 10×4.
- [ ] See them fail. Implement `families.py`. See them pass. Commit.

### Task 4: device.py — state, apply_frame, writer queue, gate (with a fake transport)

**Files:**
- Create: `custom_components/sb_katana/const.py`, `custom_components/sb_katana/device.py`,
  `tests/fakes.py`, `tests/test_device.py`

**Interfaces:**

- **Consumes:** protocol builders and parsers, `FAMILIES`.
- **Produces:**
  - `class TransportProtocol(Protocol)` with `async connect()`, `async disconnect()`,
    `async write(frame: bytes)`, `on_frame: Callable[[bytes], None]` (set by the device), `connected: bool`,
    `mtu: int`.
  - `@dataclass KatanaState`, every field `| None`:
    - `firmware`, `serial`, `output`, `input`, `inputs: list[int]`, `auto_switch`,
      `levels: dict[int, int]`, `mutes: dict[int, bool]`, `sub`, `scout`;
    - `mode_active`, `mode_names: dict[int, str]`, `store: dict[tuple[int, int], float | int]` (live slot,
      current sub);
    - `eq_name`, `dsp: dict[int, float]`;
    - `light_on`, `light_mode`, `light_colours`, `light_name`, `light_solid`.
  - `apply_frame(state: KatanaState, raw: bytes) -> bool` — a pure function; returns True if state changed.
  - `class KatanaDevice(transport, *, allow_unconfirmed: bool)` with:
    - `async start()` (connect + read-back);
    - `async stop()`;
    - `add_listener(cb) -> unsub`;
    - `state`, `available`;
    - `async request(cmd) -> Frame` (2 s timeout);
    - `async send(family: str, cmds: list[Command])` — the gate, the manual queue, awaits each ACK, raises
      `KatanaCommandError` on status ≠ 0 or timeout;
    - `submit_stream(cmds: list[Command])` — overwrites the stream slot;
    - `store_sub` property → 0 or 2 from `state.output`;
    - intents: `set_volume`, `set_mute`, `set_input`, `set_output`, `set_auto_switch`, `select_mode`,
      `set_store(family, key, value)`, `set_dsp(family, id, value)`, `set_sub`, `set_scout`,
      `set_level(family, ch, v)`, `light_on_off`, `light_solo(rgb)`, `light_preset(name)`,
      `eq_preset(name)`, `async refresh()`.
  - The firmware gate: if `state.firmware != TESTED_FIRMWARE`, `send` raises `KatanaCommandError`.

- [ ] Tests (the fake transport answers from a dict of request-hex → reply-hexes taken from the capture,
  and ACKs writes with status 00):
  - read-back populates every field;
  - `set_volume(30)` writes `5a2305000000f0000`-style bytes — exactly `5a23050000 1e 0000` — and state
    level = 30 after the ACK;
  - an unconfirmed family raises without `allow_unconfirmed`, and works with it;
  - a firmware mismatch refuses writes;
  - status `0x81` raises and marks the field unknown;
  - an ACK timeout raises;
  - `test_manual_sequence_not_interleaved`;
  - `test_store_sub_follows_output` (a notification `2c 01 24…` flips the sub to 2, and the next
    `set_store` writes sub 02);
  - unsolicited `23 00 0b 00` updates the level.
- [ ] See them fail. Implement. See them pass. Commit.

### Task 5: transport.py, config flow, __init__ setup, manifest

**Files:**
- Create: `manifest.json`, `transport.py`, `config_flow.py`, `strings.json`, `translations/en.json`;
  modify `__init__.py`
- Test: `tests/test_config_flow.py`, `tests/test_init.py`

**Interfaces — Produces:**

- `BleakTransport(hass, address)` implementing `TransportProtocol`, via
  `bluetooth.async_ble_device_from_address(..., connectable=True)` + `establish_connection(
  BleakClientWithServiceCache, ...)`, `start_notify(NOTIFY_UUID, ...)` and
  `write_gatt_char(WRITE_UUID, frame, response=False)`. It rejects frames longer than `mtu − 3`.
- Config flow:
  - `async_step_bluetooth(discovery_info)` → `bluetooth_confirm`;
  - `async_step_user` lists discovered addresses whose name starts `Control for MF8400`;
  - unique_id = address.
- Options flow: `allow_unconfirmed: bool = False`, `stream_rate_hz: int = 10`, `stream_timeout_s: int = 10`.
- `async_setup_entry`:
  - builds `KatanaDevice`; if `start()` fails → `ConfigEntryNotReady`;
  - forwards platforms;
  - registers `stream_frame` once;
  - raises a repair issue `untested_firmware` on mismatch.
- `entry.runtime_data = KatanaRuntime(device, stream)`.

- [ ] Tests:
  - discovery → confirm → entry created;
  - user step with nothing discovered → abort `no_devices_found`;
  - an already-configured address aborts;
  - options flow saves;
  - `test_setup_not_ready_when_unreachable`;
  - setup + unload with the fake transport (patch `BleakTransport`).
- [ ] See them fail. Implement. See them pass. Commit.

### Task 6: stream.py + the stream_frame service

**Files:**
- Create: `stream.py`, `services.yaml`
- Test: `tests/test_stream.py`

**Interfaces — Produces:**

- `StreamController(hass, device, rate_hz, timeout_s)` with:
  - `screen_sync: bool` (restored by the switch);
  - `receiving: bool`;
  - `handle_frame(rgb)`;
  - `manual_override()` — turns screen_sync off, idles, cancels the timer;
  - `set_screen_sync(on)`;
  - `add_listener(cb)`.
- Behaviour:
  - The first frame while idle submits `solo_prepare` + `solo_colour`.
  - Later frames submit `solo_colour` at most once per `1/rate`, the newest winning; a colour equal to the
    last one sent is skipped.
  - A timer of `timeout_s` after the last frame submits `light_power(False)` through the manual path,
    tagged as the hand-over (screen sync stays on), and sets receiving=False.
  - `set_screen_sync(False)` cancels the timer without powering off.

- [ ] Tests (fake clock via `async_fire_time_changed`, fake device recording submissions):
  - rate limit — 100 frames in 1 s at 10 Hz → ≤11 writes, the last one the newest colour;
  - dedup;
  - hand-over powers off once, and screen_sync stays True;
  - a frame with screen_sync off is ignored;
  - `manual_override`;
  - `test_stream_frame_validation`;
  - **the 100-frame stream causes exactly 1 state change of `binary_sensor` receiving and 0 of the light
    entity** (HA state machine with the full integration).
- [ ] See them fail. Implement. See them pass. Commit.

### Task 7: entities

**Files:**
- Create: `entity.py`, `light.py`, `media_player.py`, `switch.py`, `select.py`, `number.py`, `sensor.py`,
  `binary_sensor.py`, `button.py`, `diagnostics.py`
- Test: `tests/test_entities.py`

Entities and their mappings follow spec §4:

- **Light:** `ColorMode.RGB`; brightness = max(rgb); `turn_on` with rgb/brightness → `manual_override()` +
  `light_solo(scaled)`; effect → `light_preset`; `turn_off` → `light_on_off(False)`.
- **Media player:** features VOLUME_SET | VOLUME_MUTE | VOLUME_STEP | SELECT_SOURCE | SELECT_SOUND_MODE;
  source list from `state.inputs` via `INPUT_LABELS`; sound modes from `mode_names` for slots 1–10,
  de-duplicated by name, choosing the lowest slot.
- **Store values:** switches/numbers/selects read `state.store[(g, i)]` and write `set_store`.
- **Numbers:** 0–100 ↔ 0–1; mixer levels as % with step 2.
- **Unknown state** → `None` / unavailable.
- **Also:** `switch` Hold connection (config; off → `device.stop()`, on → `device.start()`), `button` Re-read
  state (`device.refresh()`), `sensor` Firmware (diagnostic), `binary_sensor` Screen sync receiving.
- **`__init__`** schedules `device.refresh()` every 60 s (reads only) while connected.

- [ ] Tests:
  - after setup with capture replies, the states are:
    - volume 0.24, source "USB Audio", sound mode "Music.", output "Speakers", decoder "Full";
    - EQ preset "Music", surround number 100, crystalizer 50;
    - scout off, auto switch on, sub 3, firmware "1.3.230619.1820";
  - each write entity emits its frames (with `allow_unconfirmed`);
  - a write without it raises `HomeAssistantError`;
  - `light.turn_on(rgb=(0,0,255))` emits the solo frames and switches Screen sync off;
  - diagnostics redact the serial and address.
- [ ] See them fail. Implement. See them pass. Commit.

### Task 8: CI, README, docs, ruff, hassfest

**Files:**
- Create: `.github/workflows/ci.yml` (ruff + pytest + HACS) and `hassfest.yml`, `hacs.json`, `README.md`,
  `LICENSE` (MIT, crediting v2x for the translated builders)

- [ ] `ruff check` and `ruff format --check` are clean; the full pytest suite is green.
- [ ] README: install, entities (exhaustive, from §4), options, the service, the safety model, the
  confirmed/unconfirmed table, and the checklist link. Commit.
- [ ] Create a private GitHub repo `Jxn01/ha-katana` and push `main`.

### Task 9: deploy and verify (no owner)

Following spec §10:

- [ ] `scp` `custom_components/sb_katana` to HA, then restart Core.
- [ ] Drive the discovery flow over REST; read entity states.
- [ ] Compare the states against Task 7's expectations.
- [ ] Note the MTU.
- [ ] Run the recorder-row test with a same-colour 100-frame stream, Screen sync off before 10 s.
- [ ] Record the results in the KB.
