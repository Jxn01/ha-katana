"""Constants for the Sound Blaster Katana V2X integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "sb_katana"
MANUFACTURER: Final = "Creative Technology"
MODEL: Final = "Sound Blaster Katana V2X"
MODEL_ID: Final = "MF8400"
DEFAULT_NAME: Final = "Sound Blaster Katana V2X"

# The BLE control device advertises the command service UUID; its name, "Control for
# MF8400" (with trailing NULs), is only in the scan response, which an adapter in passive
# scanning mode (HA's here) never receives.
LOCAL_NAME_PREFIX: Final = "Control for MF8400"
SERVICE_UUID: Final = "9e9daaea-3a10-4fe8-b69f-7397aff77886"

# The command channel: frames go to WRITE_UUID (Write Command), replies arrive on
# NOTIFY_UUID. The soundbar's second GATT service is never touched.
WRITE_UUID: Final = "9e9daaec-3a10-4fe8-b69f-7397aff77886"
NOTIFY_UUID: Final = "9e9daaeb-3a10-4fe8-b69f-7397aff77886"

CONF_ALLOW_UNCONFIRMED: Final = "allow_unconfirmed"
CONF_STREAM_RATE: Final = "stream_rate_hz"
CONF_STREAM_TIMEOUT: Final = "stream_timeout_s"
DEFAULT_STREAM_RATE: Final = 10
DEFAULT_STREAM_TIMEOUT: Final = 10
STREAM_RATE_RANGE: Final = (1, 20)
STREAM_TIMEOUT_RANGE: Final = (3, 120)

SERVICE_STREAM_FRAME: Final = "stream_frame"
ATTR_RGB: Final = "rgb"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

REPLY_TIMEOUT: Final = 2.0
POLL_INTERVAL: Final = 60
RECONNECT_BACKOFF: Final = (5, 10, 30, 60, 120, 300)
