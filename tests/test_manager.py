import sys
import os
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# --- MOCK SETUP START ---
# We must mock homeassistant modules BEFORE importing the component
mock_ha = MagicMock()
mock_core = MagicMock()
mock_helpers = MagicMock()
mock_dr = MagicMock()
mock_er = MagicMock()
mock_ar = MagicMock()
mock_const = MagicMock()
mock_event = MagicMock()
mock_util = MagicMock()
mock_vol = MagicMock()
mock_discovery = MagicMock()
mock_exceptions = MagicMock()
mock_persistent_notification = MagicMock()
mock_entity_platform = MagicMock()
mock_cv = MagicMock()
mock_http = MagicMock()
mock_sensor = MagicMock()

sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.core"] = mock_core
sys.modules["homeassistant.helpers"] = mock_helpers
sys.modules["homeassistant.helpers.device_registry"] = mock_dr
sys.modules["homeassistant.helpers.entity_registry"] = mock_er
sys.modules["homeassistant.helpers.area_registry"] = mock_ar
sys.modules["homeassistant.const"] = mock_const
sys.modules["homeassistant.helpers.event"] = mock_event
sys.modules["homeassistant.util"] = mock_util
sys.modules["voluptuous"] = mock_vol
sys.modules["homeassistant.helpers.discovery"] = mock_discovery
sys.modules["homeassistant.exceptions"] = mock_exceptions
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.persistent_notification"] = mock_persistent_notification
sys.modules["homeassistant.helpers.entity_platform"] = mock_entity_platform
sys.modules["homeassistant.helpers.config_validation"] = mock_cv
sys.modules["homeassistant.components.http"] = mock_http
sys.modules["homeassistant.components.sensor"] = mock_sensor

# Link helpers attributes to the module mocks
mock_helpers.device_registry = mock_dr
mock_helpers.entity_registry = mock_er
mock_helpers.area_registry = mock_ar

# Setup exception classes that are used in except clauses
class FakeHomeAssistantError(Exception):
    pass

class FakeServiceNotFound(Exception):
    pass

mock_exceptions.HomeAssistantError = FakeHomeAssistantError
mock_exceptions.ServiceNotFound = FakeServiceNotFound

# Setup persistent notification mock
mock_persistent_notification.async_create = AsyncMock()

# Setup common constants and functions
mock_const.STATE_UNAVAILABLE = "unavailable"
mock_const.STATE_UNKNOWN = "unknown"
mock_const.ATTR_ENTITY_ID = "entity_id"
mock_const.SERVICE_TURN_OFF = "turn_off"
mock_const.SERVICE_TURN_ON = "turn_on"

# Mock slugify
def fake_slugify(text):
    if not isinstance(text, str):
        return str(text)
    return text.lower().replace(" ", "_")
mock_util.slugify = fake_slugify

# Mock async_track_state_change_event to return an unsubscribe callable
mock_event.async_track_state_change_event = MagicMock(return_value=MagicMock())

# --- MOCK SETUP END ---

# Add the repository root to sys.path so we can import custom_components
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

# Now import the component
from custom_components.veronika.manager import VeronikaManager
from custom_components.veronika.const import CONF_ROOMS, CONF_AREA, CONF_VACUUM, CONF_SEGMENTS

class TestVeronikaManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.hass.services.async_call = AsyncMock()
        self.hass.async_create_task = MagicMock()

        # Common config
        self.config = {
            CONF_ROOMS: [
                {
                    CONF_AREA: "Living Room",
                    CONF_VACUUM: "vacuum.robot",
                    CONF_SEGMENTS: [1]
                }
            ]
        }

        # Mock Registries
        self.er_instance = MagicMock()
        mock_er.async_get.return_value = self.er_instance

        self.ar_instance = MagicMock()
        mock_ar.async_get.return_value = self.ar_instance

        self.dr_instance = MagicMock()
        mock_dr.async_get.return_value = self.dr_instance

        # Setup Area
        area_entry = MagicMock()
        area_entry.name = "Living Room"
        self.ar_instance.async_get_area.return_value = area_entry

        # Default: vacuum state exists (for async_setup validation)
        self.hass.states.get.return_value = MagicMock(state="docked")

    def _setup_entity_registry(self):
        """Helper to set up entity registry side effects for switch/disable/sensor."""
        def get_entity_id_side_effect(domain, platform, unique_id):
            if "clean" in unique_id: return "switch.veronika_clean_living_room"
            if "disable" in unique_id: return "switch.veronika_disable_living_room"
            if "status" in unique_id: return "binary_sensor.veronika_status_living_room"
            return None
        self.er_instance.async_get_entity_id.side_effect = get_entity_id_side_effect

    async def _create_manager_with_setup(self):
        """Helper to create manager and call async_setup to populate entity cache."""
        manager = VeronikaManager(self.hass, self.config)
        await manager.async_setup()
        return manager

    async def test_reset_all_toggles_success(self):
        """Test that reset_all_toggles turns on all cleaning switches."""
        self._setup_entity_registry()

        manager = await self._create_manager_with_setup()
        await manager.reset_all_toggles()

        # Verify
        self.assertTrue(self.hass.services.async_call.called)
        call_args = self.hass.services.async_call.call_args
        self.assertEqual(call_args[0][0], "switch")
        self.assertEqual(call_args[0][1], "turn_on")
        self.assertEqual(call_args[0][2]["entity_id"], "switch.veronika_clean_living_room")

    async def test_stop_cleaning(self):
        """Test stop_cleaning sends return_to_base command."""
        state = MagicMock()
        state.state = "cleaning"
        self.hass.states.get.return_value = state

        manager = VeronikaManager(self.hass, self.config)
        await manager.stop_cleaning()

        # Verify (includes blocking=True)
        self.hass.services.async_call.assert_called_with(
            "vacuum", "return_to_base", {"entity_id": "vacuum.robot"}, blocking=True
        )

    async def test_start_cleaning(self):
        """Test start_cleaning sends the correct vacuum command."""
        self._setup_entity_registry()

        # Setup States (Enabled, Ready, Not Disabled)
        def get_state_side_effect(entity_id):
            state = MagicMock()
            if entity_id == "switch.veronika_clean_living_room":
                state.state = "on"
            elif entity_id == "switch.veronika_disable_living_room":
                state.state = "off"
            elif entity_id == "binary_sensor.veronika_status_living_room":
                state.state = "on"
                state.attributes = {}
            elif entity_id == "vacuum.robot":
                state.state = "docked"
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        # Setup Device Registry for Manufacturer (Generic)
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry

        device_entry = MagicMock()
        device_entry.manufacturer = "Generic"
        self.dr_instance.async_get.return_value = device_entry

        manager = await self._create_manager_with_setup()
        await manager.start_cleaning()

        # Verify - Generic vacuum should call vacuum.start
        self.hass.services.async_call.assert_called_with(
            "vacuum", "start", {"entity_id": "vacuum.robot"}, blocking=True
        )

    async def test_start_cleaning_roborock(self):
        """Test start_cleaning sends the correct vacuum command for Roborock."""
        self._setup_entity_registry()

        # Setup States
        def get_state_side_effect(entity_id):
            state = MagicMock()
            if entity_id == "switch.veronika_clean_living_room":
                state.state = "on"
            elif entity_id == "switch.veronika_disable_living_room":
                state.state = "off"
            elif entity_id == "binary_sensor.veronika_status_living_room":
                state.state = "on"
                state.attributes = {}
            elif entity_id == "vacuum.robot":
                state.state = "docked"
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        # Setup Device Registry for Roborock
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry

        device_entry = MagicMock()
        device_entry.manufacturer = "Roborock"
        self.dr_instance.async_get.return_value = device_entry

        manager = await self._create_manager_with_setup()
        await manager.start_cleaning()

        # Verify
        self.hass.services.async_call.assert_called_with(
            "vacuum", "send_command",
            {
                "entity_id": "vacuum.robot",
                "command": "app_segment_clean",
                "params": [{"segments": [1], "repeat": 1}]
            },
            blocking=True
        )

    async def test_handle_segment_completion(self):
        """Test that segment completion turns off the switch."""
        manager = VeronikaManager(self.hass, self.config)

        # Manually populate the map since async_setup isn't called
        manager._vacuum_segment_map = {
            "vacuum.robot": {
                1: ["switch.veronika_clean_living_room"]
            }
        }

        # Execute - directly await the async method
        await manager._handle_segment_completion("vacuum.robot", 1, 200)  # > 180s duration

        # Verify the switch was turned off
        self.hass.services.async_call.assert_called_with(
            "switch", "turn_off", {"entity_id": "switch.veronika_clean_living_room"}, blocking=True
        )

    async def test_get_cleaning_plan_structure(self):
        """Test that get_cleaning_plan returns the correct structure including sensor_entity_id."""
        self._setup_entity_registry()

        # Setup States
        self.hass.states.get.return_value = MagicMock(state="on", attributes={})

        manager = await self._create_manager_with_setup()
        plan = await manager.get_cleaning_plan()

        # Verify
        self.assertIn("vacuum.robot", plan)
        room_data = plan["vacuum.robot"]["rooms"][0]
        self.assertIn("sensor_entity_id", room_data)
        self.assertEqual(room_data["sensor_entity_id"], "binary_sensor.veronika_status_living_room")

    async def test_start_cleaning_dreame(self):
        """Test start_cleaning sends the correct vacuum command for Dreame."""
        self._setup_entity_registry()

        # Setup States
        def get_state_side_effect(entity_id):
            state = MagicMock()
            if entity_id == "switch.veronika_clean_living_room":
                state.state = "on"
            elif entity_id == "switch.veronika_disable_living_room":
                state.state = "off"
            elif entity_id == "binary_sensor.veronika_status_living_room":
                state.state = "on"
                state.attributes = {}
            elif entity_id == "vacuum.robot":
                state.state = "docked"
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        # Setup Device Registry for Dreame
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry

        device_entry = MagicMock()
        device_entry.manufacturer = "Dreame Technology"
        self.dr_instance.async_get.return_value = device_entry

        manager = await self._create_manager_with_setup()
        await manager.start_cleaning()

        # Verify Dreame-specific service call
        self.hass.services.async_call.assert_called_with(
            "dreame_vacuum", "vacuum_clean_segment",
            {
                "entity_id": "vacuum.robot",
                "segments": [1]
            },
            blocking=True
        )

    async def test_start_cleaning_concurrent_prevention(self):
        """Test that concurrent start_cleaning calls are serialized by the lock."""
        import asyncio

        self._setup_entity_registry()

        # Setup States
        def get_state_side_effect(entity_id):
            state = MagicMock()
            if entity_id == "switch.veronika_clean_living_room":
                state.state = "on"
            elif entity_id == "switch.veronika_disable_living_room":
                state.state = "off"
            elif entity_id == "binary_sensor.veronika_status_living_room":
                state.state = "on"
                state.attributes = {}
            elif entity_id == "vacuum.robot":
                state.state = "docked"
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        # Setup Device Registry
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry

        device_entry = MagicMock()
        device_entry.manufacturer = "Generic"
        self.dr_instance.async_get.return_value = device_entry

        manager = await self._create_manager_with_setup()

        # Track call count with a slow service call
        call_count = 0
        async def slow_service_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
        self.hass.services.async_call.side_effect = slow_service_call

        # Launch two concurrent cleaning calls
        task1 = asyncio.create_task(manager.start_cleaning())
        task2 = asyncio.create_task(manager.start_cleaning())
        await asyncio.gather(task1, task2)

        # Both should complete (serialized by lock), service called twice
        self.assertEqual(call_count, 2)

    async def test_get_cleaning_plan_with_disabled_rooms(self):
        """Test that rooms with disable switch ON are excluded from cleaning."""
        self._setup_entity_registry()

        # Setup States - switch on, sensor ready, but disable switch is ON
        def get_state_side_effect(entity_id):
            state = MagicMock()
            if entity_id == "switch.veronika_clean_living_room":
                state.state = "on"
            elif entity_id == "switch.veronika_disable_living_room":
                state.state = "on"  # Disabled!
            elif entity_id == "binary_sensor.veronika_status_living_room":
                state.state = "on"
                state.attributes = {}
            else:
                state.state = "docked"
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        manager = await self._create_manager_with_setup()
        plan = await manager.get_cleaning_plan()

        # Verify the room is not scheduled for cleaning
        room_data = plan["vacuum.robot"]["rooms"][0]
        self.assertFalse(room_data["will_clean"])
        self.assertTrue(room_data["disabled_override"])
        self.assertIn("Disabled by Override", room_data["reasons"])
        # Segments should be empty since the room is disabled
        self.assertEqual(plan["vacuum.robot"]["segments"], [])

    async def test_public_accessors(self):
        """Test that public accessor properties work correctly."""
        manager = VeronikaManager(self.hass, self.config)

        # Initially no errors
        self.assertIsNone(manager.last_error)
        self.assertEqual(manager.error_count, 0)

        # Simulate error state
        manager._last_error = "test error"
        manager._error_count = 3
        self.assertEqual(manager.last_error, "test error")
        self.assertEqual(manager.error_count, 3)

    async def test_get_entity_watch_list(self):
        """Test that get_entity_watch_list returns non-None entity IDs."""
        self._setup_entity_registry()

        manager = await self._create_manager_with_setup()
        watch_list = manager.get_entity_watch_list()

        self.assertIn("switch.veronika_clean_living_room", watch_list)
        self.assertIn("switch.veronika_disable_living_room", watch_list)
        self.assertIn("binary_sensor.veronika_status_living_room", watch_list)
        self.assertNotIn(None, watch_list)

    async def test_unload_sets_flag(self):
        """Test that async_unload sets the _is_unloading flag."""
        manager = VeronikaManager(self.hass, self.config)

        self.assertFalse(manager._is_unloading)
        await manager.async_unload()
        self.assertTrue(manager._is_unloading)

    async def test_handle_segment_completion_skips_when_unloading(self):
        """Test that _handle_segment_completion is a no-op when unloading."""
        manager = VeronikaManager(self.hass, self.config)
        manager._vacuum_segment_map = {
            "vacuum.robot": {1: ["switch.veronika_clean_living_room"]}
        }
        manager._is_unloading = True

        await manager._handle_segment_completion("vacuum.robot", 1, 200)

        # Should NOT have called any service
        self.hass.services.async_call.assert_not_called()

if __name__ == "__main__":
    unittest.main()
