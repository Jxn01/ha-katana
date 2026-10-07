# Katana V2X — BLE control protocol (as decoded)

Decoded from one capture of Creative's iOS app driving this soundbar on 2026-10-07
(01:53–02:06 local time), firmware **1.3.230619.1820**, plus earlier probes from Garuda.
Source: `~/Downloads/katana-capture/frames.tsv` (5,342 ATT frames: 2,388 commands, 2,954
notifications). It is not in git, because its replies carry the unit's serial number and
Bluetooth address. The decoders are in `tools/` (`frames.py`, `pairs.py`, `extract_sequences.py`).

Every row is marked with one of three tiers:

- **confirmed** — the bytes, an app screenshot and a readback all agree;
- **probable** — the bytes were seen and the meaning is inferred from timing or context;
- **not captured** — the app has the feature, but the capture holds no frame for it.

Only *confirmed* writes are enabled by default in the integration (see the design spec).

## Transport

| | |
|---|---|
| Device name | `Control for MF8400`, random static address `FF:02:3C:A0:E9:F0` (its classic address is `00:02:3C:A0:E9:F0`, also reported by `0x60/02`) |
| Command service | `9e9daaea-…` |
| Write characteristic | `9e9daaec-…` — ATT value handle **0x000b** (bleak handle 0x000a). The app uses **Write Command** (0x52, no response). |
| Notify characteristic | `9e9daaeb-…` — ATT value handle **0x0008** (bleak 0x0007) |
| Second service | `e49a25f8-…` (handles 0x000d/0x0010). **The app never touches it. Never write it.** |
| Unlock | None. The AES challenge needed on USB serial is **not** needed over BLE, even from cold. |
| Pacing | During slider drags the app sustained a write every ~45 ms (about 22 Hz) with no backpressure and no errors. |
| Connect stall | On the very first connect, `72 01`, `09 04` and `26 05` were answered only after ~7.7 s, all at once. Later commands answer in 30–60 ms. |

### Framing

```
5A <op> <len> <payload: len bytes>
```

Every notification is a whole frame in this capture: iOS negotiated a large MTU, and the
longest frame seen was 63 bytes. **On a link with a smaller MTU, a reply may be split across
notifications**, so the receiver reassembles frames from a byte stream. `0x5B` starts the
firmware-transfer frame family (2-byte length). It is never sent.

### Acknowledgement

```
5A 02 0A <op> <status> <the first 8 payload bytes of the command, zero-padded>
```

| status | meaning |
|---|---|
| `00` | accepted |
| `81` | unsupported or not applicable (`28 02`, `40 01`, `40 08`, `aa 00`, `96 01`, `0e 01`, `6c 0x`, `a7 0a 00`) |
| `83` | rejected (`60 04`) |

Some commands are answered with a data frame of the same opcode and no ACK (most reads).
Writes are answered with an ACK, often plus state notifications. **Any non-zero status is
treated as "rejected"**.

### Unsolicited notifications

The device pushes state frames on changes. In this capture they came after app writes:

- `23/24` after a volume or mute change;
- `a7:01 / a7:0c / a7:06 / a8:01 / a8:0c` after a sound-mode select;
- `3a:26 / 3a:2a / 3a:2c / 3a:32 / 3a:35` and `a7:13 (03,00)` after lighting writes;
- `6f` (stream-format) frames while an input syncs.

Whether the volume knob or the remote also produce them was **not captured** — it is on the
morning checklist. The parser must tolerate unknown opcodes.

## Opcodes and sub-commands

### Identity and housekeeping (read-only)

| Command | Reply | Meaning | Tier |
|---|---|---|---|
| `03` | `03 3b 00` | ping | confirmed |
| `01 00` | `01 01 04` | ? (sent at connect) | probable |
| `72 01` | `72 01 00` | ? (sent at connect) | probable |
| `09 02` | `09 02 10 "1.3.230619.1820"` | firmware version (len-prefixed ASCII) | confirmed |
| `09 03` | `09 03 "Q8MF…"` | serial number, ASCII, NUL-terminated | confirmed |
| `09 00`, `09 01 0x`, `09 04` | binary | other version/info fields | unknown |
| `60 02` | `60 02 06 00 02 3c a0 e9 f0` | Bluetooth address | confirmed |
| `20`, `21`, `10`, `30`, `31 01`, `39 0x`, `a5 01 0x`, `6f 0x` | binary | capability/info tables (`6f 0d` = `"MV  0007.1"` / `"MV  0002.0"` stream format) | unknown |

