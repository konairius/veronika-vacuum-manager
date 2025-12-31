import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.const import CONF_NAME

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_SEGMENTS, CONF_AREA

_LOGGER = logging.getLogger(__name__)

ROOM_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_VACUUM): cv.entity_id,
    vol.Required(CONF_AREA): cv.string,
    vol.Optional(CONF_SEGMENTS, default=[]): vol.All(cv.ensure_list, [int]),
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_ROOMS): vol.All(cv.ensure_list, [ROOM_SCHEMA]),
    }),
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Veronika component."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
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
    component_dir = os.path.dirname(__file__)
    hass.http.register_static_path(
        "/veronika/veronika-plan-card.js",
        os.path.join(component_dir, "www", "veronika-plan-card.js"),
        True
    )

    # Register services
    async def handle_reset_toggles(call):
        await manager.reset_all_toggles()

    async def handle_clean_all(call):
        await manager.start_cleaning()

    async def handle_clean_room(call):
        room_name = call.data.get("room_name")
        # Or maybe accept entity_id of the sensor?
        # The frontend sends "room_sensor" entity_id.
        # Let's support both or just map it.
        # If we get entity_id "binary_sensor.veronika_status_kitchen", we can derive the name or just pass it to manager.
        # But manager expects room names for start_cleaning.
        
        # Let's make manager smarter or handle it here.
        # If we get "room_sensor", we can find the room config.
        sensor_id = call.data.get("room_sensor")
        target_room_name = None
        
        if sensor_id:
            # Find room with this sensor id
            from homeassistant.util import slugify
            for room in conf[CONF_ROOMS]:
                slug = slugify(room[CONF_NAME])
                if f"binary_sensor.veronika_status_{slug}" == sensor_id:
                    target_room_name = room[CONF_NAME]
                    break
        
        if target_room_name:
            await manager.start_cleaning([target_room_name])
        else:
            _LOGGER.warning(f"Could not find room for sensor {sensor_id}")

    hass.services.async_register(DOMAIN, "reset_all_toggles", handle_reset_toggles)
    hass.services.async_register(DOMAIN, "clean_all_enabled", handle_clean_all)
    hass.services.async_register(DOMAIN, "clean_specific_room", handle_clean_room)

    return True
