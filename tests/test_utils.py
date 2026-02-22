import sys
import os
import unittest
from unittest.mock import MagicMock

# --- MOCK SETUP ---
# Ensure all homeassistant modules are mocked before importing the component.
# If test_manager.py already ran, we reuse its mocks; otherwise we create fresh ones.
_HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.area_registry",
    "homeassistant.const",
    "homeassistant.helpers.event",
    "homeassistant.util",
    "voluptuous",
    "homeassistant.helpers.discovery",
    "homeassistant.exceptions",
    "homeassistant.components",
    "homeassistant.components.persistent_notification",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.config_validation",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
]

for mod in _HA_MODULES:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Get references to the mocks that utils.py will actually use
mock_er = sys.modules["homeassistant.helpers.entity_registry"]
mock_dr = sys.modules["homeassistant.helpers.device_registry"]
mock_ar = sys.modules["homeassistant.helpers.area_registry"]
mock_util = sys.modules["homeassistant.util"]
mock_helpers = sys.modules["homeassistant.helpers"]

# Ensure helpers attributes point to the right mocks
mock_helpers.device_registry = mock_dr
mock_helpers.entity_registry = mock_er
mock_helpers.area_registry = mock_ar

# Provide a working slugify
def fake_slugify(text):
    if not isinstance(text, str):
        return str(text)
    return text.lower().replace(" ", "_")

mock_util.slugify = fake_slugify

# --- END MOCK SETUP ---

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from custom_components.veronika.utils import (
    get_area_entities,
    get_entity_device_class,
    discover_occupancy_sensors,
    discover_door_sensors,
    get_room_identity,
)
from custom_components.veronika.const import CONF_AREA, CONF_VACUUM, CONF_SEGMENTS


