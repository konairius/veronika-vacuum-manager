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

# Link helpers attributes to the module mocks
mock_helpers.device_registry = mock_dr
mock_helpers.entity_registry = mock_er
mock_helpers.area_registry = mock_ar

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

    async def test_reset_all_toggles_success(self):
        """Test that reset_all_toggles runs without NameError or KeyError."""
        # Setup Entity Registry
        self.er_instance.async_get_entity_id.return_value = "switch.veronika_clean_living_room"

        # Initialize Manager
        manager = VeronikaManager(self.hass, self.config)
        
        # Execute
        await manager.reset_all_toggles()
        
        # Verify
        self.assertTrue(self.hass.services.async_call.called)
        call_args = self.hass.services.async_call.call_args
        self.assertEqual(call_args[0][0], "switch")
        self.assertEqual(call_args[0][1], "turn_on")
        self.assertEqual(call_args[0][2]["entity_id"], "switch.veronika_clean_living_room")

    async def test_stop_cleaning(self):
        """Test stop_cleaning sends return_to_base command."""
        # Setup State
        state = MagicMock()
        state.state = "cleaning"
        self.hass.states.get.return_value = state

        manager = VeronikaManager(self.hass, self.config)
        await manager.stop_cleaning()

        # Verify
        self.hass.services.async_call.assert_called_with(
            "vacuum", "return_to_base", {"entity_id": "vacuum.robot"}
        )

    async def test_start_cleaning(self):
        """Test start_cleaning sends the correct vacuum command."""
        # Setup Entity Registry for switches/sensors
        def get_entity_id_side_effect(domain, platform, unique_id):
            if "clean" in unique_id: return "switch.veronika_clean_living_room"
            if "disable" in unique_id: return "switch.veronika_disable_living_room"
            if "status" in unique_id: return "binary_sensor.veronika_status_living_room"
            return None
        self.er_instance.async_get_entity_id.side_effect = get_entity_id_side_effect

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
        # We need to mock the vacuum entity entry to have a device_id
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry
        
        # Mock device to return generic manufacturer
        device_entry = MagicMock()
        device_entry.manufacturer = "Generic"
        self.dr_instance.async_get.return_value = device_entry

        manager = VeronikaManager(self.hass, self.config)
        await manager.start_cleaning()

        # Verify
        # Generic vacuum should call vacuum.start
        self.hass.services.async_call.assert_called_with(
            "vacuum", "start", {"entity_id": "vacuum.robot"}
        )

    async def test_start_cleaning_roborock(self):
        """Test start_cleaning sends the correct vacuum command for Roborock."""
        # Setup Entity Registry for switches/sensors
        def get_entity_id_side_effect(domain, platform, unique_id):
            if "clean" in unique_id: return "switch.veronika_clean_living_room"
            if "disable" in unique_id: return "switch.veronika_disable_living_room"
            if "status" in unique_id: return "binary_sensor.veronika_status_living_room"
            return None
        self.er_instance.async_get_entity_id.side_effect = get_entity_id_side_effect

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
            return state
        self.hass.states.get.side_effect = get_state_side_effect

        # Setup Device Registry for Roborock
        vac_entry = MagicMock()
        vac_entry.device_id = "device_123"
        self.er_instance.async_get.return_value = vac_entry
        
        device_entry = MagicMock()
        device_entry.manufacturer = "Roborock"
        self.dr_instance.async_get.return_value = device_entry

        manager = VeronikaManager(self.hass, self.config)
        await manager.start_cleaning()

        # Verify
        self.hass.services.async_call.assert_called_with(
            "vacuum", "send_command", 
            {
                "entity_id": "vacuum.robot",
                "command": "app_segment_clean",
                "params": [{"segments": [1], "repeat": 1}]
            }
        )

    async def test_handle_segment_completion(self):
        """Test that segment completion turns off the switch."""
        manager = VeronikaManager(self.hass, self.config)
        
        # Manually populate the map since async_setup isn't called in __init__
        manager._vacuum_segment_map = {
            "vacuum.robot": {
                1: ["switch.veronika_clean_living_room"]
            }
        }

        # Execute
        manager._handle_segment_completion("vacuum.robot", 1, 200) # > 180s duration

        # Verify
        # _handle_segment_completion uses hass.async_create_task(hass.services.async_call(...))
        # We need to check if async_create_task was called with a coroutine
        self.assertTrue(self.hass.async_create_task.called)
        
        # To be more thorough, we can manually await the coroutine if we can access it
        coro = self.hass.async_create_task.call_args[0][0]
        await coro
        
        self.hass.services.async_call.assert_called_with(
            "switch", "turn_off", {"entity_id": "switch.veronika_clean_living_room"}
        )

    async def test_get_cleaning_plan_structure(self):
        """Test that get_cleaning_plan returns the correct structure including sensor_entity_id."""
        # Setup Entity Registry
        def get_entity_id_side_effect(domain, platform, unique_id):
            if "clean" in unique_id: return "switch.veronika_clean_living_room"
            if "disable" in unique_id: return "switch.veronika_disable_living_room"
            if "status" in unique_id: return "binary_sensor.veronika_status_living_room"
            return None
        self.er_instance.async_get_entity_id.side_effect = get_entity_id_side_effect

        # Setup States
        self.hass.states.get.return_value = MagicMock(state="on", attributes={})

        manager = VeronikaManager(self.hass, self.config)
        plan = await manager.get_cleaning_plan()
        
        # Verify
        self.assertIn("vacuum.robot", plan)
        room_data = plan["vacuum.robot"]["rooms"][0]
        self.assertIn("sensor_entity_id", room_data)
        self.assertEqual(room_data["sensor_entity_id"], "binary_sensor.veronika_status_living_room")

if __name__ == "__main__":
    unittest.main()
