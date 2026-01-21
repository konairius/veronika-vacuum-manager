import logging
from typing import Any, Dict, List, Optional, Set
from homeassistant.helpers.entity import Entity
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_ROOMS, CONF_AREA
from .utils import get_room_identity
from collections import Counter

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: Dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[Dict[str, Any]] = None
) -> None:
    """Set up the Veronika sensor platform."""
    if discovery_info is None:
        return

    manager = hass.data[f"{DOMAIN}_manager"]
    async_add_entities([VeronikaPlanSensor(hass, manager)], True)

class VeronikaPlanSensor(Entity):
    """Representation of a Veronika Cleaning Plan Sensor."""

    def __init__(self, hass: HomeAssistant, manager: Any) -> None:
        """Initialize the sensor."""
        self.hass: HomeAssistant = hass
        self._manager: Any = manager
        self._attr_name: str = "Veronika Cleaning Plan"
        self._attr_unique_id: str = "veronika_cleaning_plan"
        self._attr_icon: str = "mdi:robot-vacuum"
        self._state: str = "Ready"
        self._attributes: Dict[str, Any] = {}
        self._entities_to_watch: Optional[Set[str]] = None  # Cache will be built in async_added_to_hass

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        # Build watch list from manager's entity cache (only once)
        if self._entities_to_watch is None:
            self._entities_to_watch = set()
            for cache_data in self._manager._entity_cache.values():
                self._entities_to_watch.add(cache_data['switch'])
                self._entities_to_watch.add(cache_data['disable'])
                self._entities_to_watch.add(cache_data['sensor'])

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, list(self._entities_to_watch), self._on_state_change
            )
        )
        self.async_schedule_update_ha_state(True)

    @callback
    def _on_state_change(self, event: Event) -> None:
        """Handle state changes."""
        self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        """Update the sensor state."""
        plan: Dict[str, Dict[str, Any]] = await self._manager.get_cleaning_plan()
        
        total_cleaning: int = 0
        vacuums_data: Dict[str, Dict[str, Any]] = {}
        
        for vac, data in plan.items():
            rooms = data['rooms']
            cleaning_count = sum(1 for r in rooms if r['will_clean'])
            total_cleaning += cleaning_count
            
            vacuums_data[vac] = {
                "rooms": rooms,
                "count": cleaning_count,
                "debug_command": data.get('debug_command')
            }
            
        self._state = f"{total_cleaning} Rooms Scheduled"
        self._attributes = {
            "plan": vacuums_data,
            "total_cleaning": total_cleaning
        }

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        return self._attributes