class TestGetAreaEntities(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.er_instance = MagicMock()
        self.dr_instance = MagicMock()
        mock_er.async_get.return_value = self.er_instance
        mock_er.async_get.side_effect = None
        mock_dr.async_get.return_value = self.dr_instance
        mock_dr.async_get.side_effect = None
        mock_er.async_entries_for_area.return_value = []
        mock_er.async_entries_for_area.side_effect = None
        mock_dr.async_entries_for_area.return_value = []
        mock_dr.async_entries_for_area.side_effect = None
        mock_er.async_entries_for_device.return_value = []
        mock_er.async_entries_for_device.side_effect = None

    def test_empty_area(self):
        """Area with no entities and no devices returns empty list."""
        result = get_area_entities(self.hass, "kitchen")
        self.assertEqual(result, [])

    def test_direct_entities_only(self):
        """Returns entities directly assigned to the area."""
        entry1 = MagicMock(entity_id="light.kitchen_main")
        entry2 = MagicMock(entity_id="sensor.kitchen_temp")
        mock_er.async_entries_for_area.return_value = [entry1, entry2]

        result = get_area_entities(self.hass, "kitchen")
        self.assertCountEqual(result, ["light.kitchen_main", "sensor.kitchen_temp"])

    def test_device_entities_with_no_area(self):
        """Includes device entities where area_id is None (inheriting from device)."""
        device = MagicMock(id="device_1")
        mock_dr.async_entries_for_area.return_value = [device]

        entity = MagicMock(entity_id="sensor.device_sensor", area_id=None)
        mock_er.async_entries_for_device.return_value = [entity]

        result = get_area_entities(self.hass, "kitchen")
        self.assertIn("sensor.device_sensor", result)

    def test_device_entities_with_own_area_excluded(self):
        """Excludes device entities that have their own area_id set."""
        device = MagicMock(id="device_1")
        mock_dr.async_entries_for_area.return_value = [device]

        entity = MagicMock(entity_id="sensor.device_sensor", area_id="living_room")
        mock_er.async_entries_for_device.return_value = [entity]

        result = get_area_entities(self.hass, "kitchen")
        self.assertNotIn("sensor.device_sensor", result)

    def test_deduplication(self):
        """Same entity from direct and device lookup appears only once."""
        direct_entry = MagicMock(entity_id="light.kitchen")
        mock_er.async_entries_for_area.return_value = [direct_entry]

        device = MagicMock(id="device_1")
        mock_dr.async_entries_for_area.return_value = [device]

        device_entry = MagicMock(entity_id="light.kitchen", area_id=None)
        mock_er.async_entries_for_device.return_value = [device_entry]

        result = get_area_entities(self.hass, "kitchen")
        self.assertEqual(result.count("light.kitchen"), 1)

    def test_multiple_devices(self):
        """Aggregates entities from multiple devices in the area."""
        device1 = MagicMock(id="dev1")
        device2 = MagicMock(id="dev2")
        mock_dr.async_entries_for_area.return_value = [device1, device2]

        entry1 = MagicMock(entity_id="sensor.dev1_temp", area_id=None)
        entry2 = MagicMock(entity_id="sensor.dev2_humidity", area_id=None)
        mock_er.async_entries_for_device.side_effect = lambda reg, dev_id: (
            [entry1] if dev_id == "dev1" else [entry2]
        )

        result = get_area_entities(self.hass, "kitchen")
        self.assertIn("sensor.dev1_temp", result)
        self.assertIn("sensor.dev2_humidity", result)

    def test_mixed_direct_and_device_entities(self):
        """Returns both direct and device-inherited entities."""
        direct = MagicMock(entity_id="light.kitchen")
        mock_er.async_entries_for_area.return_value = [direct]

        device = MagicMock(id="dev1")
        mock_dr.async_entries_for_area.return_value = [device]

        device_entity = MagicMock(entity_id="sensor.kitchen_temp", area_id=None)
        mock_er.async_entries_for_device.return_value = [device_entity]

        result = get_area_entities(self.hass, "kitchen")
        self.assertCountEqual(result, ["light.kitchen", "sensor.kitchen_temp"])


class TestGetEntityDeviceClass(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.er_instance = MagicMock()
        mock_er.async_get.return_value = self.er_instance
        mock_er.async_get.side_effect = None

    def test_prefers_state_attribute(self):
        """Returns device_class from state attributes over registry."""
        state = MagicMock()
        state.attributes = {"device_class": "occupancy"}
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(
            device_class="motion", original_device_class=None
        )

        result = get_entity_device_class(self.hass, "binary_sensor.kitchen")
        self.assertEqual(result, "occupancy")

    def test_fallback_to_registry_device_class(self):
        """Falls back to registry device_class when state has none."""
        state = MagicMock()
        state.attributes = {}
        self.hass.states.get.return_value = state

        entry = MagicMock(device_class="door", original_device_class="window")
        self.er_instance.async_get.return_value = entry

        result = get_entity_device_class(self.hass, "binary_sensor.door")
        self.assertEqual(result, "door")

    def test_fallback_to_original_device_class(self):
        """Falls back to original_device_class when device_class is falsy."""
        state = MagicMock()
        state.attributes = {}
        self.hass.states.get.return_value = state

        entry = MagicMock()
        entry.device_class = None
        entry.original_device_class = "motion"
        self.er_instance.async_get.return_value = entry

        result = get_entity_device_class(self.hass, "binary_sensor.motion")
        self.assertEqual(result, "motion")

    def test_no_state_returns_registry_class(self):
        """Returns registry device_class when entity has no state."""
        self.hass.states.get.return_value = None

        entry = MagicMock(device_class="humidity", original_device_class=None)
        self.er_instance.async_get.return_value = entry

        result = get_entity_device_class(self.hass, "sensor.humidity")
        self.assertEqual(result, "humidity")

    def test_no_state_no_entry_returns_none(self):
        """Returns None when entity has neither state nor registry entry."""
        self.hass.states.get.return_value = None
        self.er_instance.async_get.return_value = None

        result = get_entity_device_class(self.hass, "binary_sensor.ghost")
        self.assertIsNone(result)

    def test_registry_access_exception_returns_none(self):
        """Returns None when registry access throws."""
        mock_er.async_get.side_effect = RuntimeError("Registry unavailable")

        result = get_entity_device_class(self.hass, "binary_sensor.broken")
        self.assertIsNone(result)

    def test_state_attribute_error_falls_through_to_registry(self):
        """Falls through to registry when state.attributes.get raises."""
        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = AttributeError("no attributes")
        self.hass.states.get.return_value = state

        entry = MagicMock(device_class="temperature", original_device_class=None)
        self.er_instance.async_get.return_value = entry

        result = get_entity_device_class(self.hass, "sensor.temp")
        self.assertEqual(result, "temperature")


class TestDiscoverOccupancySensors(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.er_instance = MagicMock()
        self.dr_instance = MagicMock()
        mock_er.async_get.return_value = self.er_instance
        mock_er.async_get.side_effect = None
        mock_dr.async_get.return_value = self.dr_instance
        mock_dr.async_get.side_effect = None
        mock_er.async_entries_for_area.return_value = []
        mock_er.async_entries_for_area.side_effect = None
        mock_dr.async_entries_for_area.return_value = []
        mock_dr.async_entries_for_area.side_effect = None
        mock_er.async_entries_for_device.return_value = []
        mock_er.async_entries_for_device.side_effect = None

    def _add_area_entity(self, entity_id, device_class, platform="default"):
        """Register an entity in the area with the given device class and platform."""
        area_entry = MagicMock(entity_id=entity_id)
        current = list(mock_er.async_entries_for_area.return_value)
        current.append(area_entry)
        mock_er.async_entries_for_area.return_value = current

        reg_entry = MagicMock(platform=platform)
        state = MagicMock()
        state.attributes = {"device_class": device_class}

        # Wire up per-entity lookups
        existing_er_get = self.er_instance.async_get.side_effect
        existing_states_get = self.hass.states.get.side_effect
        er_map = getattr(self, "_er_map", {})
        state_map = getattr(self, "_state_map", {})
        er_map[entity_id] = reg_entry
        state_map[entity_id] = state
        self._er_map = er_map
        self._state_map = state_map
        self.er_instance.async_get.side_effect = lambda eid: self._er_map.get(eid, MagicMock(platform="other"))
        self.hass.states.get.side_effect = lambda eid: self._state_map.get(eid, MagicMock(attributes={}))

    def test_finds_occupancy_sensor(self):
        """Discovers an occupancy sensor in the area."""
        self._add_area_entity("binary_sensor.kitchen_occ", "occupancy")

        result = discover_occupancy_sensors(self.hass, "kitchen")
        self.assertEqual(result, ["binary_sensor.kitchen_occ"])

    def test_ignores_non_occupancy_sensor(self):
        """Excludes entities that are not occupancy class."""
        self._add_area_entity("binary_sensor.kitchen_door", "door")

        result = discover_occupancy_sensors(self.hass, "kitchen")
        self.assertEqual(result, [])

    def test_finds_multiple_sensors(self):
        """Discovers all occupancy sensors in the area."""
        self._add_area_entity("binary_sensor.occ_1", "occupancy")
        self._add_area_entity("binary_sensor.occ_2", "occupancy")

        result = discover_occupancy_sensors(self.hass, "kitchen")
        self.assertCountEqual(result, ["binary_sensor.occ_1", "binary_sensor.occ_2"])

    def test_platform_filter_matching(self):
        """Includes sensor when platform matches filter."""
        self._add_area_entity("binary_sensor.occ", "occupancy", platform="mqtt")

        result = discover_occupancy_sensors(self.hass, "kitchen", platform_filter="mqtt")
        self.assertEqual(result, ["binary_sensor.occ"])

    def test_platform_filter_not_matching(self):
        """Excludes sensor when platform doesn't match filter."""
        self._add_area_entity("binary_sensor.occ", "occupancy", platform="zwave")

        result = discover_occupancy_sensors(self.hass, "kitchen", platform_filter="mqtt")
        self.assertEqual(result, [])

    def test_platform_filter_no_registry_entry(self):
        """Excludes entity when platform filter is set but registry entry is None."""
        area_entry = MagicMock(entity_id="binary_sensor.occ")
        mock_er.async_entries_for_area.return_value = [area_entry]

        self.er_instance.async_get.return_value = None
        state = MagicMock()
        state.attributes = {"device_class": "occupancy"}
        self.hass.states.get.return_value = state

        result = discover_occupancy_sensors(self.hass, "kitchen", platform_filter="mqtt")
        self.assertEqual(result, [])

    def test_empty_area_returns_empty(self):
        """Returns empty list for area with no entities."""
        result = discover_occupancy_sensors(self.hass, "empty_room")
        self.assertEqual(result, [])

    def test_registry_exception_returns_empty(self):
        """Returns empty list when entity registry access fails."""
        mock_er.async_get.side_effect = RuntimeError("Registry broken")

        result = discover_occupancy_sensors(self.hass, "broken_area")
        self.assertEqual(result, [])


class TestDiscoverDoorSensors(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.er_instance = MagicMock()
        self.dr_instance = MagicMock()
        mock_er.async_get.return_value = self.er_instance
        mock_er.async_get.side_effect = None
        mock_dr.async_get.return_value = self.dr_instance
        mock_dr.async_get.side_effect = None
        mock_er.async_entries_for_area.return_value = []
        mock_er.async_entries_for_area.side_effect = None
        mock_dr.async_entries_for_area.return_value = []
        mock_dr.async_entries_for_area.side_effect = None
        mock_er.async_entries_for_device.return_value = []
        mock_er.async_entries_for_device.side_effect = None

    def test_finds_door_sensor(self):
        """Discovers a door sensor in the area."""
        entry = MagicMock(entity_id="binary_sensor.front_door")
        mock_er.async_entries_for_area.return_value = [entry]

        state = MagicMock()
        state.attributes = {"device_class": "door"}
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_class="door")

        result = discover_door_sensors(self.hass, ["hallway"])
        self.assertEqual(result, ["binary_sensor.front_door"])

    def test_multiple_areas(self):
        """Discovers door sensors across multiple areas."""
        entry1 = MagicMock(entity_id="binary_sensor.door_1")
        entry2 = MagicMock(entity_id="binary_sensor.door_2")

        mock_er.async_entries_for_area.side_effect = lambda reg, aid: (
            [entry1] if aid == "area_1" else [entry2]
        )

        state = MagicMock()
        state.attributes = {"device_class": "door"}
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_class="door")

        result = discover_door_sensors(self.hass, ["area_1", "area_2"])
        self.assertCountEqual(result, ["binary_sensor.door_1", "binary_sensor.door_2"])

    def test_ignores_non_door_sensor(self):
        """Excludes entities without door device class."""
        entry = MagicMock(entity_id="binary_sensor.window")
        mock_er.async_entries_for_area.return_value = [entry]

        state = MagicMock()
        state.attributes = {"device_class": "window"}
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_class="window")

        result = discover_door_sensors(self.hass, ["hallway"])
        self.assertEqual(result, [])

    def test_empty_area_ids(self):
        """Returns empty list when given no area IDs."""
        result = discover_door_sensors(self.hass, [])
        self.assertEqual(result, [])

    def test_exception_in_area_continues_to_next(self):
        """Continues to next area when one throws an exception."""
        good_entry = MagicMock(entity_id="binary_sensor.door")

        mock_er.async_entries_for_area.side_effect = lambda reg, aid: (
            (_ for _ in ()).throw(RuntimeError("Bad area"))
            if aid == "bad_area"
            else [good_entry]
        )

        state = MagicMock()
        state.attributes = {"device_class": "door"}
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_class="door")

        result = discover_door_sensors(self.hass, ["bad_area", "good_area"])
        self.assertEqual(result, ["binary_sensor.door"])

    def test_exception_checking_entity_continues(self):
        """Continues to next entity when device class check throws."""
        entry1 = MagicMock(entity_id="binary_sensor.broken")
        entry2 = MagicMock(entity_id="binary_sensor.good_door")
        mock_er.async_entries_for_area.return_value = [entry1, entry2]

        call_count = [0]
        def state_side_effect(entity_id):
            call_count[0] += 1
            if entity_id == "binary_sensor.broken":
                raise RuntimeError("State broken")
            state = MagicMock()
            state.attributes = {"device_class": "door"}
            return state
        self.hass.states.get.side_effect = state_side_effect

        # get_entity_device_class will catch the exception from hass.states.get
        # for the broken entity (via the try/except in get_entity_device_class),
        # returning None. The outer try/except in discover_door_sensors handles
        # any remaining exceptions.
        self.er_instance.async_get.return_value = MagicMock(device_class="door")

        result = discover_door_sensors(self.hass, ["hallway"])
        # The broken entity returns None from get_entity_device_class (exception caught),
        # so only the good door is included
        self.assertIn("binary_sensor.good_door", result)


