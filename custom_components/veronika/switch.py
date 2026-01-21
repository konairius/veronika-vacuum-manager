import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import DOMAIN, CONF_ROOMS, CONF_AREA, CONF_VACUUM, CONF_SEGMENTS
from .utils import get_room_identity
from collections import Counter
from homeassistant.helpers import area_registry as ar

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Veronika switches."""
    if discovery_info is None:
        return

    rooms = hass.data[DOMAIN][CONF_ROOMS]
    entities = []
    
    area_counts = Counter(r[CONF_AREA] for r in rooms)

    for room in rooms:
        area_id = room[CONF_AREA]
        is_duplicate = area_counts[area_id] > 1
        
        slug, name = get_room_identity(hass, room, is_duplicate)
        
        entities.append(VeronikaSwitch(name, slug, "clean", "mdi:robot-vacuum"))
        entities.append(VeronikaSwitch(name, slug, "disable", "mdi:cancel"))

    async_add_entities(entities)

class VeronikaSwitch(SwitchEntity, RestoreEntity):
    def __init__(self, room_name, room_slug, switch_type, icon):
        self._room_name = room_name
        self._room_slug = room_slug
        self._type = switch_type
        self._attr_name = f"Veronika {switch_type.capitalize()} {room_name}"
        self._attr_unique_id = f"veronika_{switch_type}_{room_slug}"
        self._attr_icon = icon
        self._is_on = False

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        
        # Register with Manager
        manager = self.hass.data.get(f"{DOMAIN}_manager")
        if manager:
            type_key = "switch_clean" if self._type == "clean" else "switch_disable"
            manager.register_entity(type_key, self._room_slug, self.entity_id)
            
        state = await self.async_get_last_state()
        if state:
            self._is_on = state.state == "on"
