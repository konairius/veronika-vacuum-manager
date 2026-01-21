import logging
import asyncio
import time
from typing import Any, Dict, List, Optional, Set, Callable, Tuple
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers import device_registry as dr, entity_registry as er, area_registry as ar
from homeassistant.util import dt as dt_util
from homeassistant.const import (
    STATE_UNAVAILABLE, 
    STATE_UNKNOWN, 
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.components.persistent_notification import async_create as async_create_notification

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_SEGMENTS, CONF_DEBUG, CONF_AREA, CONF_MIN_SEGMENT_DURATION, CONF_SEGMENT_ATTRIBUTE
from .utils import get_room_identity
from collections import Counter

_LOGGER = logging.getLogger(__name__)

class VeronikaManager:
    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]) -> None:
        self.hass: HomeAssistant = hass
        self.config: Dict[str, Any] = config
        self.rooms: List[Dict[str, Any]] = config[CONF_ROOMS]
        self.debug_mode: bool = config.get(CONF_DEBUG, False)
        self.min_segment_duration: int = config.get(CONF_MIN_SEGMENT_DURATION, 180)
        self._vacuum_monitors: Dict[str, Dict[str, Any]] = {}  # Structure: {vacuum_id: {current_segment, start_time, completion_task}}
        self._unsubscribers: List[Callable[[], None]] = []  # Track listeners for cleanup
        
        # Map vacuum -> segment_attribute_name for different integrations
        self._vacuum_segment_attributes: Dict[str, str] = {}
        global_segment_attr: str = config.get(CONF_SEGMENT_ATTRIBUTE, "current_segment")
        for room in self.rooms:
            vac: str = room[CONF_VACUUM]
            if vac not in self._vacuum_segment_attributes:
                # Per-room override or global default
                self._vacuum_segment_attributes[vac] = room.get(CONF_SEGMENT_ATTRIBUTE, global_segment_attr)
        
        # Map vacuum -> {segment_id: [switch_entity_id]}
        self._vacuum_segment_map: Dict[str, Dict[int, List[str]]] = {}
        
        # Cache for entity IDs to avoid repeated registry lookups
        # Structure: {(area_id, vacuum, segments_tuple): {'switch': id, 'disable': id, 'sensor': id, ...}}
        self._entity_cache: Dict[Tuple[str, str, Tuple[int, ...]], Dict[str, Any]] = {}
        
        # Error tracking
        self._last_error: Optional[str] = None
        self._error_count: int = 0
        
        self._build_maps()

    def _build_maps(self) -> None:
        # We can't use entity registry here easily because it's async and this is init.
        # We will resolve IDs in async_setup
        pass

    def register_entity(self, entity_type: str, slug: str, entity_id: str) -> None:
        """Register an entity with the manager."""
        # Find the cache entry with matching slug
        target_key: Optional[Tuple[str, str, Tuple[int, ...]]] = None
        for key, data in self._entity_cache.items():
            if data['slug'] == slug:
                target_key = key
                break
        
        if not target_key:
            _LOGGER.warning(f"Attempted to register {entity_type} for unknown room slug {slug}")
            return

        # Update cache
        if entity_type == 'switch_clean':
            self._entity_cache[target_key]['switch'] = entity_id
            self._update_vacuum_segment_map(target_key)
        elif entity_type == 'switch_disable':
            self._entity_cache[target_key]['disable'] = entity_id
        elif entity_type == 'binary_sensor':
            self._entity_cache[target_key]['sensor'] = entity_id

    def _update_vacuum_segment_map(self, cache_key: Tuple[str, str, Tuple[int, ...]]) -> None:
        """Update the vacuum segment map for a specific cache entry."""
        data: Dict[str, Any] = self._entity_cache[cache_key]
        vac: str = data['vacuum']
        segments: List[int] = data['segments']
        switch_id: Optional[str] = data['switch']
        
        if not switch_id:
            return

        if vac not in self._vacuum_segment_map:
            self._vacuum_segment_map[vac] = {}
        
        for seg in segments:
            if seg not in self._vacuum_segment_map[vac]:
                self._vacuum_segment_map[vac][seg] = []
            
            # Add if not present
            if switch_id not in self._vacuum_segment_map[vac][seg]:
                self._vacuum_segment_map[vac][seg].append(switch_id)

    async def async_setup(self) -> None:
        # Build maps now that we can use async methods
        ent_reg: er.EntityRegistry = er.async_get(self.hass)
        area_reg: ar.AreaRegistry = ar.async_get(self.hass)
        
        area_counts: Counter = Counter(r[CONF_AREA] for r in self.rooms)
        
        for room in self.rooms:
            vac: str = room[CONF_VACUUM]
            segments: List[int] = room.get(CONF_SEGMENTS, [])
            area_id: str = room[CONF_AREA]
            
            is_duplicate: bool = area_counts[area_id] > 1
            slug, display_name = get_room_identity(self.hass, room, is_duplicate)
            
            # Build entity cache for this room using tuple key to avoid collisions
            # Tuple format: (area_id, vacuum, sorted_segments_tuple)
            segments_tuple: Tuple[int, ...] = tuple(sorted(segments))
            cache_key: Tuple[str, str, Tuple[int, ...]] = (area_id, vac, segments_tuple)
            
            if cache_key not in self._entity_cache:
                unique_id = f"veronika_clean_{slug}"
                switch_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id)
                # if not switch_id:
                #    switch_id = f"switch.veronika_clean_{slug}"
                
                unique_id_disable = f"veronika_disable_{slug}"
                disable_id = ent_reg.async_get_entity_id("switch", DOMAIN, unique_id_disable)
                # if not disable_id:
                #     disable_id = f"switch.veronika_disable_{slug}"
                
                unique_id_sensor = f"veronika_status_{slug}"
                sensor_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, unique_id_sensor)
                # if not sensor_id:
                #     sensor_id = f"binary_sensor.veronika_status_{slug}"
                
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
            if switch_id:
                self._update_vacuum_segment_map(cache_key)

        # Subscribe to vacuum state changes for monitoring segments
        vacuums = list(self._vacuum_segment_map.keys())
        if vacuums:
            # Validate vacuums exist before subscribing
            missing_vacuums = []
            for vac in vacuums:
                if not self.hass.states.get(vac):
                    missing_vacuums.append(vac)
            
            if missing_vacuums:
                _LOGGER.warning(
                    f"The following vacuum entities are not available yet: {', '.join(missing_vacuums)}. "
                    "Veronika will start monitoring them when they become available."
                )
            
            unsub = async_track_state_change_event(self.hass, vacuums, self._on_vacuum_state_change)
            self._unsubscribers.append(unsub)

    @callback
    def _on_vacuum_state_change(self, event: Event) -> None:
        entity_id: Optional[str] = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        
        if not new_state or not entity_id:
            return

        # Initialize monitor state if not exists
        if entity_id not in self._vacuum_monitors:
            self._vacuum_monitors[entity_id] = {
                "current_segment": None,
                "start_time": None,
                "completion_task": None
            }
        
        monitor = self._vacuum_monitors[entity_id]
        
        # Get current segment from attributes using configured attribute name
        segment_attr = self._vacuum_segment_attributes.get(entity_id, "current_segment")
        new_segment = new_state.attributes.get(segment_attr)
        
        # If vacuum is not cleaning/returning, reset monitor
        if new_state.state not in ["cleaning", "returning"]:
            # Check if we have a pending segment
            if monitor["current_segment"] is not None and monitor["start_time"] is not None:
                duration = dt_util.now().timestamp() - monitor["start_time"]
                
                # Cancel any pending completion task to avoid duplicate processing
                if monitor["completion_task"] and not monitor["completion_task"].done():
                    monitor["completion_task"].cancel()
                
                monitor["completion_task"] = self.hass.async_create_task(
                    self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
                )
            
            monitor["current_segment"] = None
            monitor["start_time"] = None
            return

        # If segment changed
        if new_segment != monitor["current_segment"]:
            # Check if we need to complete the previous segment
            if monitor["current_segment"] is not None and monitor["start_time"] is not None:
                duration = dt_util.now().timestamp() - monitor["start_time"]
                
                # Cancel any pending completion task to avoid race conditions
                if monitor["completion_task"] and not monitor["completion_task"].done():
                    monitor["completion_task"].cancel()
                
                monitor["completion_task"] = self.hass.async_create_task(
                    self._handle_segment_completion(entity_id, monitor["current_segment"], duration)
                )
            
            # Start tracking new segment
            monitor["current_segment"] = new_segment
            monitor["start_time"] = dt_util.now().timestamp()

    async def _handle_segment_completion(self, vacuum_id: str, segment_id: int, duration: float) -> None:
        _LOGGER.info(f"Vacuum {vacuum_id} finished segment {segment_id} in {duration}s")
        
        if duration < self.min_segment_duration:
            _LOGGER.info(f"Segment duration too short (<{self.min_segment_duration}s), not resetting toggles.")
            return

        # Find switches to turn off
        if vacuum_id not in self._vacuum_segment_map:
            _LOGGER.warning(f"Vacuum {vacuum_id} not found in segment map")
            return
            
        switches = self._vacuum_segment_map[vacuum_id].get(segment_id, [])
        if not switches:
            _LOGGER.debug(f"No switches configured for vacuum {vacuum_id} segment {segment_id}")
            return
            
        failed_switches: List[str] = []
        for switch in switches:
            _LOGGER.info(f"Resetting switch {switch}")
            try:
                # Retry logic for transient failures
                for attempt in range(3):
                    try:
                        await self.hass.services.async_call(
                            "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch}, blocking=True
                        )
                        break
                    except (asyncio.TimeoutError, Exception) as err:
                        if attempt < 2:
                            _LOGGER.warning(f"Retry {attempt + 1}/3 resetting switch {switch}: {err}")
                            await asyncio.sleep(1)
                        else:
                            raise
            except ServiceNotFound as err:
                _LOGGER.error(f"Switch service not found for {switch}: {err}")
                failed_switches.append(switch)
            except Exception as err:
                _LOGGER.error(f"Failed to reset switch {switch} after 3 attempts: {err}")
                failed_switches.append(switch)
                self._error_count += 1
                self._last_error = f"Failed to reset {switch}: {str(err)}"
        
        if failed_switches:
            await self._notify_error(
                f"Failed to reset {len(failed_switches)} switch(es) after cleaning segment {segment_id}",
                f"Switches: {', '.join(failed_switches)}"
            )

    async def _notify_error(self, title: str, message: str) -> None:
        """Create a persistent notification for errors."""
        try:
            await async_create_notification(
                self.hass,
                message=message,
                title=f"Veronika: {title}",
                notification_id=f"veronika_error_{int(time.time())}"
            )
        except Exception as err:
            _LOGGER.error(f"Failed to create error notification: {err}")

    async def get_cleaning_plan(self, rooms_to_clean: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Calculate the cleaning plan based on current state.
        Returns a dict: { vacuum_entity_id: { 'rooms': [room_details], 'segments': [ids] } }
        """
        plan: Dict[str, Dict[str, Any]] = {}  # vacuum -> {'rooms': [], 'segments': []}
        
        # Use cached entity IDs instead of querying registry
        for cache_key, cache_data in self._entity_cache.items():
            vac = cache_data['vacuum']
            area_id = cache_data['area']
            segments = cache_data['segments']
            
            # Initialize vacuum entry if missing
            if vac not in plan:
                plan[vac] = {'rooms': [], 'segments': []}
            
            # Get entity IDs from cache
            switch_id = cache_data.get('switch')
            disable_id = cache_data.get('disable')
            sensor_id = cache_data.get('sensor')
            display_name = cache_data.get('name', 'Unknown')
            
            # Skip if essential entities are missing
            if not switch_id or not sensor_id:
                _LOGGER.warning(f"Missing essential entities for area {area_id}, skipping")
                continue

            # Get States with error handling
            try:
                switch_state = self.hass.states.get(switch_id)
                disable_state = self.hass.states.get(disable_id) if disable_id else None
                sensor_state = self.hass.states.get(sensor_id)
            except Exception as err:
                _LOGGER.error(f"Error accessing states for area {area_id}: {err}")
                continue
            
            # Safe state checks
            is_enabled = switch_state is not None and switch_state.state == "on"
            is_disabled_override = disable_state is not None and disable_state.state == "on"
            is_ready = sensor_state is not None and sensor_state.state == "on"
            
            # Safe attribute access
            reason = "Unknown"
            if sensor_state:
                try:
                    reason = sensor_state.attributes.get("status_reason", "Unknown")
                except (AttributeError, KeyError):
                    reason = "Sensor Error"
            else:
                reason = "Sensor Unavailable"

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

    async def start_cleaning(self, rooms_to_clean: Optional[List[str]] = None) -> None:
        """
        Start cleaning for specific rooms or all enabled rooms.
        rooms_to_clean: list of room names (optional)
        """
        try:
            # 1. Identify what to clean
            plan: Dict[str, Dict[str, Any]] = await self.get_cleaning_plan(rooms_to_clean)
            
            if not plan:
                _LOGGER.warning("No cleaning plan generated, nothing to clean")
                return

            # 2. Execute Plan
            failed_vacuums: List[str] = []
            for vac, data in plan.items():
                segments = data.get('segments', [])
                if not segments:
                    _LOGGER.debug(f"No segments to clean for {vac}")
                    continue
                
                # Validate vacuum exists
                vacuum_state = self.hass.states.get(vac)
                if not vacuum_state:
                    error_msg = (
                        f"Vacuum entity {vac} not found. "
                        f"Please ensure your vacuum integration is loaded and the entity exists."
                    )
                    _LOGGER.error(error_msg)
                    failed_vacuums.append(vac)
                    continue
                
                _LOGGER.info(f"Starting cleaning for {vac} segments: {segments}")
                
                try:
                    await self._send_vacuum_command(vac, segments)
                except Exception as err:
                    _LOGGER.error(f"Failed to send cleaning command to {vac}: {err}")
                    failed_vacuums.append(vac)
            
            if failed_vacuums:
                await self._notify_error(
                    "Cleaning Start Failed",
                    f"Failed to start cleaning for: {', '.join(failed_vacuums)}"
                )
        except Exception as err:
            _LOGGER.error(f"Unexpected error in start_cleaning: {err}", exc_info=True)
            self._last_error = str(err)
            self._error_count += 1
            await self._notify_error("Cleaning Error", f"Unexpected error: {str(err)}")
            raise HomeAssistantError(f"Failed to start cleaning: {err}") from err

    async def _get_vacuum_command_payload(self, vacuum_entity: str, segments: List[int]) -> Dict[str, Any]:
        """Generate vacuum command payload based on manufacturer."""
        if not segments:
            raise ValueError(f"No segments provided for {vacuum_entity}")
            
        # Determine manufacturer
        try:
            ent_reg: er.EntityRegistry = er.async_get(self.hass)
            dev_reg: dr.DeviceRegistry = dr.async_get(self.hass)
        except Exception as err:
            _LOGGER.error(f"Failed to access registries: {err}")
            raise HomeAssistantError(f"Registry access error: {err}") from err
        
        manufacturer: str = ""
        entry: Optional[er.RegistryEntry] = ent_reg.async_get(vacuum_entity)
        if entry and entry.device_id:
            device = dev_reg.async_get(entry.device_id)
            if device and device.manufacturer:
                manufacturer = device.manufacturer
            else:
                _LOGGER.warning(f"No device found for vacuum {vacuum_entity}")
        else:
            _LOGGER.warning(f"No registry entry found for vacuum {vacuum_entity}")

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

    async def _send_vacuum_command(self, vacuum_entity: str, segments: List[int]) -> None:
        """Send cleaning command to vacuum with retry logic."""
        try:
            payload: Dict[str, Any] = await self._get_vacuum_command_payload(vacuum_entity, segments)
        except Exception as err:
            _LOGGER.error(f"Failed to generate command payload for {vacuum_entity}: {err}")
            raise HomeAssistantError(f"Command generation failed: {err}") from err
            
        if "service" not in payload or "data" not in payload:
            raise HomeAssistantError(f"Invalid payload structure for {vacuum_entity}")
            
        try:
            service_call: List[str] = payload["service"].split(".")
            if len(service_call) != 2:
                raise ValueError(f"Invalid service format: {payload['service']}")
            domain: str = service_call[0]
            service: str = service_call[1]
        except (KeyError, ValueError, IndexError) as err:
            _LOGGER.error(f"Invalid service in payload: {err}")
            raise HomeAssistantError(f"Service parsing error: {err}") from err
        
        # Retry logic for service calls
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                await self.hass.services.async_call(
                    domain, service, payload["data"], blocking=True
                )
                _LOGGER.info(f"Successfully sent command to {vacuum_entity} for segments {segments}")
                return
            except ServiceNotFound as err:
                _LOGGER.error(f"Service {domain}.{service} not found for {vacuum_entity}: {err}")
                raise HomeAssistantError(f"Service not available: {domain}.{service}") from err
            except asyncio.TimeoutError as err:
                last_error = err
                if attempt < 2:
                    _LOGGER.warning(f"Timeout on attempt {attempt + 1}/3 for {vacuum_entity}, retrying...")
                    await asyncio.sleep(2)
                else:
                    _LOGGER.error(f"Service call timed out after 3 attempts for {vacuum_entity}")
            except Exception as err:
                last_error = err
                if attempt < 2:
                    _LOGGER.warning(f"Error on attempt {attempt + 1}/3 for {vacuum_entity}: {err}, retrying...")
                    await asyncio.sleep(2)
                else:
                    _LOGGER.error(f"Failed to send command to {vacuum_entity} after 3 attempts: {err}")
        
        # If we get here, all retries failed
        self._error_count += 1
        self._last_error = f"Failed to command {vacuum_entity}: {str(last_error)}"
        raise HomeAssistantError(f"Failed to send command after 3 attempts: {last_error}") from last_error

    async def reset_all_toggles(self) -> None:
        """Reset all cleaning toggles to ON."""
        failed_switches: List[str] = []
        
        for cache_data in self._entity_cache.values():
            switch_id: Optional[str] = cache_data.get('switch')
            if not switch_id:
                continue
                
            try:
                await self.hass.services.async_call(
                    "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: switch_id}, blocking=True
                )
            except Exception as err:
                _LOGGER.error(f"Failed to reset toggle {switch_id}: {err}")
                failed_switches.append(switch_id)
        
        if failed_switches:
            await self._notify_error(
                "Toggle Reset Failed",
                f"Failed to reset {len(failed_switches)} toggle(s): {', '.join(failed_switches)}"
            )

    async def stop_cleaning(self) -> None:
        """Stop all active vacuums and return them to base."""
        vacuums: Set[str] = set(r[CONF_VACUUM] for r in self.rooms)
        failed_vacuums: List[str] = []
        
        for vac in vacuums:
            try:
                state = self.hass.states.get(vac)
                if not state:
                    _LOGGER.warning(f"Vacuum {vac} state not found")
                    continue
                    
                if state.state == "cleaning":
                    await self.hass.services.async_call(
                        "vacuum", "return_to_base",
                        {ATTR_ENTITY_ID: vac},
                        blocking=True
                    )
                    _LOGGER.info(f"Sent return to base command to {vac}")
            except Exception as err:
                _LOGGER.error(f"Failed to stop vacuum {vac}: {err}")
                failed_vacuums.append(vac)
        
        if failed_vacuums:
            await self._notify_error(
                "Stop Cleaning Failed",
                f"Failed to stop {len(failed_vacuums)} vacuum(s): {', '.join(failed_vacuums)}"
            )

    async def async_unload(self) -> None:
        """Cleanup when unloading the integration."""
        # Cancel any pending completion tasks
        for monitor in self._vacuum_monitors.values():
            if monitor.get("completion_task") and not monitor["completion_task"].done():
                monitor["completion_task"].cancel()
        
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

