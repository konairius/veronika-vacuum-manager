import logging
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import area_registry as ar, entity_registry as er, device_registry as dr, template
from homeassistant.util import slugify, dt as dt_util
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_AREA, CONF_SEGMENTS, CONF_OCCUPANCY_COOLDOWN
from .utils import get_room_identity
from collections import Counter

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return

    global_config = hass.data[DOMAIN]
    rooms = global_config[CONF_ROOMS]
    global_cooldown = global_config.get(CONF_OCCUPANCY_COOLDOWN, 0)
    
    # Pre-calculate doors per vacuum to avoid repeated lookups
    vacuum_areas = {}
    for room in rooms:
        vac = room[CONF_VACUUM]
        area = room[CONF_AREA]
        
        if vac not in vacuum_areas:
            vacuum_areas[vac] = set()
        vacuum_areas[vac].add(area)

    entities = []
    area_counts = Counter(r[CONF_AREA] for r in rooms)
    
    for room in rooms:
        is_duplicate = area_counts[room[CONF_AREA]] > 1
        entities.append(VeronikaRoomSensor(hass, room, vacuum_areas, is_duplicate, global_cooldown))

    async_add_entities(entities)

class VeronikaRoomSensor(BinarySensorEntity):
    def __init__(self, hass, config, vacuum_areas, is_duplicate, global_cooldown):
        self.hass = hass
        self._config = config
        self._vacuum = config[CONF_VACUUM]
        self._area = config[CONF_AREA]
        self._segments = config[CONF_SEGMENTS]
        self._vacuum_areas = vacuum_areas.get(self._vacuum, set())
        
        # Cooldown logic
        self._cooldown = config.get(CONF_OCCUPANCY_COOLDOWN, global_cooldown)
        self._last_occupancy_time = None
        self._cooldown_timer = None
        
        self._slug, self._name = get_room_identity(hass, config, is_duplicate)

        self._attr_name = f"Veronika Status {self._name}"
        self._attr_unique_id = f"veronika_status_{self._slug}"
        self._attr_icon = "mdi:robot-vacuum"
        
        self._clean_switch = f"switch.veronika_clean_{self._slug}"
        self._disable_switch = f"switch.veronika_disable_{self._slug}"
        
        self._doors = []
        self._occupancy = []
        self._status_reason = "Initializing"
        self._is_on = False

    @property
    def is_on(self):
        return self._is_on

    @property
    def extra_state_attributes(self):
        return {
            "veronika_segments": self._segments,
            "veronika_vacuum": self._vacuum,
            "veronika_area": self._area,
            "status_reason": self._status_reason,
            "veronika_door_sensors": self._doors,
            "veronika_occupancy_sensors": self._occupancy,
            "veronika_disable_entity": self._disable_switch,
            "veronika_clean_entity": self._clean_switch
        }

    async def async_added_to_hass(self):
        # Resolve entity IDs from unique IDs
        ent_reg = er.async_get(self.hass)
        
        clean_unique_id = f"veronika_clean_{self._slug}"
        disable_unique_id = f"veronika_disable_{self._slug}"
        
        clean_entry = ent_reg.async_get_entity_id("switch", DOMAIN, clean_unique_id)
        if clean_entry:
            self._clean_switch = clean_entry
            
        disable_entry = ent_reg.async_get_entity_id("switch", DOMAIN, disable_unique_id)
        if disable_entry:
            self._disable_switch = disable_entry

        # Discover sensors
        await self._discover_sensors()
        
        # Subscribe to state changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, 
                [self._clean_switch, self._disable_switch, self._vacuum] + self._doors + self._occupancy,
                self._on_state_change
            )
        )
        self._update_state()

    async def _discover_sensors(self):
        # 1. Occupancy
        # Use robust discovery logic similar to HA core templates
        
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        
        def get_area_entities(area_id):
            entities = set()
            # Entities directly in area
            for entry in er.async_entries_for_area(ent_reg, area_id):
                entities.add(entry.entity_id)
            
            # Entities in devices in area
            for device in dr.async_entries_for_area(dev_reg, area_id):
                for entry in er.async_entries_for_device(ent_reg, device.id):
                    if entry.area_id is None:
                        entities.add(entry.entity_id)
            return list(entities)

        # Occupancy
        area_ents = get_area_entities(self._area)
        self._occupancy = []
        for ent_id in area_ents:
            entry = ent_reg.async_get(ent_id)
            state = self.hass.states.get(ent_id)
            
            # Check if it is from magic_areas
            is_magic = entry and entry.platform == "magic_areas"
            
            # Check device class (prefer state attributes for overrides)
            device_class = None
            if state:
                device_class = state.attributes.get("device_class")
            elif entry:
                device_class = entry.device_class or entry.original_device_class
                
            if is_magic and device_class == "occupancy":
                 self._occupancy.append(ent_id)

        # Doors
        self._doors = []
        for area_id in self._vacuum_areas:
            area_ents = get_area_entities(area_id)
            for ent_id in area_ents:
                entry = ent_reg.async_get(ent_id)
                state = self.hass.states.get(ent_id)
                
                device_class = None
                if state:
                    device_class = state.attributes.get("device_class")
                elif entry:
                    device_class = entry.device_class or entry.original_device_class
                
                if device_class == "door":
                    self._doors.append(ent_id)

    @callback
    def _on_state_change(self, event):
        self._update_state()

    @callback
    def _cooldown_expired(self, _):
        self._cooldown_timer = None
        self._update_state()

    def _update_state(self):
        # Check Occupancy
        is_occupied = False
        for sens in self._occupancy:
            st = self.hass.states.get(sens)
            if st and st.state == STATE_ON:
                is_occupied = True
                break
        
        if is_occupied:
            self._status_reason = "Occupied"
            self._is_on = False
            self._last_occupancy_time = dt_util.now()
            
            # Cancel any pending cooldown timer
            if self._cooldown_timer:
                self._cooldown_timer()
                self._cooldown_timer = None
                
            self.async_write_ha_state()
            return

        # Check Cooldown
        if self._last_occupancy_time and self._cooldown > 0:
            elapsed = (dt_util.now() - self._last_occupancy_time).total_seconds()
            if elapsed < self._cooldown:
                self._status_reason = "Occupied (Cooldown)"
                self._is_on = False
                
                # Schedule update for when cooldown expires
                if not self._cooldown_timer:
                    remaining = self._cooldown - elapsed
                    self._cooldown_timer = async_call_later(self.hass, remaining + 1, self._cooldown_expired)
                
                self.async_write_ha_state()
                return

        # If we are here, occupancy is clear and cooldown is over
        if self._cooldown_timer:
             self._cooldown_timer()
             self._cooldown_timer = None

        # Check Doors
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        
        # Get Vacuum Area
        vacuum_area = None
        vac_entry = ent_reg.async_get(self._vacuum)
        if vac_entry and vac_entry.area_id:
            vacuum_area = vac_entry.area_id
        elif vac_entry and vac_entry.device_id:
            dev = dev_reg.async_get(vac_entry.device_id)
            if dev:
                vacuum_area = dev.area_id
        
        target_area = self._area
        
        for door in self._doors:
            st = self.hass.states.get(door)
            if st and st.state == STATE_OFF: # Door Closed
                # Find area of this door
                door_area = None
                d_entry = ent_reg.async_get(door)
                if d_entry:
                    door_area = d_entry.area_id
                    # Fallback to device area if entity area is not set
                    if not door_area and d_entry.device_id:
                        dev = dev_reg.async_get(d_entry.device_id)
                        if dev:
                            door_area = dev.area_id
                
                # 1. Target Room Door
                if door_area == target_area and vacuum_area != target_area:
                    self._status_reason = "Door Closed"
                    self._is_on = False
                    self.async_write_ha_state()
                    return
                
                # 2. Current Room Door (Trapped)
                if door_area == vacuum_area and vacuum_area != target_area:
                    self._status_reason = "Trapped"
                    self._is_on = False
                    self.async_write_ha_state()
                    return

        self._status_reason = "Ready"
        self._is_on = True
        self.async_write_ha_state()
