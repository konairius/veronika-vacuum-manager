import logging
import asyncio
import time
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.const import (
    STATE_UNAVAILABLE, 
    STATE_UNKNOWN, 
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, CONF_ROOMS, CONF_NAME, CONF_VACUUM, CONF_SEGMENTS, CONF_DEBUG

_LOGGER = logging.getLogger(__name__)

class VeronikaManager:
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.config = config
        self.rooms = config[CONF_ROOMS]
        self.debug_mode = config.get(CONF_DEBUG, False)
        self._vacuum_monitors = {}
        
        # Map vacuum -> {segment_id: [switch_entity_id]}
        self._vacuum_segment_map = {}
        self._build_maps()

    def _build_maps(self):
        # We can't use entity registry here easily because it's async and this is init.
        # We will resolve IDs in async_setup
        pass

    async def async_setup(self):
        # Build maps now that we can use async methods
        ent_reg = er.async_get(self.hass)
        
        for room in self.rooms:
            vac = room[CONF_VACUUM]
            segments = room.get(CONF_SEGMENTS, [])
            name = room[CONF_NAME]
            
            from homeassistant.util import slugify
            slug = slugify(name)
            unique_id = f"veronika_clean_{slug}"
            
            # Resolve entity ID
            switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id)
            if not switch_id:
                # Fallback to default if not found (e.g. first run)
                switch_id = f"switch.veronika_clean_{slug}"
            
            if vac not in self._vacuum_segment_map:
                self._vacuum_segment_map[vac] = {}
            
            for seg in segments:
                if seg not in self._vacuum_segment_map[vac]:
                    self._vacuum_segment_map[vac][seg] = []
                self._vacuum_segment_map[vac][seg].append(switch_id)

        # Subscribe to vacuum state changes for monitoring segments
        vacuums = list(self._vacuum_segment_map.keys())
        async_track_state_change_event(self.hass, vacuums, self._on_vacuum_state_change)

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
        
        # Get current segment from attributes
        # Note: Attribute name depends on integration. 
        # Roborock/Dreame usually use 'current_segment' or similar.
        # The script used: state_attr(local_vacuum_entity, 'current_segment')
        new_segment = new_state.attributes.get("current_segment")
        
        # If vacuum is not cleaning/returning, reset monitor
        if new_state.state not in ["cleaning", "returning"]:
             # Check if we have a pending segment
             if monitor["current_segment"] is not None:
                 duration = time.time() - monitor["start_time"]
                 self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
             
             monitor["current_segment"] = None
             monitor["start_time"] = 0
             return

        # If segment changed
        if new_segment != monitor["current_segment"]:
            # Check if we need to complete the previous segment
            if monitor["current_segment"] is not None:
                duration = time.time() - monitor["start_time"]
                self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
            
            # Start tracking new segment
            monitor["current_segment"] = new_segment
            monitor["start_time"] = time.time()

    def _handle_segment_completion(self, vacuum_id, segment_id, duration):
        _LOGGER.info(f"Vacuum {vacuum_id} finished segment {segment_id} in {duration}s")
        
        if duration < 180:
            _LOGGER.info("Segment duration too short (<180s), not resetting toggles.")
            return

        # Find switches to turn off
        if vacuum_id in self._vacuum_segment_map:
            # segment_id might be int or string, ensure compatibility
            try:
                seg_int = int(segment_id)
            except (ValueError, TypeError):
                seg_int = segment_id

            switches = self._vacuum_segment_map[vacuum_id].get(seg_int, [])
            for switch in switches:
                _LOGGER.info(f"Resetting switch {switch}")
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch}
                    )
                )

    async def get_cleaning_plan(self, rooms_to_clean=None):
        """
        Calculate the cleaning plan based on current state.
        Returns a dict: { vacuum_entity_id: { 'rooms': [room_details], 'segments': [ids] } }
        """
        plan = {} # vacuum -> {'rooms': [], 'segments': []}
        ent_reg = er.async_get(self.hass)
        
        for room in self.rooms:
            name = room[CONF_NAME]
            vac = room[CONF_VACUUM]
            segments = room.get(CONF_SEGMENTS, [])
            
            # Initialize vacuum entry if missing
            if vac not in plan:
                plan[vac] = {'rooms': [], 'segments': []}

            # Resolve Entities
            from homeassistant.util import slugify
            slug = slugify(name)
            
            # Switch
            unique_id_switch = f"veronika_clean_{slug}"
            switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_switch)
            if not switch_id:
                switch_id = f"switch.veronika_clean_{slug}"

            # Disable Switch
            unique_id_disable = f"veronika_disable_{slug}"
            disable_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_disable)
            if not disable_id:
                disable_id = f"switch.veronika_disable_{slug}"
            
            # Sensor
            unique_id_sensor = f"veronika_status_{slug}"
            sensor_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, unique_id_sensor)
            if not sensor_id:
                sensor_id = f"binary_sensor.veronika_status_{slug}"

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
                if name in rooms_to_clean:
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
                "name": name,
                "will_clean": will_clean,
                "enabled": is_enabled,
                "disabled_override": is_disabled_override,
                "ready": is_ready,
                "reason": display_reason,
                "reasons": reasons,
                "sensor_reason": reason,
                "switch_entity_id": switch_id,
                "disable_entity_id": disable_id
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
        
        await self.hass.services.async_call(
            domain, service, payload["data"]
        )

    async def reset_all_toggles(self):
        ent_reg = er.async_get(self.hass)
        for room in self.rooms:
            from homeassistant.util import slugify
            slug = slugify(room[CONF_NAME])
            unique_id = f"veronika_clean_{slug}"
            switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id)
            if not switch_id:
                switch_id = f"switch.veronika_clean_{slug}"
                
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

