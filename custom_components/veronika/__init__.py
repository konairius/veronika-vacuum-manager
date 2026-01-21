import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform

from .const import DOMAIN, CONF_ROOMS, CONF_VACUUM, CONF_SEGMENTS, CONF_AREA, CONF_DEBUG, CONF_OCCUPANCY_COOLDOWN

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
