"""Tests for Veronika utility functions."""
import pytest
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.veronika.const import CONF_AREA, CONF_VACUUM, CONF_SEGMENTS
from custom_components.veronika.utils import (
    get_area_entities,
    get_entity_device_class,
    discover_occupancy_sensors,
    discover_door_sensors,
    get_room_identity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_room(area="kitchen", vacuum="vacuum.robot", segments=None):
    """Build a room config dict."""
    return {
        CONF_AREA: area,
        CONF_VACUUM: vacuum,
        CONF_SEGMENTS: segments if segments is not None else [1],
    }


# ---------------------------------------------------------------------------
# TestGetAreaEntities
# ---------------------------------------------------------------------------


class TestGetAreaEntities:
    """Tests for get_area_entities."""

    async def test_empty_area(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
    ) -> None:
        """Area with no entities and no devices returns empty list."""
        area_registry.async_get_or_create("kitchen")
        result = get_area_entities(hass, "kitchen")
        assert result == []

    async def test_direct_entities_only(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Returns entities directly assigned to the area."""
        area = area_registry.async_get_or_create("kitchen")
        entity_registry.async_get_or_create(
            domain="light",
            platform="test",
            unique_id="kitchen_main",
            config_entry=mock_config_entry,
            suggested_object_id="kitchen_main",
        )
        entity_registry.async_update_entity(
            "light.kitchen_main", area_id=area.id,
        )
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="kitchen_temp",
            config_entry=mock_config_entry,
            suggested_object_id="kitchen_temp",
        )
        entity_registry.async_update_entity(
            "sensor.kitchen_temp", area_id=area.id,
        )

        result = get_area_entities(hass, area.id)
        assert sorted(result) == ["light.kitchen_main", "sensor.kitchen_temp"]

    async def test_device_entities_with_no_area(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Includes device entities where area_id is None (inheriting from device)."""
        area = area_registry.async_get_or_create("kitchen")
        device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "device_1")},
            name="Kitchen Device",
        )
        device_registry.async_update_device(device.id, area_id=area.id)
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="device_sensor",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="device_sensor",
        )
        # Entity has no explicit area_id, inherits from device

        result = get_area_entities(hass, area.id)
        assert "sensor.device_sensor" in result

    async def test_device_entities_with_own_area_excluded(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Excludes device entities that have their own area_id set."""
        kitchen = area_registry.async_get_or_create("kitchen")
        living = area_registry.async_get_or_create("living_room")
        device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "device_1")},
            name="Kitchen Device",
        )
        device_registry.async_update_device(device.id, area_id=kitchen.id)
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="device_sensor",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="device_sensor",
        )
        # Override entity to a different area
        entity_registry.async_update_entity(
            "sensor.device_sensor", area_id=living.id,
        )

        result = get_area_entities(hass, kitchen.id)
        assert "sensor.device_sensor" not in result

    async def test_deduplication(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Same entity from direct and device lookup appears only once."""
        area = area_registry.async_get_or_create("kitchen")
        device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "device_1")},
            name="Kitchen Device",
        )
        device_registry.async_update_device(device.id, area_id=area.id)
        # Entity directly assigned to area AND on device in same area
        entity_registry.async_get_or_create(
            domain="light",
            platform="test",
            unique_id="kitchen_light",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="kitchen",
        )
        entity_registry.async_update_entity(
            "light.kitchen", area_id=area.id,
        )

        result = get_area_entities(hass, area.id)
        assert result.count("light.kitchen") == 1

    async def test_multiple_devices(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Aggregates entities from multiple devices in the area."""
        area = area_registry.async_get_or_create("kitchen")
        dev1 = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "dev1")},
        )
        dev2 = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "dev2")},
        )
        device_registry.async_update_device(dev1.id, area_id=area.id)
        device_registry.async_update_device(dev2.id, area_id=area.id)
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="dev1_temp",
            config_entry=mock_config_entry,
            device_id=dev1.id,
            suggested_object_id="dev1_temp",
        )
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="dev2_humidity",
            config_entry=mock_config_entry,
            device_id=dev2.id,
            suggested_object_id="dev2_humidity",
        )

        result = get_area_entities(hass, area.id)
        assert "sensor.dev1_temp" in result
        assert "sensor.dev2_humidity" in result

    async def test_mixed_direct_and_device_entities(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Returns both direct and device-inherited entities."""
        area = area_registry.async_get_or_create("kitchen")
        device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "dev1")},
        )
        device_registry.async_update_device(device.id, area_id=area.id)
        entity_registry.async_get_or_create(
            domain="light",
            platform="test",
            unique_id="kitchen_light",
            config_entry=mock_config_entry,
            suggested_object_id="kitchen",
        )
        entity_registry.async_update_entity("light.kitchen", area_id=area.id)
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="kitchen_temp",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="kitchen_temp",
        )

        result = get_area_entities(hass, area.id)
        assert sorted(result) == ["light.kitchen", "sensor.kitchen_temp"]


