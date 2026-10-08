"""Screen sync: turn a stream of colours from the PC into solid-colour writes.

The PC (ambience-rgb) posts colours as fast as it likes. This controller sends
at most ``rate_hz`` writes a second, always the newest colour, skips a colour
equal to the last one sent, and owns the hand-over: ``timeout_s`` after the last
frame it turns the lighting off once, leaving Screen sync on so the next frame
resumes.

Nothing here touches entity state per frame. The only state that changes is
``receiving`` -- at the first frame and at the hand-over -- so a whole
screen-sync session costs two recorder rows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from . import protocol as p
from .device import KatanaCommandError, KatanaDevice

_LOGGER = logging.getLogger(__name__)

Rgb = tuple[int, int, int]


class StreamController:
    def __init__(self, hass: HomeAssistant, device: KatanaDevice, rate_hz: float, timeout_s: float) -> None:
        self._hass = hass
        self._device = device
        self.rate_hz = rate_hz
        self.timeout_s = timeout_s
        self.screen_sync = True
        self.receiving = False
        self.frames_received = 0
        self.frames_dropped = 0
        self.writes_sent = 0
        self._pending: Rgb | None = None
        self._last_sent: Rgb | None = None
        self._needs_prepare = True
        self._prepared_generation = -1  # the device connection the last prepare went out on
        self._last_write_at = float("-inf")
        self._flush_unsub: CALLBACK_TYPE | None = None
        self._handover_unsub: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def handle_frame(self, rgb: Rgb) -> bool:
        """Take one colour from the PC. Returns False if Screen sync is off and it was dropped."""
        if not self.screen_sync:
            self.frames_dropped += 1
            return False
        self.frames_received += 1
        if not self._device.available:
            # The PC is posting colours, so the soundbar is probably wanted -- and may be awake again.
            self._device.request_reconnect("screen-sync colours arriving")
        if self._handover_unsub is not None:
            self._handover_unsub()
        self._handover_unsub = async_call_later(self._hass, self.timeout_s, self._handover)
        if not self.receiving:
            self.receiving = True
            self._needs_prepare = True
            self._notify()
        self._pending = rgb
        self._schedule_flush()
        return True

    def _schedule_flush(self) -> None:
        if self._flush_unsub is not None:
            return  # a flush is already due; it will take the newest colour
        delay = self._last_write_at + 1.0 / self.rate_hz - self._hass.loop.time()
        if delay <= 0:
            self._flush()
        else:
            self._flush_unsub = async_call_later(self._hass, delay, self._flush_timer)

    @callback
    def _flush_timer(self, _now) -> None:
        self._flush_unsub = None
        self._flush()

    def _flush(self) -> None:
        rgb, self._pending = self._pending, None
        if rgb is None or not self.screen_sync:
            return
        # Prepare again after every (re)connect: the link may have dropped across a
        # hand-over, or the Creative app may have changed the lighting meanwhile.
        generation = self._device.connect_count
        prepare = self._needs_prepare or generation != self._prepared_generation
        if rgb == self._last_sent and not prepare:
            return
        cmds = [*p.solo_prepare()] if prepare else []
        cmds.append(p.solo_colour(rgb))
        self._device.submit_stream(cmds, prepare=prepare, on_done=partial(self._batch_done, prepare))
        self._last_sent = rgb
        self._needs_prepare = False
        if prepare:
            self._prepared_generation = generation
        self._last_write_at = self._hass.loop.time()
        self.writes_sent += 1

    def _batch_done(self, prepared: bool, ok: bool) -> None:
        """A batch that never reached the soundbar is not 'sent': prepare and resend next time."""
        if ok:
            return
        self._needs_prepare = True
        self._last_sent = None
        if prepared:
            self._prepared_generation = -1

    @callback
    def _handover(self, _now) -> None:
        """The PC went quiet: lights off once. Screen sync stays on."""
        self._handover_unsub = None
        self._stop_receiving()
        self._hass.async_create_task(self._power_off(), "sb_katana hand-over")

    async def _power_off(self) -> None:
        try:
            await self._device.handover_off()
        except KatanaCommandError as err:
            _LOGGER.warning("Screen sync hand-over could not turn the lighting off: %s", err)

    def _stop_receiving(self) -> None:
        for unsub in (self._flush_unsub, self._handover_unsub):
            if unsub is not None:
                unsub()
        self._flush_unsub = self._handover_unsub = None
        self._pending = None
        self._last_sent = None
        self._needs_prepare = True
        self._device.clear_stream()
        if self.receiving:
            self.receiving = False
            self._notify()

    @callback
    def set_screen_sync(self, on: bool) -> None:
        """Switching Screen sync off stops applying frames; it does not turn the lighting off."""
        if on == self.screen_sync:
            return
        self.screen_sync = on
        if not on:
            self._stop_receiving()
        self._notify()

    @callback
    def manual_override(self) -> None:
        """A manual lighting change from HA: Screen sync yields, and stays off until switched back on."""
        self.set_screen_sync(False)

    def status(self) -> dict[str, object]:
        """What ``GET /api/sb_katana/stream`` answers, and diagnostics show: no entity state, no recorder row."""
        return {
            "screen_sync": self.screen_sync,
            "receiving": self.receiving,
            "available": self._device.available,
            "rate_hz": self.rate_hz,
            "timeout_s": self.timeout_s,
            "frames_received": self.frames_received,
            "frames_dropped": self.frames_dropped,
            "writes_sent": self.writes_sent,
            "write_errors": self._device.stream_errors,
        }

    @callback
    def shutdown(self) -> None:
        self._stop_receiving()
