import logging
from typing import Any, Dict, List, Optional
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_ROOMS, CONF_AREA, CONF_VACUUM, CONF_SEGMENTS
from .utils import get_room_identity
from collections import Counter
from homeassistant.helpers import area_registry as ar

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: Dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[Dict[str, Any]] = None
) -> None:
    """Set up the Veronika switches."""
    if discovery_info is None:
        return

    rooms: List[Dict[str, Any]] = hass.data[DOMAIN][CONF_ROOMS]
    entities: List[VeronikaSwitch] = []
    
    area_counts = Counter(r[CONF_AREA] for r in rooms)

    for room in rooms:
        area_id = room[CONF_AREA]
        is_duplicate = area_counts[area_id] > 1
        
        slug, name = get_room_identity(hass, room, is_duplicate)
        
        entities.append(VeronikaSwitch(name, slug, "clean", "mdi:robot-vacuum"))
        entities.append(VeronikaSwitch(name, slug, "disable", "mdi:cancel"))

    async_add_entities(entities)

class VeronikaSwitch(SwitchEntity, RestoreEntity):
    def __init__(self, room_name: str, room_slug: str, switch_type: str, icon: str) -> None:
        self._room_name: str = room_name
        self._room_slug: str = room_slug
        self._type: str = switch_type
        self._attr_name: str = f"Veronika {switch_type.capitalize()} {room_name}"
        self._attr_unique_id: str = f"veronika_{switch_type}_{room_slug}"
        self._attr_icon: str = icon
        self._is_on: bool = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        
        # Register with Manager
        try:
            manager = self.hass.data.get(f"{DOMAIN}_manager")
            if manager:
                type_key = "switch_clean" if self._type == "clean" else "switch_disable"
                manager.register_entity(type_key, self._room_slug, self.entity_id)
            else:
                _LOGGER.warning(f"Manager not found for switch {self._attr_name}")
        except Exception as err:
            _LOGGER.error(f"Failed to register switch with manager: {err}")
            
        try:
            state = await self.async_get_last_state()
            if state:
                self._is_on = state.state == "on"
        except Exception as err:
            _LOGGER.warning(f"Failed to restore state for {self._attr_name}: {err}")
            # Default to False if restore fails
