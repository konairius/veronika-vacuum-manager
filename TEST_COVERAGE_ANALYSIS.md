# Test Coverage Analysis

## Current State

The test suite consists of **1 test file** (`tests/test_manager.py`) with **13 test methods**, all targeting `VeronikaManager`. The tests run via `unittest.IsolatedAsyncioTestCase` with extensive Home Assistant mocking.

### What's Covered (manager.py only)

| Method | Covered? | Notes |
|--------|----------|-------|
| `reset_all_toggles()` | Partial | Happy path only |
| `stop_cleaning()` | Partial | Only tests cleaning state; no error paths |
| `start_cleaning()` | Partial | Generic, Roborock, Dreame brands; concurrent lock |
| `_handle_segment_completion()` | Partial | Success path + unloading guard; no retry/error paths |
| `get_cleaning_plan()` | Partial | Structure + disabled rooms; missing many branches |
| `get_entity_watch_list()` | Yes | |
| `async_unload()` | Partial | Only checks `_is_unloading` flag; no cleanup verification |
| `last_error` / `error_count` | Yes | |

### What's NOT Covered At All

| Module | Lines | Tests |
|--------|-------|-------|
| `__init__.py` | 177 | **0 tests** |
| `utils.py` | 216 | **0 tests** |
| `binary_sensor.py` | 301 | **0 tests** |
| `switch.py` | 85 | **0 tests** |
| `sensor.py` | 104 | **0 tests** |

**4 out of 6 Python modules (706 of ~1555 lines, ~45%) have zero test coverage.**

---

## Gap Analysis & Recommendations

### Priority 1: `utils.py` — 0% covered, pure logic, easy to test

This module contains pure-ish functions that are straightforward to unit test.

**Functions to test:**

1. **`get_room_identity()`** (lines 119-216) — Critical function used by every entity.
   - Non-duplicate area: returns `(slugify(area_id), area_name)`.
   - Duplicate area with dict-format `rooms` attribute on vacuum state.
   - Duplicate area with list-format `rooms` attribute.
   - Duplicate area with fallback to segment ID suffix.
   - Area registry lookup failure (exception path).
   - Missing vacuum entity state.

2. **`get_area_entities()`** (lines 10-25) — Foundational utility.
   - Entities directly in an area.
   - Entities on devices in an area (where entity `area_id` is None).
   - Empty area (no entities, no devices).

3. **`discover_occupancy_sensors()`** (lines 52-88)
   - Finds entities with `device_class == "occupancy"`.
   - Platform filter included/excluded.
   - Error handling when registry access fails.

4. **`discover_door_sensors()`** (lines 90-117)
   - Multi-area search.
   - Finds entities with `device_class == "door"`.
   - Exception handling per area.

5. **`get_entity_device_class()`** (lines 27-50)
   - Prefers state attribute over registry.
   - Falls back to `entry.device_class` then `entry.original_device_class`.
   - Returns `None` for missing entities.

### Priority 2: `binary_sensor.py` — 0% covered, complex state machine

`VeronikaRoomSensor` contains the core room-readiness logic — the most complex state machine in the codebase.

**Areas to test:**

