"""BleakTransport: the active sweep for passively scanned adapters, the write limit, reassembly."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sb_katana import transport as t
from custom_components.sb_katana.const import NOTIFY_UUID, WRITE_UUID
from custom_components.sb_katana.device import KatanaCommandError

ADDRESS = "FF:00:00:00:00:01"


def fake_client(limit: int = 197) -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    client.disconnect = AsyncMock()
    client.write_gatt_char = AsyncMock()
    char = MagicMock()
    char.max_write_without_response_size = limit
    client.services.get_characteristic.return_value = char
    return client


@pytest.fixture
def bt():
    with (
        patch.object(t.bluetooth, "async_scanner_devices_by_address", return_value=[]) as devices,
        patch.object(t.bluetooth, "async_request_active_scan", new=AsyncMock()) as sweep,
        patch.object(t.bluetooth, "async_ble_device_from_address", return_value=MagicMock()) as ble,
        patch.object(t, "establish_connection", new=AsyncMock(return_value=fake_client())) as connect,
    ):
        yield devices, sweep, ble, connect


async def test_sweeps_actively_when_no_scanner_has_the_device(hass, bt):
    _, sweep, _, connect = bt
    transport = t.BleakTransport(hass, ADDRESS)
    await transport.connect()
    sweep.assert_awaited_once()
    connect.assert_awaited_once()
    connect.return_value.start_notify.assert_awaited_once()
    assert connect.return_value.start_notify.await_args.args[0] == NOTIFY_UUID


async def test_no_sweep_when_a_scanner_already_has_it(hass, bt):
    devices, sweep, _, _ = bt
    devices.return_value = [MagicMock()]
    await t.BleakTransport(hass, ADDRESS).connect()
    sweep.assert_not_awaited()


async def test_not_in_range_raises(hass, bt):
    _, _, ble, _ = bt
    ble.return_value = None
    with pytest.raises(KatanaCommandError, match="not in range"):
        await t.BleakTransport(hass, ADDRESS).connect()


async def test_write_uses_write_command_to_the_write_uuid(hass, bt):
    _, _, _, connect = bt
    transport = t.BleakTransport(hass, ADDRESS)
    await transport.connect()
    await transport.write(bytes.fromhex("5a3a022501"))
    connect.return_value.write_gatt_char.assert_awaited_once_with(
        WRITE_UUID, bytes.fromhex("5a3a022501"), response=False
    )


async def test_frame_over_the_write_limit_is_refused(hass, bt):
    _, _, _, connect = bt
    connect.return_value = fake_client(limit=20)
    transport = t.BleakTransport(hass, ADDRESS)
    await transport.connect()
    with pytest.raises(KatanaCommandError, match="exceeds"):
        await transport.write(bytes(23))
    connect.return_value.write_gatt_char.assert_not_awaited()


async def test_notifications_are_reassembled(hass, bt):
    transport = t.BleakTransport(hass, ADDRESS)
    frames: list[bytes] = []
    transport.on_frame = frames.append
    await transport.connect()
    transport._handle_notification(None, bytearray.fromhex("5a2c0501"))
    transport._handle_notification(None, bytearray.fromhex("020000005a0300"))
    assert frames == [bytes.fromhex("5a2c050102000000"), bytes.fromhex("5a0300")]


async def test_unexpected_disconnect_is_reported_and_deliberate_one_is_not(hass, bt):
    _, _, _, connect = bt
    transport = t.BleakTransport(hass, ADDRESS)
    calls: list[int] = []
    transport.on_disconnect = lambda: calls.append(1)
    await transport.connect()
    transport._handle_disconnect(connect.return_value)
    assert calls == [1] and not transport.connected
    connect.return_value = fake_client()
    await transport.connect()
    await transport.disconnect()
    transport._handle_disconnect(connect.return_value)
    assert calls == [1]