### Output — `0x2C` (confirmed)

| | |
|---|---|
| Set | `2C 00 <id> 00 00 00` — id `02` = Speakers, `24` = Headphones |
| Read | `2C 01` → `2C 01 <id> 00 00 00` |
| Seen | 02:00:07 → Headphones, 02:00:14 → Speakers (screenshot: Output page). Same values as the `v2x` crate. |

### Input — `0x9C` (confirmed)

| | |
|---|---|
| Set | `9C 00 <id> 00` |
| Read | `9C 01` → `9C 01 <id> 59 0b 00 00 00` |
| List | `9C 02` → `05 05` then five `(id, 00, 01)`, in display order: `0a 0c 07 04 01` |
| Map | `0a` TV (HDMI ARC) · **`0c` USB Audio** · `07` Optical · `04` Aux · `01` Bluetooth |

Evidence: the connect read returned `0c` while the screenshot shows USB Audio ticked; the
list order matches the screen top to bottom; and the writes `0a 07 04 01 0c` (02:00:21–42,
about 5 s apart) are "every other input top to bottom, then back to USB". USB is certain. The
other four follow from the list order and are rated probable-high — confirm by ear.

### Auto Switch to TV/HDMI — `0x67` (confirmed)

`67 0C <0|1>` sets it, `67 0D` → `67 0D <0|1>` reads it. Seen: off at 02:00:51, on at 02:00:55
(Input page toggle).

### Volume — `0x23`, mute — `0x24`

| | |
|---|---|
| Set level | `23 00 <ch> <level> 00 00`, level **0–50** (app percent = level × 2) |
| Read level | `23 01 <ch> 00 00 00` → `23 <ch> <level> 00` |
| Range | `22 07 00 01 02 03 04 05 06` → for each channel `ch 00 32 00 00 00 01 00`: min 0, max 0x32 = 50, step 1 |
| Set mute | `24 00 <ch> <0|1>` |
| Read mute | `24 01 <ch>` → `24 <ch> <0|1>` |
| Side effect | A level write also notifies `24 <ch> 00`, so changing the volume unmutes. |

| ch | meaning | tier | evidence |
|---|---|---|---|
| `00` | Speakers / master | confirmed | 12 = 24% on the home slider and the mixer; dragged 13→19→9 at 02:05:33 |
| `01` | Headphones level | probable | 12; reported right after the output switched to Headphones |
| `02` | ? (muted) | unknown | 18, mute = 1 |
| `03` | SPDIF In monitor | confirmed | 50 = 100%; dragged and restored at 02:06:01 |
| `04` | Line In monitor | confirmed | 18 = 36%; dragged at 02:05:56 |
| `05` | Microphone (recording) | confirmed | 35 = 70%; **dragged to 41 = 82% at 02:06:06 and left there** |
| `06` | What U Hear | probable | 50; dragged and restored at 02:06:25, the last mixer item |

### Subwoofer — `0x40` (probable)

| | |
|---|---|
| Set | `40 04 01 <int16 LE>` |
| Read | `40 03` → `40 03 <int8?> 00` (current 3) |
| Range | `40 0A` → `0a f6ff 0600 0100` = min −10, max +6, step 1 |
| Connected | `40 00` → `00 01` |
| Seen | 02:05:42–53, inside the Mixer window: 4, 5, 4, 3, 2, 1, 0, −1, 0, 1, 2, 3 (back to 3) |

### Microphone priority — `0x2D` (probable)

`2D 05 02 01 00`, `2D 05 02 00 01` and `2D 05 00` at 02:06:14–18 (after the Mixer's mic
slider). This reads as a priority list: a count, then source ids, with an empty list = Auto.
Reads: `2D 01` → `01 02 00 01`, `2D 02 0x`, `2D 04` → `04 00`. **Not exposed.**