class TestGetRoomIdentity(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.ar_instance = MagicMock()
        self.er_instance = MagicMock()
        mock_ar.async_get.return_value = self.ar_instance
        mock_ar.async_get.side_effect = None
        mock_er.async_get.return_value = self.er_instance
        mock_er.async_get.side_effect = None
        mock_er.async_entries_for_device.return_value = []
        mock_er.async_entries_for_device.side_effect = None

    def _make_room(self, area="kitchen", vacuum="vacuum.robot", segments=None):
        room = {CONF_AREA: area, CONF_VACUUM: vacuum}
        if segments is not None:
            room[CONF_SEGMENTS] = segments
        else:
            room[CONF_SEGMENTS] = [1]
        return room

    # --- Non-duplicate cases ---

    def test_non_duplicate_returns_slug_and_area_name(self):
        """Non-duplicate area returns (slugified area_id, HA area name)."""
        area_entry = MagicMock()
        area_entry.name = "Kitchen"
        self.ar_instance.async_get_area.return_value = area_entry

        slug, name = get_room_identity(self.hass, self._make_room(area="kitchen"), is_duplicate=False)
        self.assertEqual(slug, "kitchen")
        self.assertEqual(name, "Kitchen")

    def test_non_duplicate_area_not_found(self):
        """Uses area_id as display name when area not found in registry."""
        self.ar_instance.async_get_area.return_value = None

        slug, name = get_room_identity(self.hass, self._make_room(area="unknown_area"), is_duplicate=False)
        self.assertEqual(slug, "unknown_area")
        self.assertEqual(name, "unknown_area")

    def test_non_duplicate_area_registry_exception(self):
        """Falls back to area_id when area registry throws."""
        mock_ar.async_get.side_effect = RuntimeError("Registry broken")

        slug, name = get_room_identity(self.hass, self._make_room(area="broken"), is_duplicate=False)
        self.assertEqual(slug, "broken")
        self.assertEqual(name, "broken")

    def test_non_duplicate_slugifies_spaces(self):
        """Slugifies area_id that contains spaces."""
        area_entry = MagicMock()
        area_entry.name = "Living Room"
        self.ar_instance.async_get_area.return_value = area_entry

        slug, name = get_room_identity(self.hass, self._make_room(area="Living Room"), is_duplicate=False)
        self.assertEqual(slug, "living_room")
        self.assertEqual(name, "Living Room")

    # --- Duplicate: dict rooms attribute with int key ---

    def test_duplicate_dict_rooms_int_key_string_value(self):
        """Duplicate with dict rooms attr {int: str}."""
        area_entry = MagicMock()
        area_entry.name = "Upstairs"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {1: "Bedroom", 2: "Bathroom"} if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="upstairs", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "upstairs_bedroom")
        self.assertEqual(name, "Upstairs Bedroom")

    def test_duplicate_dict_rooms_string_key(self):
        """Duplicate with dict rooms attr where key is string representation of segment."""
        area_entry = MagicMock()
        area_entry.name = "Ground Floor"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {"5": "Living Room"} if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="ground_floor", segments=[5]), is_duplicate=True)
        self.assertEqual(slug, "ground_floor_living_room")
        self.assertEqual(name, "Ground Floor Living Room")

    # --- Duplicate: dict rooms with nested dict ---

    def test_duplicate_dict_rooms_nested_dict_name(self):
        """Duplicate with dict rooms attr {int: {'name': str}}."""
        area_entry = MagicMock()
        area_entry.name = "Floor 1"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {1: {"name": "Kitchen", "id": 1}} if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="floor_1", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "floor_1_kitchen")
        self.assertEqual(name, "Floor 1 Kitchen")

    def test_duplicate_dict_rooms_nested_dict_custom_name(self):
        """Duplicate with dict rooms attr {int: {'custom_name': str}}."""
        area_entry = MagicMock()
        area_entry.name = "Floor 1"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {1: {"custom_name": "My Kitchen"}} if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="floor_1", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "floor_1_my_kitchen")
        self.assertEqual(name, "Floor 1 My Kitchen")

    # --- Duplicate: list rooms attribute ---

    def test_duplicate_list_rooms_attr(self):
        """Duplicate with list-format rooms attr [{'id': int, 'name': str}]."""
        area_entry = MagicMock()
        area_entry.name = "House"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        rooms_list = [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Bathroom"}]
        state.attributes.get.side_effect = lambda attr: rooms_list if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="house", segments=[2]), is_duplicate=True)
        self.assertEqual(slug, "house_bathroom")
        self.assertEqual(name, "House Bathroom")

    def test_duplicate_list_rooms_string_id_match(self):
        """List rooms matches when id is string and segment is int."""
        area_entry = MagicMock()
        area_entry.name = "House"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        rooms_list = [{"id": "3", "name": "Study"}]
        state.attributes.get.side_effect = lambda attr: rooms_list if attr == "rooms" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="house", segments=[3]), is_duplicate=True)
        self.assertEqual(slug, "house_study")
        self.assertEqual(name, "House Study")

    # --- Duplicate: alternative attribute names ---

    def test_duplicate_room_list_attr(self):
        """Finds room name from 'room_list' attribute when 'rooms' is absent."""
        area_entry = MagicMock()
        area_entry.name = "Home"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {1: "Study"} if attr == "room_list" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="home", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "home_study")
        self.assertEqual(name, "Home Study")

    def test_duplicate_regions_attr(self):
        """Finds room name from 'regions' attribute."""
        area_entry = MagicMock()
        area_entry.name = "Home"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.side_effect = lambda attr: {1: "Garage"} if attr == "regions" else None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="home", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "home_garage")
        self.assertEqual(name, "Home Garage")

    # --- Duplicate: sibling entity lookup ---

    def test_duplicate_room_name_from_sibling_entity(self):
        """Finds room name from a sibling entity on the same device."""
        area_entry = MagicMock()
        area_entry.name = "Floor 1"
        self.ar_instance.async_get_area.return_value = area_entry

        # Vacuum entity has no rooms attribute
        vac_state = MagicMock()
        vac_state.attributes = MagicMock()
        vac_state.attributes.get.return_value = None

        # Sibling entity has rooms attribute
        sibling_state = MagicMock()
        sibling_state.attributes = MagicMock()
        sibling_state.attributes.get.side_effect = lambda attr: {1: "Kitchen"} if attr == "rooms" else None

        self.hass.states.get.side_effect = lambda eid: (
            vac_state if eid == "vacuum.robot" else sibling_state
        )

        vac_entry = MagicMock(device_id="device_1")
        self.er_instance.async_get.return_value = vac_entry

        sibling = MagicMock(entity_id="sensor.vacuum_map")
        mock_er.async_entries_for_device.return_value = [sibling]

        slug, name = get_room_identity(self.hass, self._make_room(area="floor_1", segments=[1]), is_duplicate=True)
        self.assertEqual(slug, "floor_1_kitchen")
        self.assertEqual(name, "Floor 1 Kitchen")

    # --- Duplicate: fallback cases ---

    def test_duplicate_fallback_to_segment_suffix(self):
        """Falls back to segment ID suffix when no rooms attribute found."""
        area_entry = MagicMock()
        area_entry.name = "Upstairs"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.return_value = None
        self.hass.states.get.return_value = state
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="upstairs", segments=[3, 4]), is_duplicate=True)
        self.assertEqual(slug, "upstairs_3_4")
        self.assertEqual(name, "Upstairs 3_4")

    def test_duplicate_no_segments_fallback_unknown(self):
        """Falls back to 'unknown' suffix when duplicate has no segments."""
        area_entry = MagicMock()
        area_entry.name = "Upstairs"
        self.ar_instance.async_get_area.return_value = area_entry

        self.hass.states.get.return_value = None
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="upstairs", segments=[]), is_duplicate=True)
        self.assertEqual(slug, "upstairs_unknown")
        self.assertEqual(name, "Upstairs unknown")

    def test_duplicate_vacuum_state_not_found(self):
        """Falls back to segment suffix when vacuum entity has no state."""
        area_entry = MagicMock()
        area_entry.name = "Home"
        self.ar_instance.async_get_area.return_value = area_entry

        self.hass.states.get.return_value = None
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        slug, name = get_room_identity(self.hass, self._make_room(area="home", segments=[7]), is_duplicate=True)
        self.assertEqual(slug, "home_7")
        self.assertEqual(name, "Home 7")

    def test_duplicate_no_device_id_skips_siblings(self):
        """Skips sibling lookup when vacuum has no device_id."""
        area_entry = MagicMock()
        area_entry.name = "Home"
        self.ar_instance.async_get_area.return_value = area_entry

        state = MagicMock()
        state.attributes = MagicMock()
        state.attributes.get.return_value = None
        self.hass.states.get.return_value = state

        # Vacuum entry exists but has no device_id
        self.er_instance.async_get.return_value = MagicMock(device_id=None)

        # Reset call count before our test (shared module-level mock)
        mock_er.async_entries_for_device.reset_mock()

        slug, name = get_room_identity(self.hass, self._make_room(area="home", segments=[1]), is_duplicate=True)
        # No siblings searched, falls back to segment suffix
        self.assertEqual(slug, "home_1")
        mock_er.async_entries_for_device.assert_not_called()


if __name__ == "__main__":
    unittest.main()