1. **`_update_state()` — state machine** (lines 190-301)
   - Room occupied → `is_on = False`, reason = "Occupied".
   - Room occupied then cleared with cooldown → "Occupied (Cooldown)" until expiry.
   - Door closed in target area → "Door Closed".
   - Vacuum trapped (door closed in vacuum's area) → "Trapped".
   - All clear → "Ready", `is_on = True`.
   - Occupancy sensor unavailable/unknown → ignored.

2. **`async_added_to_hass()`** (lines 106-164)
   - Registers with manager.
   - Resolves entity IDs from registry.
   - Discovers sensors.
   - Subscribes to state changes.
   - Handles manager not found.
   - Handles sensor discovery failure.

3. **`_cooldown_expired()`** — timer callback triggers re-evaluation.

4. **`extra_state_attributes`** — returns expected attribute dict.

5. **`async_will_remove_from_hass()`** — cooldown timer cancellation.

### Priority 3: `__init__.py` — 0% covered, integration setup

**Areas to test:**

1. **`_validate_configuration()`** (lines 34-81)
   - Vacuum entity without `vacuum.` prefix → error.
   - Missing area → error.
   - Empty segments → warning (not error).
   - Negative cooldown → error.
   - Vacuum entity not yet available → warning only.
   - Valid configuration → empty error list.

2. **`async_setup()`** (lines 83-174)
   - Domain not in config → returns True (no-op).
   - Validation errors → returns False.
   - Manager initialization failure → returns False.
   - Platform loading failure → returns False.
   - Service registration — all 4 services registered.
   - `handle_clean_room` with area parameter.
   - `handle_clean_room` without area parameter → warning.

### Priority 4: `switch.py` — 0% covered, simple but important

**Areas to test:**

1. **`VeronikaSwitch`**
   - `async_turn_on()` / `async_turn_off()` toggle `_is_on`.
   - `async_added_to_hass()` restores state from `async_get_last_state()`.
   - Registers with manager on add.
   - Failed state restore defaults to `False`.

2. **`async_setup_platform()`**
   - Creates 2 switches per room (clean + disable).
   - Handles duplicate areas correctly.
   - No-op when `discovery_info` is None.

### Priority 5: `sensor.py` — 0% covered

**Areas to test:**

1. **`VeronikaPlanSensor.async_update()`** (lines 64-94)
   - Aggregates room counts correctly.
   - Handles `get_cleaning_plan()` exception → state = "Error".
   - Includes `last_error` and `error_count` in attributes.

2. **`async_added_to_hass()`** — builds watch list, subscribes to changes.

3. **`async_setup_platform()`** — handles missing manager.

### Priority 6: Deeper coverage of `manager.py` existing methods

The existing tests cover happy paths but miss many important branches.

**Missing test cases:**

1. **`_handle_segment_completion()`**
   - Duration below `min_segment_duration` → no-op.
   - Vacuum not in segment map → warning + return.
   - No switches for segment → debug log + return.
   - Switch service call failure with retry (3 attempts).
   - `ServiceNotFound` exception path.
   - Failure notification sent when switches fail.

2. **`_send_vacuum_command()`**
   - Retry logic on `TimeoutError` (3 attempts with backoff).
   - `ServiceNotFound` raises immediately (no retry).
   - Generic exception retry.
   - `_is_unloading` check → early return.
   - Invalid service format in payload → error.

3. **`_get_vacuum_command_payload()`**
   - Empty segments → `ValueError`.
   - No registry entry for vacuum → warning + generic command.
   - No device for vacuum → warning.

4. **`start_cleaning()` / `_start_cleaning_inner()`**
   - Empty plan → warning, no action.
   - Vacuum entity not found → error notification.
   - Vacuum command failure → error notification.
   - Unexpected exception → error count incremented, raises `HomeAssistantError`.

5. **`stop_cleaning()`**
   - Vacuum state not found → warning, skip.
   - Vacuum not cleaning (e.g., "docked") → no command sent.
   - Service call failure → error notification.

6. **`reset_all_toggles()`**
   - Switch service call failure → notification.
   - Skips entries with no switch ID.

7. **`async_unload()`**
   - Cancels pending completion tasks.
   - Unsubscribes all listeners.
   - Clears all caches.

8. **`_on_vacuum_state_change()`**
   - Segment change during cleaning → completes previous, starts new.
   - Vacuum stops cleaning → completes pending segment.
   - No `new_state` or `entity_id` → early return.
   - Pending completion task cancellation on new segment.

9. **`register_entity()`**
   - Unknown slug → warning.
   - Register switch_clean → updates segment map.
   - Register switch_disable / binary_sensor → updates cache.

10. **Multi-room configuration**
    - Multiple rooms per vacuum.
    - Multiple vacuums.
    - Duplicate area handling.

---

## Infrastructure Recommendations

1. **Add pytest configuration** — No `pyproject.toml`, `setup.py`, or `pytest.ini` exists. Adding a `pyproject.toml` with pytest settings would standardize test execution and enable coverage reporting.

2. **Add coverage tooling** — Install `pytest-cov` and configure a coverage threshold. Currently there is no way to measure coverage quantitatively.

3. **Refactor mock setup** — The 80-line mock preamble in `test_manager.py` should be extracted into a `conftest.py` or shared fixture module so new test files can reuse it.

4. **Add CI/CD** — No GitHub Actions workflow exists. A basic workflow running tests on push would prevent regressions.

---

## Summary

| Priority | Module | Current Coverage | Effort | Impact |
|----------|--------|-----------------|--------|--------|
| P1 | `utils.py` | 0% | Low | High — used by every entity |
| P2 | `binary_sensor.py` | 0% | Medium | High — core room readiness logic |
| P3 | `__init__.py` | 0% | Medium | Medium — setup/validation |
| P4 | `switch.py` | 0% | Low | Medium — state restore logic |
| P5 | `sensor.py` | 0% | Low | Low — display only |
| P6 | `manager.py` (gaps) | ~40% | Medium | High — error paths untested |
