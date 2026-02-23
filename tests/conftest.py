"""Shared fixtures for Veronika Vacuum Manager tests."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.veronika.const import (
    DOMAIN,
    CONF_ROOMS,
    CONF_AREA,
    CONF_VACUUM,
    CONF_SEGMENTS,
)


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry for device registration."""
    entry = MockConfigEntry(domain="test_vacuum", title="Test Vacuum")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def single_room_config() -> dict:
    """Return a basic single-room Veronika configuration."""
    return {
        CONF_ROOMS: [
            {
                CONF_AREA: "living_room",
                CONF_VACUUM: "vacuum.robot",
                CONF_SEGMENTS: [1],
            }
        ]
    }


@pytest.fixture
async def setup_area(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
) -> ar.AreaEntry:
    """Create a 'Living Room' area in the area registry."""
    return area_registry.async_get_or_create("living_room")


@pytest.fixture
async def setup_vacuum_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_config_entry: MockConfigEntry,
) -> dr.DeviceEntry:
    """Create a vacuum device with a Generic manufacturer."""
    return device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("test_vacuum", "robot_1")},
        name="Robot Vacuum",
        manufacturer="Generic",
    )


@pytest.fixture
async def setup_vacuum_entity(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
    setup_vacuum_device: dr.DeviceEntry,
) -> er.RegistryEntry:
    """Register a vacuum entity in the entity registry and set its state."""
    entry = entity_registry.async_get_or_create(
        domain="vacuum",
        platform="test_vacuum",
        unique_id="robot_1",
        config_entry=mock_config_entry,
        device_id=setup_vacuum_device.id,
        suggested_object_id="robot",
    )
    hass.states.async_set("vacuum.robot", "docked")
    return entry


@pytest.fixture
async def setup_switch_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> dict[str, str]:
    """Register Veronika switch entities and return their entity IDs."""
    clean = entity_registry.async_get_or_create(
        domain="switch",
        platform=DOMAIN,
        unique_id="veronika_clean_living_room",
        suggested_object_id="veronika_clean_living_room",
    )
    disable = entity_registry.async_get_or_create(
        domain="switch",
        platform=DOMAIN,
        unique_id="veronika_disable_living_room",
        suggested_object_id="veronika_disable_living_room",
    )
    sensor = entity_registry.async_get_or_create(
        domain="binary_sensor",
        platform=DOMAIN,
        unique_id="veronika_status_living_room",
        suggested_object_id="veronika_status_living_room",
    )
    return {
        "clean": clean.entity_id,
        "disable": disable.entity_id,
        "sensor": sensor.entity_id,
    }


@pytest.fixture
def mock_switch_service(hass: HomeAssistant) -> list:
    """Mock the switch service calls."""
    return async_mock_service(hass, "switch", "turn_on") + async_mock_service(
        hass, "switch", "turn_off"
    )
