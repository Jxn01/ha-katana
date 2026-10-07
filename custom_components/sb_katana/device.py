"""The soundbar as an object: state, I/O discipline and the write gate.

Three rules from the design live here:

* **State comes only from the device.** A field changes when the soundbar
  reports it (a reply or an unsolicited notification) or acknowledges a write
  with status 00. No reply means unknown: the field is cleared and re-read.
* **One exchange at a time.** Acknowledgements name only the opcode they
  answer, so every frame -- read or write -- goes out under one lock and waits
  for its answer before the next. A manual command sequence (a preset load)
  holds the lock for its whole length, so stream frames can never interleave.
* **Writes pass the gate.** Untested firmware refuses every write; a family the
  owner has not yet confirmed live refuses unless ``allow_unconfirmed``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from homeassistant.exceptions import HomeAssistantError

from . import captured
from . import protocol as p
from .const import RECONNECT_BACKOFF, REPLY_TIMEOUT
from .families import FAMILIES, is_allowed

_LOGGER = logging.getLogger(__name__)

StoreValues = dict[tuple[int, int], float | int]


class KatanaCommandError(HomeAssistantError):
    """A write was refused, rejected by the soundbar, or not answered."""


class KatanaUnconfirmedError(KatanaCommandError):
    """A write in a family the owner has not confirmed live yet."""


class KatanaRejectedError(KatanaCommandError):
    """The soundbar answered with a non-zero status: the outcome is known (not applied)."""


class Transport(Protocol):
    on_frame: Callable[[bytes], None] | None
    on_disconnect: Callable[[], None] | None

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def write(self, frame: bytes) -> None: ...


@dataclass
class KatanaState:
    """Everything known about the soundbar. ``None`` means unknown."""

    firmware: str | None = None
    serial: str | None = None
    output: str | None = None  # "speakers" | "headphones"
    input: int | None = None
    inputs: list[int] | None = None
    auto_switch: bool | None = None
    levels: dict[int, int] = field(default_factory=dict)
    mutes: dict[int, bool] = field(default_factory=dict)
    sub: int | None = None
    scout: bool | None = None
    mode_active: int | None = None
    mode_names: dict[int, str] = field(default_factory=dict)
    store: dict[int, StoreValues] = field(default_factory=dict)  # live slot, keyed by sub
    eq_names: dict[int, str] = field(default_factory=dict)  # live EQ name, keyed by sub
    dsp: dict[int, float] = field(default_factory=dict)
    light_on: bool | None = None
    light_mode: int | None = None
    light_colours: list[tuple[int, int, int]] | None = None
    light_name: str | None = None
    light_solid: bool | None = None

    @property
    def store_sub(self) -> int:
        return p.STORE_SUB_HEADPHONES if self.output == "headphones" else p.STORE_SUB_SPEAKERS


def apply_frame(state: KatanaState, raw: bytes) -> bool:
    """Fold one inbound frame into ``state``. Returns True if anything changed.

    Pure, so the whole notification model is tested without a device. Frames
    this does not understand -- acknowledgements, stream-format reports,
    capability tables -- are ignored.
    """
    try:
        frame = p.parse(raw)
    except p.ProtocolError:
        return False
    before = repr(state)
    op, pl = frame.op, frame.payload
    try:
        if op == p.OP_INFO and pl[:1] == b"\x02":
            state.firmware = p.parse_firmware(frame)
        elif op == p.OP_INFO and pl[:1] == b"\x03":
            state.serial = p.parse_serial(frame)
        elif op == p.OP_OUTPUT and pl[:1] == b"\x01":
            state.output = p.parse_output(frame)
        elif op == p.OP_INPUT and pl[:1] == b"\x01":
            state.input = p.parse_input(frame)
        elif op == p.OP_INPUT and pl[:1] == b"\x02":
            state.inputs = p.parse_input_list(frame)
        elif op == p.OP_AUTO_SWITCH and pl[:1] == b"\x0d":
            state.auto_switch = p.parse_auto_switch(frame)
        elif op == p.OP_LEVEL and len(pl) >= 2 and pl[0] in p.CHANNELS:
            ch, level = p.parse_level(frame)
            state.levels[ch] = level
        elif op == p.OP_MUTE and len(pl) == 2 and pl[0] in p.CHANNELS:
            ch, muted = p.parse_mute(frame)
            state.mutes[ch] = muted
        elif op == p.OP_SUB and pl[:1] == b"\x03":
            state.sub = p.parse_sub(frame)
        elif op == p.OP_SCOUT and pl[:3] == b"\x08\xff\xff":
            state.scout = p.parse_scout(frame)
        elif op == p.OP_MODE and pl[:1] == b"\x01" and len(pl) == 2:
            state.mode_active = p.parse_mode_active(frame)
        elif op == p.OP_MODE and pl[:1] == b"\x06":
            slot, which, name = p.parse_mode_name(frame)
            if which == 0 and slot in p.MODE_SLOTS:
                state.mode_names[slot] = name
        elif op == p.OP_MODE and pl[:1] == b"\x13":
            slot, sub, values = p.parse_store(frame)
            if slot == p.LIVE_SLOT:
                state.store.setdefault(sub, {}).update(values)
        elif op == p.OP_EQ and pl[:2] == b"\x06\x00":
            slot, sub, name = p.parse_eq_name(frame)
            if slot == p.LIVE_SLOT:
                state.eq_names[sub] = name
        elif op == p.OP_DSP_READ:
            state.dsp.update(p.parse_dsp(frame))
        elif op == p.OP_LIGHT and pl[:1] == bytes([p.LIGHT_SUB_POWER_QUERY]):
            state.light_on = p.parse_light_power(frame)
        elif op == p.OP_LIGHT and pl[:1] == bytes([p.LIGHT_SUB_MODE_QUERY]):
            slot, mode = p.parse_light_mode(frame)
            if slot == p.LIVE_SLOT:
                state.light_mode = mode
        elif op == p.OP_LIGHT and pl[:4] == b"\x2c\x00\x01\x01":
            _, colours = p.parse_colours(frame)
            state.light_colours = colours
        elif op == p.OP_LIGHT and pl[:2] == bytes([p.LIGHT_SUB_NAME_QUERY, p.LIVE_SLOT]):
            _, state.light_name = p.parse_light_name(frame)
        elif op == p.OP_LIGHT and pl[:2] == bytes([p.LIGHT_SUB_MAP_QUERY, p.LIVE_SLOT]):
            _, state.light_solid = p.parse_light_map_is_solid(frame)
    except (p.ProtocolError, IndexError):
        _LOGGER.debug("Unparseable frame ignored: %s", raw.hex())
        return False
    return repr(state) != before


@dataclass
class _Pending:
    cmd: p.Command
    future: asyncio.Future


@dataclass
class _StreamBatch:
    cmds: list[p.Command]
    prepare: bool
    on_done: Callable[[bool], None] | None


class KatanaDevice:
    """One soundbar over one transport."""

    def __init__(self, transport: Transport, *, allow_unconfirmed: bool = False, hold_connection: bool = True) -> None:
        self._transport = transport
        self.allow_unconfirmed = allow_unconfirmed
        self.hold_connection = hold_connection
        self.state = KatanaState()
        self._listeners: list[Callable[[], None]] = []
        self._io_lock = asyncio.Lock()
        self._pending: _Pending | None = None
        self._stream_slot: _StreamBatch | None = None
        self._stream_wake = asyncio.Event()
        self._stream_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False
        self._verified = False  # identity (firmware) read on THIS connection
        self.connect_count = 0  # bumps on every verified (re)connect
        self.stream_errors = 0
        transport.on_frame = self._on_frame
        transport.on_disconnect = self._on_disconnect

    # --- lifecycle ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._transport.connected and self._verified

    @property
    def firmware_ok(self) -> bool:
        """Only a firmware read on the current connection counts: the app could have updated it meanwhile."""
        return self._verified and self.state.firmware == p.TESTED_FIRMWARE

    def _ensure_stream_task(self) -> None:
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = asyncio.create_task(self._stream_loop(), name="sb_katana stream writer")

    async def _connect_and_verify(self) -> None:
        """Connect and read everything back; on a failed read-back drop the link so a retry starts clean."""
        await self._transport.connect()
        try:
            await self.refresh(full=True)
        except BaseException:
            await self._transport.disconnect()
            raise
        self.connect_count += 1

    async def start(self, *, keep_trying: bool = False) -> None:
        """Connect and read everything back. Raises if the soundbar cannot be reached.

        ``keep_trying`` (the Hold connection switch) also starts the reconnect loop
        when this attempt fails; setup leaves retrying to Home Assistant instead.
        """
        self._stopping = False
        self._ensure_stream_task()
        try:
            await self._connect_and_verify()
        except BaseException:
            if keep_trying and self.hold_connection and (self._reconnect_task is None or self._reconnect_task.done()):
                self._reconnect_task = asyncio.create_task(self._reconnect_loop(), name="sb_katana reconnect")
            raise
        self._notify()

    async def stop(self) -> None:
        self._stopping = True
        self._verified = False
        for task in (self._stream_task, self._reconnect_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._stream_task = self._reconnect_task = None
        await self._transport.disconnect()
        self._notify()

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return remove

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def _on_disconnect(self) -> None:
        _LOGGER.info("Katana disconnected")
        self._verified = False
        if self._pending is not None and not self._pending.future.done():
            self._pending.future.set_exception(KatanaCommandError("soundbar disconnected"))
        self._notify()
        if (
            not self._stopping
            and self.hold_connection
            and (self._reconnect_task is None or self._reconnect_task.done())
        ):
            self._reconnect_task = asyncio.create_task(self._reconnect_loop(), name="sb_katana reconnect")

    async def _reconnect_loop(self) -> None:
        for delay in (*RECONNECT_BACKOFF, *[RECONNECT_BACKOFF[-1]] * 10_000):
            await asyncio.sleep(delay)
            if self._stopping or self._transport.connected:
                return
            try:
                await self._connect_and_verify()
            except (KatanaCommandError, OSError, TimeoutError) as err:
                _LOGGER.debug("Katana reconnect failed: %s", err)
                continue
            except Exception:
                _LOGGER.exception("Katana reconnect failed unexpectedly")
                continue
            _LOGGER.info("Katana reconnected")
            self._ensure_stream_task()
            self._notify()
            return

    # --- inbound ----------------------------------------------------------------------

    def _on_frame(self, raw: bytes) -> None:
        try:
            frame = p.parse(raw)
        except p.ProtocolError:
            return
        pending = self._pending
        if pending is not None and not pending.future.done():
            ack = p.parse_ack(frame)
            if ack is not None:
                # A read is answered by data; an ACK only resolves it when it is a refusal.
                # (A late status-00 ACK of an earlier, timed-out write is not its answer.)
                if (pending.cmd.ack and p.matches_ack(pending.cmd, ack)) or (
                    ack.op == pending.cmd.reply_op and ack.status != 0
                ):
                    pending.future.set_result(ack)
            elif p.matches_reply(pending.cmd, frame):
                pending.future.set_result(frame)
        if apply_frame(self.state, raw):
            self._notify()

    # --- outbound ---------------------------------------------------------------------

    async def _exchange(self, cmd: p.Command) -> p.Frame | p.Ack:
        """Send one frame and wait for its answer. The caller holds ``_io_lock``."""
        if not self._transport.connected:
            raise KatanaCommandError("soundbar not connected")
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending = _Pending(cmd, future)
        try:
            await self._transport.write(cmd.frame)
            result = await asyncio.wait_for(future, REPLY_TIMEOUT)
        except TimeoutError as err:
            raise KatanaCommandError(f"no answer to {cmd.frame.hex()}") from err
        finally:
            self._pending = None
        if isinstance(result, p.Ack) and result.status != 0:
            raise KatanaRejectedError(f"soundbar rejected {cmd.frame.hex()} with status {result.status:#04x}")
        return result

    async def request(self, cmd: p.Command) -> p.Frame:
        """Send a read and return its reply (which has also been folded into state)."""
        async with self._io_lock:
            result = await self._exchange(cmd)
        if not isinstance(result, p.Frame):
            raise KatanaCommandError(f"expected a reply to {cmd.frame.hex()}")
        return result

    def check_gate(self, family: str) -> None:
        if not self.firmware_ok:
            raise KatanaCommandError(
                f"firmware {self.state.firmware!r} is not the tested {p.TESTED_FIRMWARE}; writes are disabled"
            )
        if not is_allowed(family, self.allow_unconfirmed):
            raise KatanaUnconfirmedError(
                f"'{FAMILIES[family].label}' has not been confirmed live yet. Turn on 'Allow unconfirmed "
                "controls' in the integration options to test it (see the morning checklist)."
            )

    async def send(
        self,
        family: str,
        cmds: list[p.Command],
        *,
        reread: list[p.Command] | None = None,
        forget: Callable[[], None] | None = None,
    ) -> None:
        """Gate, then send ``cmds`` back to back, each waiting for its acknowledgement.

        A refusal (status != 0) means the write was not applied: the old value
        stands and is re-read. No answer (a timeout, a dropped link) means the
        outcome is unknown: the affected fields are cleared (``forget``) before the
        re-read, so state never claims a value the soundbar did not confirm.
        """
        self.check_gate(family)
        try:
            async with self._io_lock:
                for cmd in cmds:
                    await self._exchange(cmd)
        except KatanaRejectedError:
            if reread:
                await self._reread(reread)
            raise
        except KatanaCommandError:
            if forget is not None:
                forget()
                self._notify()
            if reread:
                await self._reread(reread)
            raise

    async def _reread(self, cmds: list[p.Command]) -> None:
        for cmd in cmds:
            try:
                await self.request(cmd)
            except KatanaCommandError as err:
                _LOGGER.debug("Re-read failed: %s", err)

    def submit_stream(
        self, cmds: list[p.Command], *, prepare: bool = False, on_done: Callable[[bool], None] | None = None
    ) -> None:
        """Replace whatever stream write is waiting: the newest frame wins.

        ``prepare`` marks a batch that starts with the solo-prepare frames. If such a
        batch is replaced before it went out, the prepare is carried into the new
        one -- otherwise only colours would follow and the lights could stay off.
        ``on_done(ok)`` reports whether the batch reached the soundbar.
        """
        old = self._stream_slot
        if old is not None and old.prepare and not prepare:
            # A prepare batch is the prepare frames followed by exactly one colour.
            cmds = [*old.cmds[: len(old.cmds) - 1], *cmds]
            prepare = True
        self._stream_slot = _StreamBatch(cmds, prepare, on_done)
        self._stream_wake.set()

    def clear_stream(self) -> None:
        """Drop a stream write that has not gone out yet."""
        self._stream_slot = None

    async def _stream_loop(self) -> None:
        while True:
            await self._stream_wake.wait()
            self._stream_wake.clear()
            while self._stream_slot is not None:
                batch, self._stream_slot = self._stream_slot, None
                ok = False
                try:
                    self.check_gate("light_solo")
                    async with self._io_lock:
                        for cmd in batch.cmds:
                            await self._exchange(cmd)
                    ok = True
                except KatanaCommandError as err:
                    self.stream_errors += 1
                    _LOGGER.debug("Stream write failed: %s", err)
                except Exception:  # the writer must outlive any one bad batch
                    self.stream_errors += 1
                    _LOGGER.exception("Stream write failed unexpectedly")
                if batch.on_done is not None:
                    batch.on_done(ok)

    # --- reads ------------------------------------------------------------------------

    def _read_plan(self, full: bool) -> list[p.Command]:
        quick = [
            p.output_query(),
            p.input_query(),
            p.level_query(p.CH_SPEAKERS),
            p.mute_query(p.CH_SPEAKERS),
            p.mode_active_query(),
            p.light_power_query(),
        ]
        if not full:
            return quick + self._missing_reads()
        plan = [p.ping(), p.firmware_query(), p.serial_query(), *quick, p.input_list_query(), p.auto_switch_query()]
        plan += [p.level_query(ch) for ch in p.CHANNELS if ch != p.CH_SPEAKERS]
        plan += [p.mute_query(ch) for ch in p.CHANNELS if ch != p.CH_SPEAKERS]
        plan += [p.sub_query(), p.scout_query()]
        plan += [p.mode_name_query(slot) for slot in p.MODE_SLOTS]
        plan += self._store_reads(p.STORE_SUB_SPEAKERS) + self._store_reads(p.STORE_SUB_HEADPHONES)
        plan += [p.eq_name_query(p.STORE_SUB_SPEAKERS), p.eq_name_query(p.STORE_SUB_HEADPHONES)]
        plan += [p.dsp_query(p.DSP_READ_IDS)]
        plan += self._light_reads()
        return plan

    def _missing_reads(self) -> list[p.Command]:
        """Reads for whatever is still unknown, so the poll heals a read that failed at connect."""
        s = self.state
        reads: list[p.Command] = []
        if s.inputs is None:
            reads.append(p.input_list_query())
        if s.auto_switch is None:
            reads.append(p.auto_switch_query())
        reads += [p.level_query(ch) for ch in p.CHANNELS if ch not in s.levels and ch != p.CH_SPEAKERS]
        reads += [p.mute_query(ch) for ch in p.CHANNELS if ch not in s.mutes and ch != p.CH_SPEAKERS]
        if s.sub is None:
            reads.append(p.sub_query())
        if s.scout is None:
            reads.append(p.scout_query())
        reads += [p.mode_name_query(slot) for slot in p.MODE_SLOTS if slot not in s.mode_names]
        wanted = {key for keys in p.STORE_READ_KEYS for key in keys}
        for sub in (p.STORE_SUB_SPEAKERS, p.STORE_SUB_HEADPHONES):
            if not wanted <= set(s.store.get(sub, {})):
                reads += self._store_reads(sub)
            if sub not in s.eq_names:
                reads.append(p.eq_name_query(sub))
        if not set(p.DSP_READ_IDS) <= set(s.dsp):
            reads.append(p.dsp_query(p.DSP_READ_IDS))
        if s.light_colours is None or s.light_mode is None or s.light_name is None or s.light_solid is None:
            reads += self._light_reads()
        return reads

    @staticmethod
    def _store_reads(sub: int) -> list[p.Command]:
        return [p.store_query(p.LIVE_SLOT, sub, keys) for keys in p.STORE_READ_KEYS]

    @staticmethod
    def _light_reads() -> list[p.Command]:
        return [
            p.light_power_query(),
            p.light_mode_query(),
            p.light_colours_query(),
            p.light_name_query(),
            p.light_map_query(),
        ]

    async def refresh(self, *, full: bool = False) -> None:
        """Read state back. The full read is what connect does; the quick one is the poll.

        Right after a connect the soundbar can sit on a few questions for several
        seconds (seen in the app's capture and live), so a read that times out is
        retried once at the end. A failed full read of the identity raises,
        because a soundbar that cannot even report its firmware is not set up.
        """
        if full:
            self._verified = False
            self.state.firmware = None
        failed: list[p.Command] = []
        for cmd in self._read_plan(full):
            try:
                await self.request(cmd)
            except KatanaCommandError as err:
                if full and cmd.op in (p.OP_PING, p.OP_INFO):
                    raise
                _LOGGER.debug("Read %s failed, will retry: %s", cmd.frame.hex(), err)
                failed.append(cmd)
        for cmd in failed:
            try:
                await self.request(cmd)
            except KatanaCommandError as err:
                _LOGGER.debug("Read %s failed again: %s", cmd.frame.hex(), err)
        if full:
            self._verified = self.state.firmware is not None
        self._notify()

    # --- intents ----------------------------------------------------------------------

    async def set_volume(self, level: int) -> None:
        await self.set_level("volume", p.CH_SPEAKERS, level)

    async def set_level(self, family: str, channel: int, level: int) -> None:
        level = max(0, min(p.LEVEL_MAX, int(level)))
        await self.send(
            family,
            [p.set_level(channel, level)],
            reread=[p.level_query(channel)],
            forget=lambda: self.state.levels.pop(channel, None),
        )
        self.state.levels[channel] = level
        self.state.mutes[channel] = False  # the soundbar unmutes on any level change
        self._notify()

    async def set_mute(self, muted: bool, channel: int = p.CH_SPEAKERS) -> None:
        await self.send(
            "mute",
            [p.set_mute(channel, muted)],
            reread=[p.mute_query(channel)],
            forget=lambda: self.state.mutes.pop(channel, None),
        )
        self.state.mutes[channel] = muted
        self._notify()

    async def set_input(self, input_id: int) -> None:
        await self.send(
            "input",
            [p.set_input(input_id)],
            reread=[p.input_query()],
            forget=lambda: setattr(self.state, "input", None),
        )
        self.state.input = input_id
        self._notify()

    async def set_output(self, headphones: bool) -> None:
        await self.send(
            "output",
            [p.set_output(headphones)],
            reread=[p.output_query()],
            forget=lambda: setattr(self.state, "output", None),
        )
        self.state.output = "headphones" if headphones else "speakers"
        # The live store and EQ follow the output; make sure that side is loaded.
        await self._reread([*self._store_reads(self.state.store_sub), p.eq_name_query(self.state.store_sub)])
        self._notify()

    async def set_auto_switch(self, on: bool) -> None:
        await self.send(
            "auto_switch",
            [p.set_auto_switch(on)],
            reread=[p.auto_switch_query()],
            forget=lambda: setattr(self.state, "auto_switch", None),
        )
        self.state.auto_switch = on
        self._notify()

    async def set_scout(self, on: bool) -> None:
        await self.send(
            "scout", [p.set_scout(on)], reread=[p.scout_query()], forget=lambda: setattr(self.state, "scout", None)
        )
        self.state.scout = on
        self._notify()

    async def set_sub(self, level: int) -> None:
        level = max(p.SUB_MIN, min(p.SUB_MAX, int(level)))
        await self.send(
            "subwoofer", [p.set_sub(level)], reread=[p.sub_query()], forget=lambda: setattr(self.state, "sub", None)
        )
        self.state.sub = level
        self._notify()

    async def select_mode(self, slot: int) -> None:
        await self.send(
            "sound_mode",
            [p.select_mode(slot)],
            reread=[p.mode_active_query()],
            forget=lambda: setattr(self.state, "mode_active", None),
        )
        self.state.mode_active = slot
        # Selecting a mode replaces the live acoustic, decoder and EQ settings.
        await self._reread(
            [
                *self._store_reads(p.STORE_SUB_SPEAKERS),
                *self._store_reads(p.STORE_SUB_HEADPHONES),
                p.eq_name_query(p.STORE_SUB_SPEAKERS),
                p.eq_name_query(p.STORE_SUB_HEADPHONES),
            ]
        )
        self._notify()

    async def set_store(self, family: str, key: tuple[int, int], value: float) -> None:
        if self.state.output is None:
            # Speakers and Headphones have separate settings; writing the wrong side
            # while showing it as applied would be worse than refusing.
            raise KatanaCommandError("the current output is unknown, so it is unclear which side to change")
        sub = self.state.store_sub
        await self.send(
            family,
            [p.store_write(sub, [(key, value)])],
            reread=self._store_reads(sub),
            forget=lambda: self.state.store.get(sub, {}).pop(key, None),
        )
        self.state.store.setdefault(sub, {})[key] = float(value)
        self._notify()

    async def set_dsp(self, pid: int, on: bool) -> None:
        value = 1.0 if on else 0.0
        await self.send(
            "crystalvoice",
            [p.dsp_write(pid, value)],
            reread=[p.dsp_query(p.DSP_READ_IDS)],
            forget=lambda: self.state.dsp.pop(pid, None),
        )
        self.state.dsp[pid] = value
        self._notify()

    async def eq_preset(self, name: str) -> None:
        if name not in captured.EQ_PRESETS:
            raise KatanaCommandError(f"unknown EQ preset {name!r}")
        await self.send(
            "eq_preset",
            p.captured_sequence(captured.EQ_PRESETS[name]),
            reread=[p.eq_name_query(self.state.store_sub)],
            forget=self.state.eq_names.clear,
        )
        await self._reread(
            [
                p.eq_name_query(p.STORE_SUB_SPEAKERS),
                p.eq_name_query(p.STORE_SUB_HEADPHONES),
                *self._store_reads(self.state.store_sub),
            ]
        )
        self._notify()

    async def light_on_off(self, on: bool) -> None:
        await self.send(
            "light_power",
            [p.light_power(on)],
            reread=[p.light_power_query()],
            forget=lambda: setattr(self.state, "light_on", None),
        )
        self.state.light_on = on
        self._notify()

    async def light_solo(self, rgb: tuple[int, int, int]) -> None:
        await self.send(
            "light_solo",
            [*p.solo_prepare(), p.solo_colour(rgb)],
            reread=self._light_reads(),
            forget=self._forget_light,
        )
        self.state.light_on = True
        self.state.light_mode = p.LIGHT_MODE_MOOD
        self.state.light_solid = True
        self.state.light_colours = [tuple(rgb), *(self.state.light_colours or [])[1:]]
        self._notify()

    async def light_preset(self, name: str) -> None:
        if name not in captured.LIGHTING_PRESETS:
            raise KatanaCommandError(f"unknown lighting preset {name!r}")
        await self.send(
            "light_preset",
            p.captured_sequence(captured.LIGHTING_PRESETS[name]),
            reread=self._light_reads(),
            forget=self._forget_light,
        )
        await self._reread(self._light_reads())
        self._notify()

    def _forget_light(self) -> None:
        s = self.state
        s.light_on = s.light_mode = s.light_colours = s.light_name = s.light_solid = None

    async def handover_off(self) -> None:
        """The stream's hand-over: lights off, through the manual path, gated as lighting power."""
        await self.light_on_off(False)
