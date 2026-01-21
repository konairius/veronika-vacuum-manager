import logging
from homeassistant.helpers.entity import Entity
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_ROOMS, CONF_AREA
from .utils import get_room_identity
from collections import Counter

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Veronika sensor platform."""
    if discovery_info is None:
        return

    manager = hass.data[f"{DOMAIN}_manager"]
    async_add_entities([VeronikaPlanSensor(hass, manager)], True)

class VeronikaPlanSensor(Entity):
    """Representation of a Veronika Cleaning Plan Sensor."""

    def __init__(self, hass, manager):
        """Initialize the sensor."""
        self.hass = hass
        self._manager = manager
        self._attr_name = "Veronika Cleaning Plan"
        self._attr_unique_id = "veronika_cleaning_plan"
        self._attr_icon = "mdi:robot-vacuum"
        self._state = "Ready"
        self._attributes = {}
        self._entities_to_watch = None  # Cache will be built in async_added_to_hass

    async def async_added_to_hass(self):
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
    def _on_state_change(self, event):
        """Handle state changes."""
        self.async_schedule_update_ha_state(True)

    async def async_update(self):
        """Update the sensor state."""
        plan = await self._manager.get_cleaning_plan()
        
        total_cleaning = 0
        vacuums_data = {}
        
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
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes
