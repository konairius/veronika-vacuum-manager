import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import DOMAIN, CONF_ROOMS, CONF_NAME

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Veronika switches."""
    if discovery_info is None:
        return

    rooms = hass.data[DOMAIN][CONF_ROOMS]
    entities = []

    for room in rooms:
        name = room[CONF_NAME]
        slug = slugify(name)
        entities.append(VeronikaSwitch(name, slug, "clean", "mdi:robot-vacuum"))
        entities.append(VeronikaSwitch(name, slug, "disable", "mdi:cancel"))

    async_add_entities(entities)

class VeronikaSwitch(SwitchEntity, RestoreEntity):
    def __init__(self, room_name, room_slug, switch_type, icon):
        self._room_name = room_name
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
        state = await self.async_get_last_state()
        if state:
            self._is_on = state.state == "on"