### Scout Mode — `0x26` (confirmed)

`26 07 02 00 <0|1> 00` sets it. `26 08 ff ff` → `26 08 ff ff <02 when on, 00 when off> 00…`
reads it. Seen: on at 02:05:12, off at 02:05:16. Same bytes as the `v2x` crate.

### Live DSP parameters — `0x11` read, `0x12` write

`11 <count> <id16>…` reads parameters, `12 <count> (<id16> <f32 LE>)…` writes them. Ids are
big-endian pairs (`96 xx`, `95 xx`, `97 xx`). Replies come in frames of up to 9 values:
`11 <n> <more?> (<id> <f32>)…`.

| id | meaning | tier |
|---|---|---|
| `9600 / 9601` | Surround enable / level (0–1) | confirmed — mirrors store `01.00/01.01` and changes with the output |
| `9607 / 9608` | Crystalizer enable / level | confirmed — mirrors store `01.02/01.03` |
| `9602–9606` | Smart Volume / Dialog+ | probable |
| `9609` | main EQ enable | confirmed (v2x and the store) |
| `960a` | EQ preamp | confirmed |
| `960b–9614` | EQ bands 31 Hz … 16 kHz (dB) | confirmed — equal to the Music curve on the screenshot |
| `952c` | CrystalVoice Smart Volume (mic) enable | confirmed — off/on at 02:04:18/21; on in the screenshot |
| `952d` | ? (0.74) | unknown |
| `9513` | Microphone Equalizer enable | confirmed — 0 = "Off" in the screenshot |
| `9514–951b` | mic EQ gains, 8 bands | confirmed — 11 preset taps at 02:04:25–50 |
| `951c–9523` | mic EQ band centres 62.5 Hz … 8 kHz | confirmed (read-only constants) |
| `9524–952b` | mic EQ band lower edges (f/√2) | confirmed (constants) |
| `9506` | CrystalVoice Focus enable | confirmed |
| `9507` | ? (0.08) | unknown |
| `9508 / 9509` | Focus wedge angle (degrees, 30) | confirmed for `9508`, dragged at 02:04:59–05:10 |
| `9702`, `961e` | ? | unknown |

The app writes **only CrystalVoice** through `0x12`. It writes the acoustic engine, the
decoder and EQ enable **through the sound-mode store** (`0xA7`, below), which updates the DSP
and keeps the store consistent. The integration does the same.

### Sound-mode store — `0xA7`

Slots `00`–`0a`. **Slot `00` is the live working copy of the active mode.** Slots `01`–`0a`
are stored modes. Each slot holds four sub-configs: **`00` = Speakers**, **`02` =
Headphones** (proven: the live DSP read flips with the output and matches these), and `01` /
`03`, whose meaning is unknown.

| Command | Reply | Meaning | Tier |
|---|---|---|---|
| `A7 01` | `A7 01 <slot>` | active stored slot (1 = "Music.") | confirmed |
| `A7 00 <slot>` | ACK + `a7:01<slot>`, `a7:0c 00 00 <uuid>`, `a7:06 00 00 <name>`, `a8:01 <slot>`, `a8:0c…` | **select a stored mode** | confirmed — 02:01:04–31 |
| `A7 06 <slot> <00|01>` | `06 <slot> <y> <len> <max=0x10> 00 <UTF-16LE name>` | mode name (`y=00`); `y=01` is a second name of unknown role | confirmed for `y=00` |
| `A7 0C <slot> <00|01>` | 16-byte UUID | mode identity; built-in templates are `00000000-0000-1000-8000-0000000000NN` | confirmed |
| `A7 0D` | `0d 04` | number of user modes? | probable |
| `A7 13 <slot> <sub> <n> (<grp> <idx>)…` | `13 <slot> <sub> <n> (<grp> <idx> <4 bytes>)…` | read parameters | confirmed |
| `A7 12 <slot> <sub> <n> (<grp> <idx> <4 bytes>)…` | ACK | **write parameters** | confirmed |
| `A7 0B <slot> <sub> <uuid>` · `A7 05 <slot> <sub> <len> <len> 00 <name>` · `A7 10 …` | ACK | editor path: load a template into slot `ff` | confirmed, **never used** |
| `A7 02`, `07 00`, `11 <slot> <sub>`, `16`, `19 …` | binary | store metadata | unknown |

