"""BLE transport: one write characteristic, one notify characteristic, nothing else.

This module knows Bluetooth and nothing about what the bytes mean. It writes
whole frames to the command characteristic with Write Command (no response),
which is what Creative's app does, and reassembles notifications into frames.
The soundbar's second GATT service is never referenced here; a guard test fails
if any other characteristic UUID appears in the integration.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import NOTIFY_UUID, WRITE_UUID
from .device import KatanaCommandError
from .protocol import FrameReader

_LOGGER = logging.getLogger(__name__)

# Frames are never fragmented: the 5A framing has no continuation, so a frame
# longer than one Write Command can carry is refused rather than split.
_MIN_WRITE = 20

# The soundbar advertises with flags 0x0A, which habluetooth's passive-scan
# patterns (0x02 0x04 0x05 0x06 0x18 0x1A) do not match. A passively scanning
# adapter therefore hears it but BlueZ never puts it on the bus, and bleak
# cannot connect. An on-demand active sweep puts it there.
_ACTIVE_SWEEP_SECONDS = 10.0


class BleakTransport:
    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self._hass = hass
        self._address = address
        self._client: BleakClientWithServiceCache | None = None
        self._learned_limit = _MIN_WRITE
        self._reader = FrameReader()
        self.on_frame: Callable[[bytes], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def write_limit(self) -> int:
        """Largest frame one Write Command can carry on this link (negotiated MTU - 3).

        The characteristic's own figure is the documented source, but on HA's BlueZ
        it was seen stuck at the 23-byte default on one connection (the first
        connection read 197) while the soundbar was sending 40-byte frames. So the
        MTU learned at connect (``_learn_write_limit``) counts too.
        """
        client = self._client
        if client is None:
            return _MIN_WRITE
        return max(self._reported_limit(client), self._learned_limit)

    @staticmethod
    def _reported_limit(client: BleakClientWithServiceCache) -> int:
        char = client.services.get_characteristic(WRITE_UUID)
        return char.max_write_without_response_size if char is not None else _MIN_WRITE

    async def _learn_write_limit(self, client: BleakClientWithServiceCache) -> None:
        """If the characteristic reports the default, ask BlueZ for the negotiated MTU.

        ``_acquire_mtu`` (bleak's BlueZ backend) calls AcquireWrite and closes the
        returned socket at once: it learns the MTU and writes nothing to the device.
        """
        self._learned_limit = _MIN_WRITE
        reported = self._reported_limit(client)
        if reported > _MIN_WRITE:
            return
        backend = getattr(client, "_backend", None)
        acquire = getattr(backend, "_acquire_mtu", None)
        if acquire is None:
            return
        try:
            await acquire()
            self._learned_limit = max(_MIN_WRITE, backend.mtu_size - 3)
        except Exception as err:  # a best-effort probe
            _LOGGER.debug("Could not learn the MTU: %s", err)
        _LOGGER.debug("Write limit: characteristic reports %s, BlueZ MTU gives %s", reported, self._learned_limit)

    async def connect(self) -> None:
        if self.connected:
            return
        if not bluetooth.async_scanner_devices_by_address(self._hass, self._address, connectable=True):
            _LOGGER.debug("Katana not on any scanner's bus (passive scanning); requesting an active sweep")
            await bluetooth.async_request_active_scan(self._hass, _ACTIVE_SWEEP_SECONDS)
        ble_device = bluetooth.async_ble_device_from_address(self._hass, self._address, connectable=True)
        if ble_device is None:
            raise KatanaCommandError(f"soundbar {self._address} is not in range of a connectable Bluetooth adapter")
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            "Katana V2X",
            disconnected_callback=self._handle_disconnect,
            ble_device_callback=lambda: (
                bluetooth.async_ble_device_from_address(self._hass, self._address, connectable=True) or ble_device
            ),
        )
        self._reader.clear()
        try:
            await client.start_notify(NOTIFY_UUID, self._handle_notification)
        except BleakError:
            await client.disconnect()
            raise
        self._client = client
        await self._learn_write_limit(client)
        _LOGGER.info("Connected to the Katana at %s; write limit %s bytes", self._address, self.write_limit)

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            # Clear first so the disconnect callback does not trigger a reconnect.
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Disconnect failed: %s", err)

    async def write(self, frame: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise KatanaCommandError("soundbar not connected")
        limit = self.write_limit
        if len(frame) > limit:
            raise KatanaCommandError(f"frame of {len(frame)} bytes exceeds the link's {limit}-byte limit")
        try:
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
        except BleakError as err:
            raise KatanaCommandError(f"BLE write failed: {err}") from err

    def _handle_notification(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._reader.feed(bytes(data))
        for raw in self._reader.frames():
            if self.on_frame is not None:
                self.on_frame(raw)

    def _handle_disconnect(self, client: BleakClientWithServiceCache) -> None:
        if self._client is not client:
            return  # a deliberate disconnect, or a stale client
        self._client = None
        if self.on_disconnect is not None:
            self.on_disconnect()
