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
    async def test_reset_all_toggles_success(self):
        """
        Test that reset_all_toggles runs without NameError or KeyError.
        This test specifically targets the bug where CONF_NAME was used instead of CONF_AREA.
        """
        # Setup
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        
        # Configure a sample room
        config = {
            CONF_ROOMS: [
                {
                    CONF_AREA: "Living Room",
                    CONF_VACUUM: "vacuum.robot",
                    CONF_SEGMENTS: [1]
                }
            ]
        }
        
        # Mock Entity Registry to return a switch ID
        er_instance = MagicMock()
        # When asking for the switch, return None first to trigger the fallback logic, 
        # or return a string to test the primary logic.
        er_instance.async_get_entity_id.return_value = "switch.veronika_clean_living_room"
        mock_er.async_get.return_value = er_instance
        
        # Mock Area Registry (needed by utils.get_room_identity)
        ar_instance = MagicMock()
        area_entry = MagicMock()
        area_entry.name = "Living Room"
        ar_instance.async_get_area.return_value = area_entry
        mock_ar.async_get.return_value = ar_instance

        # Initialize Manager
        manager = VeronikaManager(hass, config)
        
        # Execute
        try:
            await manager.reset_all_toggles()
        except NameError as e:
            self.fail(f"Caught NameError: {e} - This indicates the variable is not defined.")
        except Exception as e:
            self.fail(f"Caught unexpected exception: {e}")
        
        # Verify service call
        # We expect a call to turn_on the switch
        self.assertTrue(hass.services.async_call.called)
        call_args = hass.services.async_call.call_args
        
        # Check arguments: domain, service, data
        self.assertEqual(call_args[0][0], "switch")
        self.assertEqual(call_args[0][1], "turn_on")
        self.assertIn("entity_id", call_args[0][2])
        self.assertEqual(call_args[0][2]["entity_id"], "switch.veronika_clean_living_room")

if __name__ == "__main__":
    unittest.main()
