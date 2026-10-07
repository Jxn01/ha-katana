"""The PC's screen-sync endpoint, and the equivalent service.

``POST /api/sb_katana/stream`` with ``{"rgb": [r, g, b]}`` and a long-lived
token; ``GET`` on the same path answers the stream's status (Screen sync,
receiving, whether the soundbar is connected, counters) for the PC's
diagnostics. It is an HTTP view rather than a service on purpose: every service call
fires a ``call_service`` bus event, the recorder stores every event (this HA has
no exclusions), and at 10 Hz that would be ~36,000 rows an hour. A view fires
no event. The ``stream_frame`` service exists for automations and tests.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_CONFIG_ENTRY_ID, ATTR_RGB, DOMAIN, SERVICE_STREAM_FRAME

if TYPE_CHECKING:
    from .stream import StreamController

_CHANNEL = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
FRAME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RGB): vol.All(vol.ExactSequence([_CHANNEL, _CHANNEL, _CHANNEL]), vol.Coerce(tuple)),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


class StreamTargetError(LookupError):
    pass


@callback
def _stream_for(hass: HomeAssistant, entry_id: str | None) -> StreamController:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id is not None:
        entries = [e for e in entries if e.entry_id == entry_id]
    if len(entries) != 1:
        raise StreamTargetError(
            "no loaded Katana entry" if not entries else "several Katana entries: pass config_entry_id"
        )
    return entries[0].runtime_data.stream


class KatanaStreamView(HomeAssistantView):
    url = "/api/sb_katana/stream"
    name = "api:sb_katana:stream"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        try:
            body = FRAME_SCHEMA(await request.json())
        except (ValueError, vol.Invalid) as err:
            return self.json_message(f"bad frame: {err}", HTTPStatus.BAD_REQUEST)
        try:
            stream = _stream_for(hass, body.get(ATTR_CONFIG_ENTRY_ID))
        except StreamTargetError as err:
            return self.json_message(str(err), HTTPStatus.NOT_FOUND)
        return self.json({"accepted": stream.handle_frame(body[ATTR_RGB])})

    async def get(self, request: web.Request) -> web.Response:
        try:
            stream = _stream_for(request.app[KEY_HASS], request.query.get(ATTR_CONFIG_ENTRY_ID))
        except StreamTargetError as err:
            return self.json_message(str(err), HTTPStatus.NOT_FOUND)
        return self.json(stream.status())


@callback
def async_setup_api(hass: HomeAssistant) -> None:
    hass.http.register_view(KatanaStreamView())

    async def handle_stream_frame(call: ServiceCall) -> None:
        try:
            stream = _stream_for(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        except StreamTargetError as err:
            raise ServiceValidationError(str(err)) from err
        stream.handle_frame(call.data[ATTR_RGB])

    hass.services.async_register(DOMAIN, SERVICE_STREAM_FRAME, handle_stream_frame, schema=FRAME_SCHEMA)
