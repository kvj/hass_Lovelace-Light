from PIL import Image, ImageDraw, ImageColor
import io

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryChange,
    ConfigEntryState,
    ConfigEntry
)

from homeassistant.helpers import (
    dispatcher,
    event,
    device_registry,
)
from homeassistant.util.yaml.loader import parse_yaml

from homeassistant.core import (
    callback,
    HomeAssistant,
)
from homeassistant.components import lovelace
from homeassistant.const import (
    CONF_DEVICE_ID,
    # CONF_NAME,
)


from .constants import *
from .mdi_font import GlyphProvider

import collections.abc
import logging
import json, copy, orjson
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)

class Coordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            setup_method=self._async_setup,
            update_method=self._async_update,
        )
        self._entry = entry
        self._entry_id = entry.entry_id
        self._variables = {}
        self._subentries = {}

        self._on_config_entry_handler = None
        self._on_device_updated_handler = None
        self._entry_data = None
        self._on_event_handler = None
        self._event_listeners = []

    async def _async_setup(self):
        self._mdi_font = GlyphProvider()
        await self.hass.async_add_executor_job(self._mdi_font.init)

    async def _async_update(self):
        return {
        }

    async def _async_update_state(self, data: dict):
        _LOGGER.debug(f"_async_update_state: {data}, {self.data}")
        new_state = {
            **self.data,
            **data,
        }
        if json.dumps(new_state) != json.dumps(self.data):
            new_state["ts"] = datetime.now().timestamp()
        self.async_set_updated_data(new_state)

    async def async_call_device_service(self, name: str, data: dict) -> bool:
        if not self.is_device_connected():
            _LOGGER.warning(f"async_call_device_service: not connected")
            return False
        for _, service in self._entry_data.services.items():
            if service.name == name:
                _LOGGER.debug(f"async_call_device_service: call service {name} with {data}, spec: {service}")
                await self._entry_data.client.execute_service(service, data)
                return True
        _LOGGER.warning(f"async_call_device_service: service not found: {name}")
        return False
    
    def _platform_config(self):
        return self.hass.data[DOMAIN]

    async def async_send_configuration(self):
        pass

    def add_event_listener(self, listener):
        self._event_listeners.append(listener)

    def remove_event_listener(self, listener):
        if listener in self._event_listeners:
            self._event_listeners.remove(listener)

    async def async_handle_event(self, type_: str, event: dict):
        _LOGGER.debug(f"async_handle_event: event = {event}")

    def subentry_config(self, id: str) -> dict:
        return self._subentries.get(id, {})

    def subentry_config_by_index(self, index: int) -> dict:
        return self.subentry_config(self._subentries_map.get(index))


    def load_options(self):
        self._config = {
            **self._entry.as_dict()["options"],
            "title": self._entry.title,
        }
        self._subentries = {}
        self._variables = {}
        try:
            if yaml_obj := parse_yaml(self._config[CONF_VARS]):
                self._variables = yaml_obj
        except:
            _LOGGER.exception(f"load_options: Invalid variables yaml")
        # index = 1
        # for id, entry in self._entry.subentries.items():
        #     self._subentries[id] = {
        #         **entry.as_dict()["data"],
        #         "title": entry.title,
        #     }
        #     self._subentries_map[index] = id
        #     index += 1
        # self._targets = []
        # for i in range(3):
        #     self._targets.append((-1, 0, 0, 0, None))

    def _config_entry_by_device_id(self, device_id: str):
        if device := device_registry.async_get(self.hass).async_get(device_id):
            _LOGGER.debug(f"_config_entry_by_device_id: device = {device}")
            for entry_id in device.config_entries:
                if entry := self.hass.config_entries.async_get_entry(entry_id):
                    _LOGGER.debug(f"_config_entry_by_device_id: entry: {entry}")
                    if entry.domain == "esphome":
                        return entry
        return None
    
    async def _async_on_device_event(self, event):
        type_ = event.data.get("type")
        await self.async_handle_event(type_, event.data)

    async def async_load(self):
        self.load_options()

    async def async_unload(self):
        _LOGGER.debug(f"async_unload:")

    def _disable_listener(self, listener):
        if listener:
            listener()
        return None

    def _make_grid_layout(self, items, cols: int, measure_fn, dense: bool = False):
        cells = []
        def add_row():
            cells.append([False for _ in range(cols)])
        col = 0
        row = 0
        def find_pos_in_row(w: int) -> int:
            while len(cells) <= row:
                add_row()
            if not dense:
                for x in range(col, cols):
                    if cells[row][x]:
                        return None
            for x in range(col, cols):
                if cols - x >= w:
                    all_false = True
                    for i in range(w):
                        if cells[row][x + i]:
                            all_false = False
                            break
                    if all_false:
                        # Found spot
                        return x
            return None
        def fill_item(x: int, y: int, w: int, h: int):
            while len(cells) < y + h:
                add_row()
            for y_ in range(y, y + h):
                for x_ in range(x, x + w):
                    cells[y_][x_] = True
        
        result = []
        for item in items:
            w, h, data = measure_fn(item)
            if w == 0 and h == 0:
                # Unsupported
                continue
            if w > cols:
                w = cols
            while (_ := find_pos_in_row(w)) == None:
                col = 0
                row += 1
            col = find_pos_in_row(w)
            fill_item(col, row, w, h)
            result.append((col, row, w, h, data))
            col += w
        return (len(cells), result)
    
    # Normal setup: 4 columns, 48 cells, 6 cells per tile, 6x1 - minimum size
    def _read_sections_layout(self, data):
        def _measure_item(data):
            if data.get("type") == "tile":
                vert = data.get("vertical", False)
                h = 2 if vert else 1
                cols = data.get("grid_options", {}).get("columns", 6)
                rows = data.get("grid_options", {}).get("rows", h)
                item = {
                    "layout": "tile",
                    "entity_id": data.get("entity"),
                    "title": data.get("name"),
                    "color": data.get("color"),
                    "icon": data.get("icon"),
                    "vertical": vert,
                    "hide_state": data.get("hide_state", False),
                }
                return (cols, rows, item)
            if data.get("type") == "button":
                cols = data.get("grid_options", {}).get("columns", 6)
                rows = data.get("grid_options", {}).get("rows", 2)
                item = {
                    "layout": "button",
                    "entity_id": data.get("entity"),
                    "title": data.get("name"),
                    "icon": data.get("icon"),
                    "show_state": data.get("show_state", False),
                    "show_title": data.get("show_name", True),
                }
                return (cols, rows, item)
            if data.get("type") == "entity":
                cols = data.get("grid_options", {}).get("columns", 6)
                rows = data.get("grid_options", {}).get("rows", 2)
                item = {
                    "layout": "entity",
                    "entity_id": data.get("entity"),
                    "title": data.get("name"),
                    "icon": data.get("icon"),
                    "unit": data.get("unit"),
                    "show_title": data.get("show_name", True),
                }
                return (cols, rows, item)
            if data.get("type") == "picture-entity":
                cols = data.get("grid_options", {}).get("columns", 6)
                rows = data.get("grid_options", {}).get("rows", 2)
                item = {
                    "layout": "picture",
                    "entity_id": data.get("entity"),
                    "mode": data.get("fit_mode"),
                }
                return (cols, rows, item)
            return (0, 0, None)
        def _measure_section(data):
            if data.get("type") == "grid":
                cards = data.get("cards", [])
                cols = data.get("column_span", 1) * 12
                rows, items = self._make_grid_layout(cards, cols, _measure_item, True)
                return (cols, rows, items)
            return (0, 0, None)
        items = data.get("sections", [])
        cols = data.get("max_columns", 4) * 12
        rows, items_ = self._make_grid_layout(items, cols, _measure_section)
        return (cols, rows, items_)

    def _serialize_layout(self, cols, rows, items):
        data = []
        for x_, y_, w_, h_, items_ in items:
            # Sections
            for x__, y__, w__, h__, item_ in items_:
                data.append({
                    "x": x_ + x__,
                    "y": y_ + y__,
                    "w": w__,
                    "h": h__,
                    "data": item_,
                })
        return {
            "cols": cols,
            "rows": rows,
            "items": data,
        }

    async def _async_get_sections_layout(self, id: str, page: str):
        dashboard = self.hass.data[lovelace.const.LOVELACE_DATA].dashboards.get(id)
        if dashboard:
            data_ = await dashboard.async_load(True)
            _LOGGER.debug(f"_async_get_sections_layout: dashboard: {dashboard.mode}, {data_}")
            for i, item in enumerate(data_.get("views", [])):
                path = item.get("path", i)
                _LOGGER.debug(f"async_get_dashboard: page: {path}, {page}")
                if str(path) == str(page) and item.get("type") == "sections":
                    return self._read_sections_layout(item)
        return (None, None, None)

    async def _async_execute_hass_action(self, entity_id: str, action_def: dict):
        [domain, name] = entity_id.split(".")
        action = "homeassistant.toggle"
        if domain == "script":
            action = entity_id
        elif domain == "automation":
            action = "automation.trigger"
        elif domain == "scene":
            action = "scene.apply"
        elif domain == "button":
            action = "button.press"
        
        _LOGGER.debug(f"_async_execute_hass_action: action = {action}, entity = {entity_id}")
        [domain, name] = action.split(".")
        await self.hass.services.async_call(domain, name, {
            "entity_id": entity_id,
            # **extra,
        }, blocking=False)

    async def async_do_action(self, id: str, page: str, index: int, action: str):
        _, _, items = await self._async_get_sections_layout(id, page)
        if items:
            index_ = 0
            for _, _, _, _, items_ in items:
                for _, _, _, _, item_ in items_:
                    if index_ == index and item_.get("entity_id"):
                        await self.async_fire_event(action, {
                            "entity_id": item_.get("entity_id"),
                            "dashboard": id,
                            "page": page,
                            "index": index,
                        })
                        try:
                            await self._async_execute_hass_action(item_["entity_id"], {})
                        except:
                            _LOGGER.exception(f"async_do_action: failed for: {item_} / {action}")
                            return False
                        return True
                    index_ += 1
        return False

    async def async_get_dashboard(self, id, page):
        _LOGGER.debug(f"async_get_dashboard: {id} / {page}")
        cols, rows, items = await self._async_get_sections_layout(id, page)
        if items:
            _LOGGER.debug(f"async_get_dashboard: result: {cols} / {rows} / {items}")
            return self._serialize_layout(cols, rows, items)
        return None

    async def async_render_mdi_icon(self, icon: str, color6x: str, size: int) -> bytes:
        bg_color = (0x00, 0x00, 0x00, 0x01)
        img = Image.new("RGBA", (size, size), bg_color)
        draw = ImageDraw.Draw(img)
        if self._mdi_font.draw_icon(draw, icon, size, int(size / 2), int(size / 2), ImageColor.getrgb(f"#{color6x}")):
            img_bytes = io.BytesIO()
            img.save(img_bytes, format="png")
            return img_bytes.getvalue()
        _LOGGER.warning(f"async_render_mdi_icon: icon not found: {icon}")
        return None

    async def async_get_config_variables(self):
        result = {}
        for key in VARIABLES_DEFAULT.keys():
            result[key] = self._variables.get(key, VARIABLES_DEFAULT[key])
        return result

    async def async_fire_event(self, name: str, extra: dict):
        _LOGGER.debug(f"async_fire_event: {name} with {extra}")
        for l in self._event_listeners:
            await l.async_on_event(name, extra)
        return None
    
