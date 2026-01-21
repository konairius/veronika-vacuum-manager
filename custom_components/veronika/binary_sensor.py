import logging
from typing import Any, Dict, List, Optional, Set, Callable
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import area_registry as ar, entity_registry as er, device_registry as dr, template
from homeassistant.util import slugify, dt as dt_util
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_AREA, CONF_SEGMENTS, CONF_OCCUPANCY_COOLDOWN, CONF_SENSOR_PLATFORM
from .utils import get_room_identity, discover_occupancy_sensors, discover_door_sensors
from collections import Counter

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: Dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[Dict[str, Any]] = None
) -> None:
    if discovery_info is None:
        return

    global_config: Dict[str, Any] = hass.data[DOMAIN]
    rooms: List[Dict[str, Any]] = global_config[CONF_ROOMS]
    global_cooldown: int = global_config.get(CONF_OCCUPANCY_COOLDOWN, 0)
    global_sensor_platform: Optional[str] = global_config.get(CONF_SENSOR_PLATFORM)
    
    # Pre-calculate doors per vacuum to avoid repeated lookups
    vacuum_areas: Dict[str, Set[str]] = {}
    for room in rooms:
        vac: str = room[CONF_VACUUM]
        area: str = room[CONF_AREA]
        
        if vac not in vacuum_areas:
            vacuum_areas[vac] = set()
        vacuum_areas[vac].add(area)

    entities: List[VeronikaRoomSensor] = []
    area_counts: Counter = Counter(r[CONF_AREA] for r in rooms)
    
    for room in rooms:
        is_duplicate = area_counts[room[CONF_AREA]] > 1
        entities.append(VeronikaRoomSensor(hass, room, vacuum_areas, is_duplicate, global_cooldown, global_sensor_platform))

    async_add_entities(entities)

class VeronikaRoomSensor(BinarySensorEntity):
    def __init__(
        self,
        hass: HomeAssistant,
        config: Dict[str, Any],
        vacuum_areas: Dict[str, Set[str]],
        is_duplicate: bool,
        global_cooldown: int,
        global_sensor_platform: Optional[str]
    ) -> None:
        self.hass: HomeAssistant = hass
        self._config: Dict[str, Any] = config
        self._vacuum: str = config[CONF_VACUUM]
        self._area: str = config[CONF_AREA]
        self._segments: List[int] = config[CONF_SEGMENTS]
        self._vacuum_areas: Set[str] = vacuum_areas.get(self._vacuum, set())
        
        # Cooldown logic
        self._cooldown: int = config.get(CONF_OCCUPANCY_COOLDOWN, global_cooldown)
        self._sensor_platform: Optional[str] = config.get(CONF_SENSOR_PLATFORM, global_sensor_platform)

        self._last_occupancy_time: Optional[dt_util.dt.datetime] = None
        self._cooldown_timer: Optional[Callable[[], None]] = None
        
        self._slug, self._name = get_room_identity(hass, config, is_duplicate)

        self._attr_name = f"Veronika Status {self._name}"
        self._attr_unique_id = f"veronika_status_{self._slug}"
        self._attr_icon = "mdi:robot-vacuum"
        
        self._clean_switch: str = f"switch.veronika_clean_{self._slug}"
        self._disable_switch: str = f"switch.veronika_disable_{self._slug}"
        
        self._doors: List[str] = []
        self._occupancy: List[str] = []
        self._status_reason: str = "Initializing"
        self._is_on: bool = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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

    async def async_added_to_hass(self) -> None:
        # Resolve entity IDs from unique IDs
        ent_reg: er.EntityRegistry = er.async_get(self.hass)
        
        # Register with Manager
        manager = self.hass.data.get(f"{DOMAIN}_manager")
        if manager:
            manager.register_entity("binary_sensor", self._slug, self.entity_id)

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

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when entity is removed."""
        # Cancel any pending cooldown timer
        if self._cooldown_timer:
            self._cooldown_timer()
            self._cooldown_timer = None

    async def _discover_sensors(self) -> None:
        """Discover occupancy and door sensors for this room."""
        # Discover occupancy sensors in the room's area
        self._occupancy = discover_occupancy_sensors(self.hass, self._area, platform_filter=self._sensor_platform)
        
        # Discover door sensors in all areas the vacuum can access
        self._doors = discover_door_sensors(self.hass, list(self._vacuum_areas))

    @callback
    def _on_state_change(self, event: Event) -> None:
        self._update_state()

    @callback
    def _cooldown_expired(self, _: Any) -> None:
        self._cooldown_timer = None
        self._update_state()

    def _update_state(self) -> None:
        # Check Occupancy
        is_occupied = False
        for sens in self._occupancy:
            st = self.hass.states.get(sens)
            if st and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) and st.state == STATE_ON:
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
