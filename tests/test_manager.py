"""Tests for the Veronika Vacuum Manager."""
import asyncio

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
    CONF_AREA,
    CONF_ROOMS,
    CONF_SEGMENTS,
    CONF_VACUUM,
    DOMAIN,
)
from custom_components.veronika.manager import VeronikaManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_manager(
    hass: HomeAssistant,
    config: dict,
    *,
    run_setup: bool = True,
) -> VeronikaManager:
    """Create a VeronikaManager and optionally run async_setup."""
    manager = VeronikaManager(hass, config)
    if run_setup:
        await manager.async_setup()
    return manager


def _set_room_states(
    hass: HomeAssistant,
    entity_ids: dict[str, str],
    *,
    clean_on: bool = True,
    disable_on: bool = False,
    sensor_on: bool = True,
    vacuum_state: str = "docked",
) -> None:
    """Set entity states for a single-room test scenario."""
    hass.states.async_set(
        entity_ids["clean"], "on" if clean_on else "off"
    )
    hass.states.async_set(
        entity_ids["disable"], "on" if disable_on else "off"
    )
    hass.states.async_set(
        entity_ids["sensor"], "on" if sensor_on else "off", {"status_reason": "Ready"}
    )
    hass.states.async_set("vacuum.robot", vacuum_state)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_reset_all_toggles_success(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    single_room_config: dict,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test that reset_all_toggles turns on all cleaning switches."""
    calls = async_mock_service(hass, "switch", "turn_on")

    manager = await _create_manager(hass, single_room_config)
    await manager.reset_all_toggles()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == setup_switch_entities["clean"]


async def test_stop_cleaning(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    single_room_config: dict,
    setup_area: ar.AreaEntry,
) -> None:
    """Test stop_cleaning sends return_to_base command."""
    hass.states.async_set("vacuum.robot", "cleaning")
    calls = async_mock_service(hass, "vacuum", "return_to_base")

    manager = await _create_manager(hass, single_room_config, run_setup=False)
    await manager.stop_cleaning()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "vacuum.robot"


async def test_start_cleaning(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    single_room_config: dict,
    mock_config_entry: MockConfigEntry,
    setup_area: ar.AreaEntry,
    setup_vacuum_device: dr.DeviceEntry,
    setup_vacuum_entity: er.RegistryEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test start_cleaning sends the correct vacuum command for a generic vacuum."""
    _set_room_states(hass, setup_switch_entities)
    calls = async_mock_service(hass, "vacuum", "start")

    manager = await _create_manager(hass, single_room_config)
    await manager.start_cleaning()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "vacuum.robot"


async def test_start_cleaning_roborock(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    single_room_config: dict,
    mock_config_entry: MockConfigEntry,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test start_cleaning sends the correct vacuum command for Roborock."""
    # Create Roborock device + entity
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("test_vacuum", "roborock_1")},
        name="Roborock Vacuum",
        manufacturer="Roborock",
    )
    entity_registry.async_get_or_create(
        domain="vacuum",
        platform="test_vacuum",
        unique_id="roborock_1",
        config_entry=mock_config_entry,
        device_id=device.id,
        suggested_object_id="robot",
    )

    _set_room_states(hass, setup_switch_entities)
    calls = async_mock_service(hass, "vacuum", "send_command")

    manager = await _create_manager(hass, single_room_config)
    await manager.start_cleaning()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "vacuum.robot"
    assert calls[0].data["command"] == "app_segment_clean"
    assert calls[0].data["params"] == [{"segments": [1], "repeat": 1}]


async def test_start_cleaning_dreame(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    single_room_config: dict,
    mock_config_entry: MockConfigEntry,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test start_cleaning sends the correct vacuum command for Dreame."""
    device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("test_vacuum", "dreame_1")},
        name="Dreame Vacuum",
        manufacturer="Dreame Technology",
    )
    entity_registry.async_get_or_create(
        domain="vacuum",
        platform="test_vacuum",
        unique_id="dreame_1",
        config_entry=mock_config_entry,
        device_id=device.id,
        suggested_object_id="robot",
    )

    _set_room_states(hass, setup_switch_entities)
    calls = async_mock_service(hass, "dreame_vacuum", "vacuum_clean_segment")

    manager = await _create_manager(hass, single_room_config)
    await manager.start_cleaning()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "vacuum.robot"
    assert calls[0].data["segments"] == [1]


