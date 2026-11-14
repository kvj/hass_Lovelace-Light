from __future__ import annotations
from .constants import *
from .coordinator import Coordinator
from . import public

from homeassistant.core import (
    HomeAssistant,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

from homeassistant.helpers import service, reload
from homeassistant.components import frontend, websocket_api, http
from aiohttp import web
from http import HTTPStatus

# from homeassistant.const import SERVICE_RELOAD


import voluptuous as vol
import logging
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
    }, extra=vol.ALLOW_EXTRA),
}, extra=vol.ALLOW_EXTRA)

async def _async_update_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.debug(f"_async_update_entry: {entry}, {entry.subentries}")
    coordinator = entry.runtime_data
    # entry.subentries
    await coordinator.async_unload()
    await coordinator.async_load()

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):

    _LOGGER.debug(f"async_setup_entry: {entry}, {entry.subentries}")
    entry.runtime_data = Coordinator(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_update_entry))
    await entry.runtime_data.async_config_entry_first_refresh()
    await entry.runtime_data.async_load()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_unload()
    entry.runtime_data = None
    return True

# def _register_service(hass: HomeAssistant,  name: str, handler, resp: SupportsResponse = SupportsResponse.NONE):
#     async def handler_(call):
#         await handler(_manager(hass), call.data)
#     hass.services.async_register(DOMAIN, name, handler_, supports_response=resp)
# 
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN, {})
    _LOGGER.debug(f"async_setup: {conf}")
    hass.data[DOMAIN] = conf
    # async def _async_reload_yaml(call):
    #     config = await reload.async_integration_yaml_config(hass, DOMAIN)
    #     conf = config.get(DOMAIN, {})
    #     _LOGGER.debug(f"_async_reload_yaml: {conf}")
    #     hass.data[DOMAIN] = conf
    # service.async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, _async_reload_yaml)
    for fn in (_ws_load_dashboard, _ws_do_action):
        websocket_api.async_register_command(hass, fn)

    paths = [
        http.StaticPathConfig("/lovelace_light/index.js", "{}/lovelace_light.js".format(public.locate_dir()), False),
        http.StaticPathConfig("/lovelace_light/index.css", "{}/lovelace_light.css".format(public.locate_dir()), False),
    ]
    for file in ("click0.wav", "click1.wav"):
        paths.append(http.StaticPathConfig("/lovelace_light/media/{}".format(file), "{}/media/{}".format(public.locate_dir(), file), False))
    await hass.http.async_register_static_paths(paths)
    hass.http.register_view(IndexHTML(hass))
    hass.http.register_view(ExtraCSS(hass))
    hass.http.register_view(MdiIconPNG(hass))
    return True

def _coordinator_by_id(hass: HomeAssistant, slug: str) -> Coordinator | None:
    for entry in hass.config_entries.async_entries(domain=DOMAIN):
        if entry.domain == DOMAIN and entry.runtime_data and entry.runtime_data._config.get(CONF_SLUG) == slug:
            _LOGGER.debug(f"_coordinator_by_id: entry: {entry}")
            return entry.runtime_data
    return None

@websocket_api.websocket_command({
    vol.Required("type"): "lovelace_light/get_dashboard",
    vol.Required("slug"): str,
    vol.Required("dashboard"): str,
    vol.Required("page"): str,
})
@websocket_api.async_response
async def _ws_load_dashboard(hass, connection, msg: dict):
    _LOGGER.debug("_ws_load_dashboard: %s", msg)
    dashboard = None
    if c := _coordinator_by_id(hass, msg.get("slug")):
        dashboard = await c.async_get_dashboard(msg.get("dashboard"), msg.get("page"))
    #     await c.async_handle_web_event(msg["event"], msg.get("data"))
    connection.send_result(msg["id"], {
        "response": "lovelace_light/get_dashboard",
        "dashboard": dashboard,
    })

@websocket_api.websocket_command({
    vol.Required("type"): "lovelace_light/action",
    vol.Required("slug"): str,
    vol.Required("dashboard"): str,
    vol.Required("page"): str,
    vol.Required("index"): int,
    vol.Required("action"): str,
})
@websocket_api.async_response
async def _ws_do_action(hass, connection, msg: dict):
    _LOGGER.debug("_ws_do_action: %s", msg)
    result = False
    if c := _coordinator_by_id(hass, msg.get("slug")):
        result = await c.async_do_action(msg.get("dashboard"), msg.get("page"), msg.get("index"), msg.get("action"))
    connection.send_result(msg["id"], {
        "response": "lovelace_light/action",
        "result": result,
    })

class IndexHTML(http.HomeAssistantView):
    """View to return index.html"""

    requires_auth = False
    url = "/lovelace_light/{slug}/{id}/{page}.html"
    name = "lovelace_light:index.html"

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def get(self, request: web.Request, slug: str, id: str, page: str) -> web.Response:
        _LOGGER.debug(f"IndexHTML::get: request: {slug}, {id}, {page}")
        if c := _coordinator_by_id(self.hass, slug):
            vars = await c.async_get_config_variables()
            config = ", ".join([f"\"{key}\": {value}" for key, value in vars.items()])
            response = web.Response(
                status=HTTPStatus.OK,
                body=public.LL_HTML.format(**{
                    "ts": datetime.now().timestamp(),
                    "slug": slug,
                    "id": id,
                    "page": page,
                    "config": config,
                }),
                content_type="text/html"
            )
            return response
        return web.Response(status=HTTPStatus.NOT_FOUND)

class ExtraCSS(http.HomeAssistantView):
    """View to return extra.css"""

    requires_auth = False
    url = "/lovelace_light/{slug}.extra.css"
    name = "lovelace_light:extra.css"

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def get(self, request: web.Request, slug: str) -> web.Response:
        _LOGGER.debug(f"ExtraCSS::get: request: {slug}")
        if c := _coordinator_by_id(self.hass, slug):
            response = web.Response(
                status=HTTPStatus.OK,
                body=public.LL_CSS.format(**{
                    "extra_css": c._config.get(CONF_CSS, "")
                }),
                content_type="text/css"
            )
            return response
        return web.Response(status=HTTPStatus.NOT_FOUND)

class MdiIconPNG(http.HomeAssistantView):
    """View to render png from mdi icon"""

    requires_auth = False
    url = "/lovelace_light/{slug}/mdi/{icon}/{color}/{size}.png"
    name = "lovelace_light:mdi.icon"

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def get(self, request: web.Request, slug: str, icon: str, color: str, size: str) -> web.Response:
        _LOGGER.debug(f"MdiIconPNG::get: request: {icon} / {color} / {size}")
        if c := _coordinator_by_id(self.hass, slug):
            if content := await c.async_render_mdi_icon(icon, color, int(size, base=10)):
                response = web.Response(
                    status=HTTPStatus.OK,
                    body=content,
                    content_type="image/png",
                )
                response.enable_compression()
                return response
        return web.Response(status=HTTPStatus.NOT_FOUND)