class BaseEntity(CoordinatorEntity):

    def __init__(self, coordinator: Coordinator):
        super().__init__(coordinator)

    def with_name(self, suffix: str, name: str):
        self._attr_has_entity_name = True
        entry_id = self.coordinator._entry_id
        self._attr_unique_id = f"_{entry_id}_{suffix}"
        self._attr_name = name
        return self

    @property
    def device_info(self):
        return {
            "identifiers": {
                ("config_entry", self.coordinator._entry_id)
            },
            "name": self.coordinator._config["title"],
        }

    # @property
    # def available(self):
    #     return self.coordinator.is_device_connected()

class BaseSubEntity(CoordinatorEntity):

    def __init__(self, coordinator: Coordinator, subentry_id: str):
        super().__init__(coordinator)
        self._subentry_id = subentry_id

    def with_name(self, suffix: str, name: str):
        self._attr_has_entity_name = True
        entry_id = self._subentry_id
        self._attr_unique_id = f"_{entry_id}_{suffix}"
        self._attr_name = name
        return self
    
    @property
    def config(self):
        return self.coordinator.subentry_config(self._subentry_id)
    
    @property
    def device_info(self):
        return {
            "identifiers": {
                ("config_entry", self._subentry_id)
            },
            "name": self.config["title"],
        }

    # @property
    # def available(self):
    #     return self.coordinator.is_device_connected()