async def test_handle_segment_completion(
    hass: HomeAssistant,
    single_room_config: dict,
) -> None:
    """Test that segment completion turns off the switch."""
    calls = async_mock_service(hass, "switch", "turn_off")

    manager = VeronikaManager(hass, single_room_config)
    manager._vacuum_segment_map = {
        "vacuum.robot": {1: ["switch.veronika_clean_living_room"]}
    }

    await manager._handle_segment_completion("vacuum.robot", 1, 200)

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "switch.veronika_clean_living_room"


async def test_get_cleaning_plan_structure(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    single_room_config: dict,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test that get_cleaning_plan returns the correct structure including sensor_entity_id."""
    hass.states.async_set(setup_switch_entities["clean"], "on")
    hass.states.async_set(setup_switch_entities["disable"], "off")
    hass.states.async_set(setup_switch_entities["sensor"], "on", {"status_reason": "Ready"})
    hass.states.async_set("vacuum.robot", "docked")

    manager = await _create_manager(hass, single_room_config)
    plan = await manager.get_cleaning_plan()

    assert "vacuum.robot" in plan
    room_data = plan["vacuum.robot"]["rooms"][0]
    assert "sensor_entity_id" in room_data
    assert room_data["sensor_entity_id"] == setup_switch_entities["sensor"]


async def test_start_cleaning_concurrent_prevention(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    single_room_config: dict,
    mock_config_entry: MockConfigEntry,
    setup_area: ar.AreaEntry,
    setup_vacuum_device: dr.DeviceEntry,
    setup_vacuum_entity: er.RegistryEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test that concurrent start_cleaning calls are serialized by the lock."""
    _set_room_states(hass, setup_switch_entities)

    call_count = 0

    async def slow_service_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)

    async_mock_service(hass, "vacuum", "start")
    hass.services.async_register("vacuum", "start", slow_service_call)

    manager = await _create_manager(hass, single_room_config)

    task1 = asyncio.create_task(manager.start_cleaning())
    task2 = asyncio.create_task(manager.start_cleaning())
    await asyncio.gather(task1, task2)

    assert call_count == 2


async def test_get_cleaning_plan_with_disabled_rooms(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    single_room_config: dict,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test that rooms with disable switch ON are excluded from cleaning."""
    _set_room_states(hass, setup_switch_entities, disable_on=True)

    manager = await _create_manager(hass, single_room_config)
    plan = await manager.get_cleaning_plan()

    room_data = plan["vacuum.robot"]["rooms"][0]
    assert room_data["will_clean"] is False
    assert room_data["disabled_override"] is True
    assert "Disabled by Override" in room_data["reasons"]
    assert plan["vacuum.robot"]["segments"] == []


async def test_public_accessors(
    hass: HomeAssistant,
    single_room_config: dict,
) -> None:
    """Test that public accessor properties work correctly."""
    manager = VeronikaManager(hass, single_room_config)

    assert manager.last_error is None
    assert manager.error_count == 0

    manager._last_error = "test error"
    manager._error_count = 3
    assert manager.last_error == "test error"
    assert manager.error_count == 3


async def test_get_entity_watch_list(
    hass: HomeAssistant,
    area_registry: ar.AreaRegistry,
    entity_registry: er.EntityRegistry,
    single_room_config: dict,
    setup_area: ar.AreaEntry,
    setup_switch_entities: dict[str, str],
) -> None:
    """Test that get_entity_watch_list returns non-None entity IDs."""
    manager = await _create_manager(hass, single_room_config)
    watch_list = manager.get_entity_watch_list()

    assert setup_switch_entities["clean"] in watch_list
    assert setup_switch_entities["disable"] in watch_list
    assert setup_switch_entities["sensor"] in watch_list
    assert None not in watch_list


async def test_unload_sets_flag(
    hass: HomeAssistant,
    single_room_config: dict,
) -> None:
    """Test that async_unload sets the _is_unloading flag."""
    manager = VeronikaManager(hass, single_room_config)

    assert manager._is_unloading is False
    await manager.async_unload()
    assert manager._is_unloading is True


async def test_handle_segment_completion_skips_when_unloading(
    hass: HomeAssistant,
    single_room_config: dict,
) -> None:
    """Test that _handle_segment_completion is a no-op when unloading."""
    calls = async_mock_service(hass, "switch", "turn_off")

    manager = VeronikaManager(hass, single_room_config)
    manager._vacuum_segment_map = {
        "vacuum.robot": {1: ["switch.veronika_clean_living_room"]}
    }
    manager._is_unloading = True

    await manager._handle_segment_completion("vacuum.robot", 1, 200)

    assert len(calls) == 0
