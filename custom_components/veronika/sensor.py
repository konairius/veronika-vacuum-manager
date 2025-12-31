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
        self._entities_to_watch = set()

    async def async_added_to_hass(self):
        """Register callbacks."""
        # Resolve entities to watch
        ent_reg = er.async_get(self.hass)
        
        area_counts = Counter(r[CONF_AREA] for r in self._manager.rooms)
        
        for room in self._manager.rooms:
            area_id = room[CONF_AREA]
            is_duplicate = area_counts[area_id] > 1
            slug, _ = get_room_identity(self.hass, room, is_duplicate)
            
            # Switch
            unique_id_switch = f"veronika_clean_{slug}"
            unique_id_switch = f"veronika_clean_{slug}"
            switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_switch)
            if not switch_id:
                switch_id = f"switch.veronika_clean_{slug}"
            self._entities_to_watch.add(switch_id)

            # Disable Switch
            unique_id_disable = f"veronika_disable_{slug}"
            disable_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_disable)
            if not disable_id:
                disable_id = f"switch.veronika_disable_{slug}"
            self._entities_to_watch.add(disable_id)
            
            # Binary Sensor
            unique_id_sensor = f"veronika_status_{slug}"
            sensor_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, unique_id_sensor)
            if not sensor_id:
                sensor_id = f"binary_sensor.veronika_status_{slug}"
            self._entities_to_watch.add(sensor_id)

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