Names on this unit, from `A7 06 <slot> 00`: `01` "Music.", `02` "Gaming.", `03` "Voice.",
`04`–`0a` "Effects Off". The app's Modes list showed "Gaming., Music., Voice., Effects Off"
and then dozens of **app-side templates** (Gaming, Music, Movies, Apex Legends, …). Those are
written into the live slot through the editor path and are not stored on the device. The app
picked "Effects Off" as slot `09`.

#### Parameter map — `(group, index)`

**A value is not always a float.** Decode by key:

| key | type | meaning | tier |
|---|---|---|---|
| `00.00` | f32 0/1 | EQ enable (EQ Presets page On/Off, 02:02:52/54) | confirmed |
| `00.01` | **u32** | EQ store slot this mode uses (1, 2, 3, …). The app writes 0 before an EQ preset pick. | confirmed |
| `01.00` / `01.01` | f32 0/1, f32 0–1 | Surround enable / level (UI 0–100) | confirmed — 02:01:41–51 |
| `01.02` / `01.03` | f32 0/1, f32 0–1 | Crystalizer enable / level | confirmed — 02:01:54–02:04 |
| `01.06` | f32 0/1 | Smart Volume enable | confirmed — 02:02:08 / 02:22 |
| `01.08` | f32 0/1/2 | Smart Volume mode (three choices; names not captured) | probable |
| `01.07` | f32 0–1 | Smart Volume level | probable |
| `01.09` / `01.0a` | f32 0/1, f32 0–1 | Dialog+ enable / level | confirmed — 02:02:25–35 |
| `02.00` | f32 | ? (always 0) | unknown |
| `03.00` | f32 0/1 | lighting power, mirrored by the firmware on every `3a 25` | confirmed |
| `03.01` | **u32** | lighting store slot (`0x81` + n) | confirmed |
| `04.00` | f32 1/2/3 | Decoder: **1 = Full, 2 = Normal, 3 = Night** | confirmed — taps at 02:03:37–44 and 02:05:21–26; "Full" ticked = 1 |

The app edits on the Speakers tab as `A7 12 00 00 01 <grp> <idx> <f32>`, i.e. live slot,
sub `00`. The integration writes sub `00` while the output is Speakers and sub `02` while it
is Headphones.

### EQ store — `0xA8`

Indexed `00 <slot> <sub>` with sub `00` (Speakers) / `02` (Headphones).

| Command | Meaning | Tier |
|---|---|---|
| `A8 01` → `01 00 <slot>` | active EQ slot | confirmed |
| `A8 06 00 <slot> <sub>` | EQ preset name (UTF-16LE, ≤16 chars, so "Footsteps Enhanc") | confirmed |
| `A8 0C 00 <slot> <sub>` | EQ preset UUID (`…00NN`: 02 Gaming, 03 Music, 04 Movies, 05 Footsteps Enhancer) | confirmed |
| `A8 11 00 <slot> <sub> <n> <idx>…` | read EQ values: `00` preamp, `01`–`0a` the ten bands, `0b` bass, `0c` treble | confirmed |
| `A8 0B / 05 / 10 00 ff <sub> …` | load a preset into the live EQ (uuid, name, values) | confirmed — four EQ-page picks at 02:02:40–49 |

**EQ preset curves live in the app**, not on the device. The capture holds four complete
EQ-page picks — Movies, Footsteps Enhancer, Gaming, Music — stored verbatim in
`custom_components/sb_katana/captured.py`. **Dragging a main EQ band was not captured.** The
02:04:25–55 run is the microphone EQ.

### Lighting — `0x3A`

The live config is slot `00`. The app addresses it as `ff`, and the device echoes the change
as slot `00`. ambience-rgb and the v2x crate write `00` directly, which is proven to work.
Stored presets are slots `01`–`04` (on this unit: Mood Orange, Aurora, Wave Green, Solo
White). Per-mode slots `81`–`8a` are all `EMPTY`.

