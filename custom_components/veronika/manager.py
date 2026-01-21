import logging
import asyncio
import time
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, area_registry as ar
from homeassistant.const import (
    STATE_UNAVAILABLE, 
    STATE_UNKNOWN, 
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_SEGMENTS, CONF_DEBUG, CONF_AREA, CONF_MIN_SEGMENT_DURATION, CONF_SEGMENT_ATTRIBUTE
from .utils import get_room_identity
from collections import Counter

_LOGGER = logging.getLogger(__name__)

class VeronikaManager:
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.config = config
        self.rooms = config[CONF_ROOMS]
        self.debug_mode = config.get(CONF_DEBUG, False)
        self.min_segment_duration = config.get(CONF_MIN_SEGMENT_DURATION, 180)
        self._vacuum_monitors = {}
        self._unsubscribers = []  # Track listeners for cleanup
        
        # Map vacuum -> segment_attribute_name for different integrations
        self._vacuum_segment_attributes = {}
        global_segment_attr = config.get(CONF_SEGMENT_ATTRIBUTE, "current_segment")
        for room in self.rooms:
            vac = room[CONF_VACUUM]
            if vac not in self._vacuum_segment_attributes:
                # Per-room override or global default
                self._vacuum_segment_attributes[vac] = room.get(CONF_SEGMENT_ATTRIBUTE, global_segment_attr)
        
        # Map vacuum -> {segment_id: [switch_entity_id]}
        self._vacuum_segment_map = {}
        
        # Cache for entity IDs to avoid repeated registry lookups
        # Structure: {cache_key: {'switch': id, 'disable': id, 'sensor': id, 'slug': slug, 'name': name, ...}}
        self._entity_cache = {}
        
        self._build_maps()

    def _build_maps(self):
        # We can't use entity registry here easily because it's async and this is init.
        # We will resolve IDs in async_setup
        pass

    async def async_setup(self):
        # Build maps now that we can use async methods
        ent_reg = er.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        
        area_counts = Counter(r[CONF_AREA] for r in self.rooms)
        
        for room in self.rooms:
            vac = room[CONF_VACUUM]
            segments = room.get(CONF_SEGMENTS, [])
            area_id = room[CONF_AREA]
            
            is_duplicate = area_counts[area_id] > 1
            slug, display_name = get_room_identity(self.hass, room, is_duplicate)
            
            # Build entity cache for this room
            cache_key = f"{area_id}_{vac}_{'-'.join(map(str, segments))}"
            
            if cache_key not in self._entity_cache:
                unique_id = f"veronika_clean_{slug}"
                switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id)
                if not switch_id:
                    switch_id = f"switch.veronika_clean_{slug}"
                
                unique_id_disable = f"veronika_disable_{slug}"
                disable_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_disable)
                if not disable_id:
                    disable_id = f"switch.veronika_disable_{slug}"
                
                unique_id_sensor = f"veronika_status_{slug}"
                sensor_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, unique_id_sensor)
                if not sensor_id:
                    sensor_id = f"binary_sensor.veronika_status_{slug}"
                
                self._entity_cache[cache_key] = {
                    'switch': switch_id,
                    'disable': disable_id,
                    'sensor': sensor_id,
                    'slug': slug,
                    'name': display_name,
                    'area': area_id,
                    'vacuum': vac,
                    'segments': segments
                }
            
            # Build segment map using cached switch ID
            switch_id = self._entity_cache[cache_key]['switch']
            
            if vac not in self._vacuum_segment_map:
                self._vacuum_segment_map[vac] = {}
            
            for seg in segments:
                if seg not in self._vacuum_segment_map[vac]:
                    self._vacuum_segment_map[vac][seg] = []
                self._vacuum_segment_map[vac][seg].append(switch_id)

        # Subscribe to vacuum state changes for monitoring segments
        vacuums = list(self._vacuum_segment_map.keys())
        if vacuums:
            unsub = async_track_state_change_event(self.hass, vacuums, self._on_vacuum_state_change)
            self._unsubscribers.append(unsub)

    @callback
    def _on_vacuum_state_change(self, event):
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        
        if not new_state:
            return

        # Initialize monitor state if not exists
        if entity_id not in self._vacuum_monitors:
            self._vacuum_monitors[entity_id] = {
                "current_segment": None,
                "start_time": 0
            }
        
        monitor = self._vacuum_monitors[entity_id]
        
        # Get current segment from attributes using configured attribute name
        segment_attr = self._vacuum_segment_attributes.get(entity_id, "current_segment")
        new_segment = new_state.attributes.get(segment_attr)
        
        # If vacuum is not cleaning/returning, reset monitor
        if new_state.state not in ["cleaning", "returning"]:
             # Check if we have a pending segment
             if monitor["current_segment"] is not None:
                 duration = time.time() - monitor["start_time"]
                 self.hass.async_create_task(
                     self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
                 )
             
             monitor["current_segment"] = None
             monitor["start_time"] = 0
             return

        # If segment changed
        if new_segment != monitor["current_segment"]:
            # Check if we need to complete the previous segment
            if monitor["current_segment"] is not None:
                duration = time.time() - monitor["start_time"]
                self.hass.async_create_task(
                    self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
                )
            
            # Start tracking new segment
            monitor["current_segment"] = new_segment
            monitor["start_time"] = time.time()

    async def _handle_segment_completion(self, vacuum_id, segment_id, duration):
        _LOGGER.info(f"Vacuum {vacuum_id} finished segment {segment_id} in {duration}s")
        
        if duration < self.min_segment_duration:
            _LOGGER.info(f"Segment duration too short (<{self.min_segment_duration}s), not resetting toggles.")
            return

        # Find switches to turn off
        if vacuum_id in self._vacuum_segment_map:
            switches = self._vacuum_segment_map[vacuum_id].get(segment_id, [])
            for switch in switches:
                _LOGGER.info(f"Resetting switch {switch}")
                try:
                    await self.hass.services.async_call(
                        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch}
                    )
                except Exception as err:
                    _LOGGER.error(f"Failed to reset switch {switch}: {err}")

    async def get_cleaning_plan(self, rooms_to_clean=None):
        """Calculate the cleaning plan based on current state.
        Returns a dict: { vacuum_entity_id: { 'rooms': [room_details], 'segments': [ids] } }
        """
        plan = {}  # vacuum -> {'rooms': [], 'segments': []}
        
        # Use cached entity IDs instead of querying registry
        for cache_key, cache_data in self._entity_cache.items():
            vac = cache_data['vacuum']
            area_id = cache_data['area']
            segments = cache_data['segments']
            
            # Initialize vacuum entry if missing
            if vac not in plan:
                plan[vac] = {'rooms': [], 'segments': []}
            
            # Get entity IDs from cache
            switch_id = cache_data['switch']
            disable_id = cache_data['disable']
            sensor_id = cache_data['sensor']
            display_name = cache_data['name']

            # Get States
            switch_state = self.hass.states.get(switch_id)
            disable_state = self.hass.states.get(disable_id)
            sensor_state = self.hass.states.get(sensor_id)
            
            is_enabled = switch_state and switch_state.state == "on"
            is_disabled_override = disable_state and disable_state.state == "on"
            is_ready = sensor_state and sensor_state.state == "on"
            reason = sensor_state.attributes.get("status_reason", "Unknown") if sensor_state else "Sensor Unavailable"

            # Determine if it will be cleaned
            will_clean = False
            if rooms_to_clean:
                if area_id in rooms_to_clean:
                    will_clean = True 
            else:
                if is_enabled and is_ready and not is_disabled_override:
                    will_clean = True
            
            # Collect all reasons
            reasons = []
            if not is_enabled:
                reasons.append("Not Scheduled")
            if is_disabled_override:
                reasons.append("Disabled by Override")
            if not is_ready:
                reasons.append(reason)
            
            # Override reason for display if disabled (Legacy support, but we use reasons list now)
            display_reason = ", ".join(reasons) if reasons else "Scheduled"

            room_data = {
                "name": display_name,
                "will_clean": will_clean,
                "enabled": is_enabled,
                "disabled_override": is_disabled_override,
                "ready": is_ready,
                "reason": display_reason,
                "reasons": reasons,
                "sensor_reason": reason,
                "switch_entity_id": switch_id,
                "disable_entity_id": disable_id,
                "sensor_entity_id": sensor_id
            }
            
            plan[vac]['rooms'].append(room_data)
            
            if will_clean and segments:
                plan[vac]['segments'].extend(segments)
        
        # Deduplicate segments and add debug command
        for vac in plan:
            plan[vac]['segments'] = list(set(plan[vac]['segments']))
            if self.debug_mode:
                plan[vac]['debug_command'] = await self._get_vacuum_command_payload(vac, plan[vac]['segments'])
            
        return plan

    async def start_cleaning(self, rooms_to_clean=None):
        """
        Start cleaning for specific rooms or all enabled rooms.
        rooms_to_clean: list of room names (optional)
        """
        # 1. Identify what to clean
        plan = await self.get_cleaning_plan(rooms_to_clean)

        # 2. Execute Plan
        for vac, data in plan.items():
            segments = data['segments']
            if not segments:
                continue
            
            _LOGGER.info(f"Starting cleaning for {vac} segments: {segments}")
            
            await self._send_vacuum_command(vac, segments)

    async def _get_vacuum_command_payload(self, vacuum_entity, segments):
        # Determine manufacturer
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        
        manufacturer = ""
        entry = ent_reg.async_get(vacuum_entity)
        if entry and entry.device_id:
            device = dev_reg.async_get(entry.device_id)
            if device:
                manufacturer = device.manufacturer

        if manufacturer == "Roborock":
            return {
                "service": "vacuum.send_command",
                "data": {
                    ATTR_ENTITY_ID: vacuum_entity,
                    "command": "app_segment_clean",
                    "params": [{"segments": segments, "repeat": 1}]
                }
            }
        elif "Dreame" in manufacturer:
             return {
                "service": "dreame_vacuum.vacuum_clean_segment",
                "data": {
                    ATTR_ENTITY_ID: vacuum_entity,
                    "segments": segments
                }
            }
        else:
            return {
                "service": "vacuum.start",
                "data": {ATTR_ENTITY_ID: vacuum_entity}
            }

    async def _send_vacuum_command(self, vacuum_entity, segments):
        payload = await self._get_vacuum_command_payload(vacuum_entity, segments)
        service_call = payload["service"].split(".")
        domain = service_call[0]
        service = service_call[1]
        
        try:
            await self.hass.services.async_call(
                domain, service, payload["data"]
            )
            _LOGGER.info(f"Successfully sent command to {vacuum_entity} for segments {segments}")
        except Exception as err:
            _LOGGER.error(f"Failed to send command to {vacuum_entity}: {err}")

    async def reset_all_toggles(self):
        """Reset all cleaning toggles to ON."""
        for cache_data in self._entity_cache.values():
            switch_id = cache_data['switch']
            await self.hass.services.async_call(
                "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: switch_id}
            )

    async def stop_cleaning(self):
        vacuums = set(r[CONF_VACUUM] for r in self.rooms)
        for vac in vacuums:
            state = self.hass.states.get(vac)
            if state and state.state == "cleaning":
                await self.hass.services.async_call(
                    "vacuum", "return_to_base",
                    {ATTR_ENTITY_ID: vac}
                )

    async def async_unload(self):
        """Cleanup when unloading the integration."""
        # Unsubscribe from all state change listeners
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        
        # Clear caches and monitors
        self._vacuum_monitors.clear()
        self._vacuum_segment_map.clear()
        self._vacuum_segment_attributes.clear()
        self._entity_cache.clear()
        
        _LOGGER.info("Veronika manager unloaded successfully")