# ---------------------------------------------------------------------------
# TestGetEntityDeviceClass
# ---------------------------------------------------------------------------


class TestGetEntityDeviceClass:
    """Tests for get_entity_device_class."""

    async def test_prefers_state_attribute(
        self,
        hass: HomeAssistant,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Returns device_class from state attributes over registry."""
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="kitchen_occ",
            config_entry=mock_config_entry,
            original_device_class="motion",
            suggested_object_id="kitchen",
        )
        hass.states.async_set(
            "binary_sensor.kitchen", "on", {"device_class": "occupancy"}
        )

        result = get_entity_device_class(hass, "binary_sensor.kitchen")
        assert result == "occupancy"

    async def test_fallback_to_registry_device_class(
        self,
        hass: HomeAssistant,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls back to registry device_class when state has none."""
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="door_1",
            config_entry=mock_config_entry,
            original_device_class="door",
            suggested_object_id="door",
        )
        hass.states.async_set("binary_sensor.door", "on", {})

        result = get_entity_device_class(hass, "binary_sensor.door")
        assert result == "door"

    async def test_fallback_to_original_device_class(
        self,
        hass: HomeAssistant,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls back to original_device_class when device_class is falsy."""
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="motion_1",
            config_entry=mock_config_entry,
            original_device_class="motion",
            suggested_object_id="motion",
        )
        hass.states.async_set("binary_sensor.motion", "on", {})

        result = get_entity_device_class(hass, "binary_sensor.motion")
        assert result == "motion"

    async def test_no_state_returns_registry_class(
        self,
        hass: HomeAssistant,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Returns registry device_class when entity has no state."""
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="humidity_1",
            config_entry=mock_config_entry,
            original_device_class="humidity",
            suggested_object_id="humidity",
        )
        # No state set

        result = get_entity_device_class(hass, "sensor.humidity")
        assert result == "humidity"

    async def test_no_state_no_entry_returns_none(
        self, hass: HomeAssistant,
    ) -> None:
        """Returns None when entity has neither state nor registry entry."""
        result = get_entity_device_class(hass, "binary_sensor.ghost")
        assert result is None

    async def test_state_attribute_error_falls_through_to_registry(
        self,
        hass: HomeAssistant,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls through to registry when state attributes have no device_class."""
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="temp_1",
            config_entry=mock_config_entry,
            original_device_class="temperature",
            suggested_object_id="temp",
        )
        # State with no device_class attribute
        hass.states.async_set("sensor.temp", "22.5", {"unit": "°C"})

        result = get_entity_device_class(hass, "sensor.temp")
        assert result == "temperature"


# ---------------------------------------------------------------------------
# TestDiscoverOccupancySensors
# ---------------------------------------------------------------------------


class TestDiscoverOccupancySensors:
    """Tests for discover_occupancy_sensors."""

    async def test_finds_occupancy_sensor(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Discovers an occupancy sensor in the area."""
        area = area_registry.async_get_or_create("kitchen")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="kitchen_occ",
            config_entry=mock_config_entry,
            suggested_object_id="kitchen_occ",
        )
        entity_registry.async_update_entity(
            "binary_sensor.kitchen_occ", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.kitchen_occ", "off", {"device_class": "occupancy"}
        )

        result = discover_occupancy_sensors(hass, area.id)
        assert result == ["binary_sensor.kitchen_occ"]

    async def test_ignores_non_occupancy_sensor(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Excludes entities that are not occupancy class."""
        area = area_registry.async_get_or_create("kitchen")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="kitchen_door",
            config_entry=mock_config_entry,
            suggested_object_id="kitchen_door",
        )
        entity_registry.async_update_entity(
            "binary_sensor.kitchen_door", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.kitchen_door", "off", {"device_class": "door"}
        )

        result = discover_occupancy_sensors(hass, area.id)
        assert result == []

    async def test_finds_multiple_sensors(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Discovers all occupancy sensors in the area."""
        area = area_registry.async_get_or_create("kitchen")
        for idx in (1, 2):
            entity_registry.async_get_or_create(
                domain="binary_sensor",
                platform="test",
                unique_id=f"occ_{idx}",
                config_entry=mock_config_entry,
                suggested_object_id=f"occ_{idx}",
            )
            entity_registry.async_update_entity(
                f"binary_sensor.occ_{idx}", area_id=area.id,
            )
            hass.states.async_set(
                f"binary_sensor.occ_{idx}", "off", {"device_class": "occupancy"}
            )

        result = discover_occupancy_sensors(hass, area.id)
        assert sorted(result) == ["binary_sensor.occ_1", "binary_sensor.occ_2"]

    async def test_platform_filter_matching(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Includes sensor when platform matches filter."""
        area = area_registry.async_get_or_create("kitchen")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="mqtt",
            unique_id="occ_mqtt",
            config_entry=mock_config_entry,
            suggested_object_id="occ",
        )
        entity_registry.async_update_entity(
            "binary_sensor.occ", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.occ", "off", {"device_class": "occupancy"}
        )

        result = discover_occupancy_sensors(hass, area.id, platform_filter="mqtt")
        assert result == ["binary_sensor.occ"]

    async def test_platform_filter_not_matching(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Excludes sensor when platform doesn't match filter."""
        area = area_registry.async_get_or_create("kitchen")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="zwave",
            unique_id="occ_zwave",
            config_entry=mock_config_entry,
            suggested_object_id="occ",
        )
        entity_registry.async_update_entity(
            "binary_sensor.occ", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.occ", "off", {"device_class": "occupancy"}
        )

        result = discover_occupancy_sensors(hass, area.id, platform_filter="mqtt")
        assert result == []

    async def test_empty_area_returns_empty(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
    ) -> None:
        """Returns empty list for area with no entities."""
        area_registry.async_get_or_create("empty_room")
        result = discover_occupancy_sensors(hass, "empty_room")
        assert result == []


# ---------------------------------------------------------------------------
# TestDiscoverDoorSensors
# ---------------------------------------------------------------------------


class TestDiscoverDoorSensors:
    """Tests for discover_door_sensors."""

    async def test_finds_door_sensor(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Discovers a door sensor in the area."""
        area = area_registry.async_get_or_create("hallway")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="front_door",
            config_entry=mock_config_entry,
            suggested_object_id="front_door",
        )
        entity_registry.async_update_entity(
            "binary_sensor.front_door", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.front_door", "on", {"device_class": "door"}
        )

        result = discover_door_sensors(hass, [area.id])
        assert result == ["binary_sensor.front_door"]

    async def test_multiple_areas(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Discovers door sensors across multiple areas."""
        area1 = area_registry.async_get_or_create("area_1")
        area2 = area_registry.async_get_or_create("area_2")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="door_1",
            config_entry=mock_config_entry,
            suggested_object_id="door_1",
        )
        entity_registry.async_update_entity(
            "binary_sensor.door_1", area_id=area1.id,
        )
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="door_2",
            config_entry=mock_config_entry,
            suggested_object_id="door_2",
        )
        entity_registry.async_update_entity(
            "binary_sensor.door_2", area_id=area2.id,
        )
        hass.states.async_set(
            "binary_sensor.door_1", "on", {"device_class": "door"}
        )
        hass.states.async_set(
            "binary_sensor.door_2", "on", {"device_class": "door"}
        )

        result = discover_door_sensors(hass, [area1.id, area2.id])
        assert sorted(result) == ["binary_sensor.door_1", "binary_sensor.door_2"]

    async def test_ignores_non_door_sensor(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Excludes entities without door device class."""
        area = area_registry.async_get_or_create("hallway")
        entity_registry.async_get_or_create(
            domain="binary_sensor",
            platform="test",
            unique_id="window_1",
            config_entry=mock_config_entry,
            suggested_object_id="window",
        )
        entity_registry.async_update_entity(
            "binary_sensor.window", area_id=area.id,
        )
        hass.states.async_set(
            "binary_sensor.window", "on", {"device_class": "window"}
        )

        result = discover_door_sensors(hass, [area.id])
        assert result == []

    async def test_empty_area_ids(self, hass: HomeAssistant) -> None:
        """Returns empty list when given no area IDs."""
        result = discover_door_sensors(hass, [])
        assert result == []


# ---------------------------------------------------------------------------
# TestGetRoomIdentity
# ---------------------------------------------------------------------------


class TestGetRoomIdentity:
    """Tests for get_room_identity."""

    async def test_non_duplicate_returns_slug_and_area_name(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
    ) -> None:
        """Non-duplicate area returns (slugified area_id, HA area name)."""
        area_registry.async_get_or_create("kitchen")

        slug, name = get_room_identity(hass, _make_room(area="kitchen"), is_duplicate=False)
        assert slug == "kitchen"
        assert name == "kitchen"

    async def test_non_duplicate_area_not_found(
        self, hass: HomeAssistant,
    ) -> None:
        """Uses area_id as display name when area not found in registry."""
        slug, name = get_room_identity(
            hass, _make_room(area="unknown_area"), is_duplicate=False
        )
        assert slug == "unknown_area"
        assert name == "unknown_area"

    async def test_non_duplicate_slugifies_spaces(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
    ) -> None:
        """Slugifies area_id that contains spaces."""
        area_registry.async_get_or_create("Living Room")

        slug, name = get_room_identity(
            hass, _make_room(area="Living Room"), is_duplicate=False
        )
        assert slug == "living_room"
        assert name == "Living Room"

    async def test_duplicate_dict_rooms_int_key_string_value(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Duplicate with dict rooms attr {int: str}."""
        area_registry.async_get_or_create("upstairs")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": {1: "Bedroom", 2: "Bathroom"}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="upstairs", segments=[1]), is_duplicate=True
        )
        assert slug == "upstairs_bedroom"
        assert name == "upstairs Bedroom"

    async def test_duplicate_dict_rooms_string_key(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Duplicate with dict rooms attr where key is string representation of segment."""
        area_registry.async_get_or_create("ground_floor")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": {"5": "Living Room"}},
        )

        slug, name = get_room_identity(
            hass,
            _make_room(area="ground_floor", segments=[5]),
            is_duplicate=True,
        )
        assert slug == "ground_floor_living_room"
        assert name == "ground_floor Living Room"

    async def test_duplicate_dict_rooms_nested_dict_name(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Duplicate with dict rooms attr {int: {'name': str}}."""
        area_registry.async_get_or_create("floor_1")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": {1: {"name": "Kitchen", "id": 1}}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="floor_1", segments=[1]), is_duplicate=True
        )
        assert slug == "floor_1_kitchen"
        assert name == "floor_1 Kitchen"

    async def test_duplicate_dict_rooms_nested_dict_custom_name(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Duplicate with dict rooms attr {int: {'custom_name': str}}."""
        area_registry.async_get_or_create("floor_1")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": {1: {"custom_name": "My Kitchen"}}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="floor_1", segments=[1]), is_duplicate=True
        )
        assert slug == "floor_1_my_kitchen"
        assert name == "floor_1 My Kitchen"

    async def test_duplicate_list_rooms_attr(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Duplicate with list-format rooms attr [{'id': int, 'name': str}]."""
        area_registry.async_get_or_create("house")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Bathroom"}]},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="house", segments=[2]), is_duplicate=True
        )
        assert slug == "house_bathroom"
        assert name == "house Bathroom"

    async def test_duplicate_list_rooms_string_id_match(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """List rooms matches when id is string and segment is int."""
        area_registry.async_get_or_create("house")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"rooms": [{"id": "3", "name": "Study"}]},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="house", segments=[3]), is_duplicate=True
        )
        assert slug == "house_study"
        assert name == "house Study"

    async def test_duplicate_room_list_attr(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Finds room name from 'room_list' attribute when 'rooms' is absent."""
        area_registry.async_get_or_create("home")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"room_list": {1: "Study"}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="home", segments=[1]), is_duplicate=True
        )
        assert slug == "home_study"
        assert name == "home Study"

    async def test_duplicate_regions_attr(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Finds room name from 'regions' attribute."""
        area_registry.async_get_or_create("home")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set(
            "vacuum.robot", "docked",
            {"regions": {1: "Garage"}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="home", segments=[1]), is_duplicate=True
        )
        assert slug == "home_garage"
        assert name == "home Garage"

    async def test_duplicate_room_name_from_sibling_entity(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        device_registry: dr.DeviceRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Finds room name from a sibling entity on the same device."""
        area_registry.async_get_or_create("floor_1")
        device = device_registry.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("test", "device_1")},
        )
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="robot",
        )
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="test",
            unique_id="vacuum_map",
            config_entry=mock_config_entry,
            device_id=device.id,
            suggested_object_id="vacuum_map",
        )
        # Vacuum entity has no rooms attribute
        hass.states.async_set("vacuum.robot", "docked", {})
        # Sibling entity has rooms attribute
        hass.states.async_set(
            "sensor.vacuum_map", "ready",
            {"rooms": {1: "Kitchen"}},
        )

        slug, name = get_room_identity(
            hass, _make_room(area="floor_1", segments=[1]), is_duplicate=True
        )
        assert slug == "floor_1_kitchen"
        assert name == "floor_1 Kitchen"

    async def test_duplicate_fallback_to_segment_suffix(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls back to segment ID suffix when no rooms attribute found."""
        area_registry.async_get_or_create("upstairs")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set("vacuum.robot", "docked", {})

        slug, name = get_room_identity(
            hass, _make_room(area="upstairs", segments=[3, 4]), is_duplicate=True
        )
        assert slug == "upstairs_3_4"
        assert name == "upstairs 3_4"

    async def test_duplicate_no_segments_fallback_unknown(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls back to 'unknown' suffix when duplicate has no segments."""
        area_registry.async_get_or_create("upstairs")

        slug, name = get_room_identity(
            hass, _make_room(area="upstairs", segments=[]), is_duplicate=True
        )
        assert slug == "upstairs_unknown"
        assert name == "upstairs unknown"

    async def test_duplicate_vacuum_state_not_found(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Falls back to segment suffix when vacuum entity has no state."""
        area_registry.async_get_or_create("home")
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        # No state set for vacuum.robot

        slug, name = get_room_identity(
            hass, _make_room(area="home", segments=[7]), is_duplicate=True
        )
        assert slug == "home_7"
        assert name == "home 7"

    async def test_duplicate_no_device_id_skips_siblings(
        self,
        hass: HomeAssistant,
        area_registry: ar.AreaRegistry,
        entity_registry: er.EntityRegistry,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Skips sibling lookup when vacuum has no device_id."""
        area_registry.async_get_or_create("home")
        # Register entity without a device
        entity_registry.async_get_or_create(
            domain="vacuum",
            platform="test",
            unique_id="vac_1",
            config_entry=mock_config_entry,
            suggested_object_id="robot",
        )
        hass.states.async_set("vacuum.robot", "docked", {})

        slug, name = get_room_identity(
            hass, _make_room(area="home", segments=[1]), is_duplicate=True
        )
        # No siblings searched, falls back to segment suffix
        assert slug == "home_1"