| Command | Meaning | Tier |
|---|---|---|
| `3A 25 <0|1>` | power off/on (app toggle at 02:03:28/31) | confirmed |
| `3A 26` → `26 <0|1>` | power state | confirmed |
| `3A 29 <slot> <mode>` | mode: `01` Cycle, `03` Solo/Mood, `04` Wave, `05` Pulsate, `07` Morph, `08` Aurora | confirmed |
| `3A 2A <slot>` → `2a <slot> <mode>` | mode read | confirmed |
| `3A 37 <slot> <n>` | colour count (1 for Solo/Morph, 7 otherwise) | confirmed |
| `3A 2B <slot> 01 01 <7×ABGR>` / `… 01 01 <ABGR>` | colours (wire order `ff B G R`) | confirmed |
| `3A 2B <slot> 02 01 <ABGR>` | Morph target colour | confirmed |
| `3A 2B <slot> 03 <u16 LE ms>` | speed (period) | confirmed |
| `3A 2B <slot> 04 01 <00|01>` | wave direction | confirmed |
| `3A 2B <slot> 09 00 <0|1> 40 ff 2c 01` | music-reactive | confirmed |
| `3A 2C <slot> <param> [01 07]` | read a parameter | confirmed |
| `3A 34 <slot> <uuid>` / `3A 31 <slot> <len> <len> 00 <name>` | preset identity / name | confirmed |
| `3A 35 <slot>` / `3A 32 <slot>` | read the identity / name ("Onboard" for the live slot) | confirmed |
| `3A 20` | `07 01 00 04 00 00 1a`: 7 colours, 26 LEDs | confirmed |
| `3A 21` | `06 00 01 03 04 05 07 08`: supported modes | confirmed |
| `3A 22 <mode>` | per-mode parameter descriptor | probable |
| `3A 24 <slot>` | per-LED colour-slot map | probable |
| `3A 27 <level>` | brightness (v2x crate) | **not captured** — the app has no brightness control |

A **preset load** is: `34` uuid → `31` name → `25 00` → `29` mode → `37` count → `2b` params
→ `25 01`. The nine captured loads (Aurora, Cycle, Mood Orange, Morph Cyan, Pulsate Red, Solo
White, Wave Green, Wave Ice Blue, Wave Rainbow) are stored verbatim in `captured.py`.

### Never sent

| Opcode | Why |
|---|---|
| `0x53` | firmware validate/apply |
| `0x54` | debug memory read/write/exec |
| `0x5B` (marker) / `0x98` | firmware transfer |
| any write to the `e49a25f8` service | unknown purpose, never used by the app |

The app's settings gear offers firmware **1.30.260813.1100**. It is never taken, and the
integration never offers updates.

## Not captured

- **Super X-Fi** — greyed out on Speakers, never toggled. No frames.
- **Main EQ band drag**, Bass/Treble sliders — the values are readable (`A8 11`, `0x11`), but
  no write was captured.
- **Lighting brightness** — the app has no such control.
- **Custom Buttons**, the Bluetooth pairing sub-page, sound-mode create/rename/delete.
- **Smart Volume mode names** (the values 0/1/2 are known, the labels are not).

## State the capture left behind

These are from the owner's tapping, not from anything the integration does:

- Microphone level 70% → **82%** (`23 ch05` = 41).
- Speakers 24% → 22% (`ch00` = 11).
- **Microphone Equalizer was Off and is now On**, with an 8-band mic preset (−3 −4 0 2 3 −3 4 5
  dB). The screenshot showed "Off"; the last write at 02:04:55 is `9513` = 1.
- Focus wedge angle 30° → 29.8°.
- Lighting is now the **Wave Rainbow** preset, toggled off and on. ambience-rgb repaints Solo
  on top while it runs.
- Everything else was returned to its starting value: output Speakers, input USB, auto-switch
  on, sound mode "Music.", acoustic engine, decoder Full, EQ preset Music and EQ on,
  subwoofer 3, scout off, CrystalVoice Smart Volume on.
