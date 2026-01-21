import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers import area_registry as ar, entity_registry as er

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_SEGMENTS, CONF_AREA, CONF_DEBUG, CONF_OCCUPANCY_COOLDOWN, CONF_MIN_SEGMENT_DURATION

_LOGGER = logging.getLogger(__name__)

ROOM_SCHEMA = vol.Schema({
    vol.Required(CONF_VACUUM): cv.entity_id,
    vol.Required(CONF_AREA): cv.string,
    vol.Optional(CONF_SEGMENTS, default=[]): vol.All(cv.ensure_list, [int]),
    vol.Optional(CONF_OCCUPANCY_COOLDOWN): cv.positive_int,
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_ROOMS): vol.All(cv.ensure_list, [ROOM_SCHEMA]),
        vol.Optional(CONF_DEBUG, default=False): cv.boolean,
        vol.Optional(CONF_OCCUPANCY_COOLDOWN, default=0): cv.positive_int,
        vol.Optional(CONF_MIN_SEGMENT_DURATION, default=180): cv.positive_int,
    }),
}, extra=vol.ALLOW_EXTRA)

async def _validate_configuration(hass: HomeAssistant, config: dict) -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []
    area_reg = ar.async_get(hass)
    rooms = config[CONF_ROOMS]
    
    for idx, room in enumerate(rooms):
        room_desc = f"Room {idx + 1} ({room.get(CONF_AREA, 'unknown')})"
        
        # Validate vacuum entity exists
        vacuum_entity = room[CONF_VACUUM]
        vacuum_state = hass.states.get(vacuum_entity)
        if not vacuum_state:
            errors.append(f"{room_desc}: Vacuum entity '{vacuum_entity}' does not exist")
        elif not vacuum_entity.startswith('vacuum.'):
            errors.append(f"{room_desc}: Entity '{vacuum_entity}' is not a vacuum entity")
        
        # Validate area exists
        area_id = room[CONF_AREA]
        area = area_reg.async_get_area(area_id)
        if not area:
            # Try to find area by name
            area = area_reg.async_get_area_by_name(area_id)
            if not area:
                errors.append(f"{room_desc}: Area '{area_id}' does not exist")
        
        # Validate segments
        segments = room.get(CONF_SEGMENTS, [])
        if segments is not None and len(segments) == 0 and vacuum_state:
            # Empty segments is allowed but warn if it seems unintentional
            _LOGGER.warning(f"{room_desc}: No segments configured - room will not be cleaned")
        
        # Validate cooldown if specified
        cooldown = room.get(CONF_OCCUPANCY_COOLDOWN)
        if cooldown is not None and cooldown < 0:
            errors.append(f"{room_desc}: Occupancy cooldown cannot be negative")
    
    return errors

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Veronika component."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    
    # Validate configuration
    validation_errors = await _validate_configuration(hass, conf)
    if validation_errors:
        for error in validation_errors:
            _LOGGER.error(f"Configuration validation error: {error}")
        _LOGGER.error("Veronika integration setup aborted due to configuration errors")
        return False
    
    hass.data[DOMAIN] = conf

    # Initialize Manager
    from .manager import VeronikaManager
    manager = VeronikaManager(hass, conf)
    await manager.async_setup()
    hass.data[f"{DOMAIN}_manager"] = manager

    # Load platforms
    hass.async_create_task(async_load_platform(hass, "binary_sensor", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "switch", DOMAIN, {}, config))
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))
    
    # Register static path for card
    import os
    from homeassistant.components.http import StaticPathConfig

    component_dir = os.path.dirname(__file__)
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            "/veronika/veronika-plan-card.js",
            os.path.join(component_dir, "www", "veronika-plan-card.js"),
            True
        )
    ])

    # Register services
    async def handle_reset_toggles(call):
        await manager.reset_all_toggles()

    async def handle_clean_all(call):
        await manager.start_cleaning()

    async def handle_clean_room(call):
        area = call.data.get("area")
        if area:
            await manager.start_cleaning([area])
        else:
            _LOGGER.warning("No area specified for clean_specific_room service")

    async def handle_stop_cleaning(call):
        await manager.stop_cleaning()

    hass.services.async_register(DOMAIN, "reset_all_toggles", handle_reset_toggles)
    hass.services.async_register(DOMAIN, "clean_all_enabled", handle_clean_all)
    hass.services.async_register(DOMAIN, "clean_specific_room", handle_clean_room)
    hass.services.async_register(DOMAIN, "stop_cleaning", handle_stop_cleaning)

    return True

async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Unload Veronika integration."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["binary_sensor", "switch", "sensor"]
    )
    
    if unload_ok:
        # Cleanup manager
        manager = hass.data.get(f"{DOMAIN}_manager")
        if manager:
            await manager.async_unload()
        
        # Remove services
        hass.services.async_remove(DOMAIN, "reset_all_toggles")
        hass.services.async_remove(DOMAIN, "clean_all_enabled")
        hass.services.async_remove(DOMAIN, "clean_specific_room")
        hass.services.async_remove(DOMAIN, "stop_cleaning")
        
        # Clear stored data
        hass.data.pop(DOMAIN, None)
        hass.data.pop(f"{DOMAIN}_manager", None)
    
    return unload_ok
