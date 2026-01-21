# Veronika Vacuum Manager

A custom Home Assistant integration for intelligent vacuum cleaning management with multi-vacuum support, room state monitoring, and automated segment-based cleaning.

## Features

- **🤖 Multi-Vacuum Support**: Manage multiple vacuum cleaners (Roborock, Dreame, and others)
- **📍 Segment-Based Cleaning**: Configure rooms using vacuum segment IDs for precise cleaning
- **🚪 Room State Monitoring**: Automatically checks if rooms are ready for cleaning
  - Door sensors: Prevents cleaning when doors are closed
  - Occupancy sensors: Skips occupied rooms with configurable cooldown
  - Trap detection: Prevents vacuum from getting stuck
- **⚡ Smart Scheduling**: Toggle-based system to enable/disable rooms for cleaning
- **🔄 Auto-Reset**: Automatically resets cleaning toggles after segment completion
- **🛡️ Error Handling**: Robust error handling with retries and user notifications
- **📊 Cleaning Plan Sensor**: Visualize which rooms will be cleaned before starting
- **🎯 Debug Mode**: Inspect vacuum commands before execution

## What's New in v1.1.0

- ✨ Full type hints for better code maintainability
- 🔧 Enhanced error handling with automatic retries
- 🐛 Fixed race conditions in segment tracking
- ⚠️ Persistent notifications for critical errors
- 🚀 Improved performance with better caching
- 📝 Better configuration validation (non-blocking for loading entities)
- 🔄 Fixed room sensors stuck in "Initializing" state

## Installation

### HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository in HACS:
   - Go to HACS > Integrations > ⋮ > Custom repositories
   - URL: `https://github.com/konairius/veronika-vacuum-manager`
   - Category: Integration
3. Click "Install"
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/veronika` folder to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

Add the following to your `configuration.yaml`:

### Basic Configuration

```yaml
veronika:
  rooms:
    - vacuum: vacuum.roborock_s7
      area: living_room
      segments: [16, 17]
    - vacuum: vacuum.roborock_s7
      area: kitchen
      segments: [18]
```

### Advanced Configuration

```yaml
veronika:
  # Global settings
  debug: false  # Enable debug mode to see vacuum commands
  min_segment_duration: 180  # Minimum seconds before auto-reset (default: 180)
  occupancy_cooldown: 300  # Global cooldown in seconds after occupancy detected
  segment_attribute: current_segment  # Attribute name for segment tracking
  sensor_platform: mqtt  # Filter occupancy sensors by platform (optional)
  
  rooms:
    - vacuum: vacuum.roborock_s7
      area: living_room
      segments: [16, 17]
      occupancy_cooldown: 600  # Room-specific cooldown (optional)
      segment_attribute: current_segment  # Room-specific override (optional)
      sensor_platform: mqtt  # Room-specific sensor filter (optional)
    
    - vacuum: vacuum.dreame_w10
      area: kitchen
      segments: [1, 2]
    
    - vacuum: vacuum.roborock_s7
      area: bedroom
      segments: [19]
      occupancy_cooldown: 0  # Disable cooldown for this room
```

### Configuration Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `vacuum` | string | Yes | - | Entity ID of the vacuum cleaner |
| `area` | string | Yes | - | Area ID from Home Assistant |
| `segments` | list | Yes | - | List of segment IDs for this room |
| `occupancy_cooldown` | integer | No | 0 | Seconds to wait after occupancy clears |
| `segment_attribute` | string | No | `current_segment` | Vacuum attribute containing current segment |
| `sensor_platform` | string | No | - | Filter occupancy sensors by platform |
| `debug` | boolean | No | false | Enable debug command inspection |
| `min_segment_duration` | integer | No | 180 | Minimum segment duration for auto-reset |

## Usage

### Entities Created

For each configured room, Veronika creates:

1. **Switch: Clean [Room]** - Toggle to include/exclude room from cleaning
2. **Switch: Disable [Room]** - Override to temporarily disable a room
3. **Binary Sensor: Status [Room]** - Shows if room is ready for cleaning
4. **Sensor: Cleaning Plan** (one per integration) - Overview of scheduled cleaning

### Services

#### `veronika.clean_all_enabled`
Starts cleaning all enabled and ready rooms.

```yaml
service: veronika.clean_all_enabled
```

#### `veronika.clean_specific_room`
Cleans a specific room by area ID.

```yaml
service: veronika.clean_specific_room
data:
  area: living_room
```

#### `veronika.reset_all_toggles`
Turns on all cleaning switches.

```yaml
service: veronika.reset_all_toggles
```

#### `veronika.stop_cleaning`
Stops all active vacuums and returns them to base.

```yaml
service: veronika.stop_cleaning
```

### Automation Examples

#### Daily Cleaning Schedule

```yaml
automation:
  - alias: "Morning Cleaning"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.someone_home
        state: "off"
    action:
      - service: veronika.clean_all_enabled
```

#### Reset Toggles After Cleaning

```yaml
automation:
  - alias: "Reset Cleaning Toggles"
    trigger:
      - platform: state
        entity_id: vacuum.roborock_s7
        to: "docked"
        for: "00:05:00"
    action:
      - service: veronika.reset_all_toggles
```

#### Disable Room When Occupied

```yaml
automation:
  - alias: "Disable Bedroom When Sleeping"
    trigger:
      - platform: state
        entity_id: binary_sensor.bedroom_occupancy
        to: "on"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.veronika_disable_bedroom
```

## Sensor Discovery

Veronika automatically discovers sensors in each room:

- **Occupancy Sensors**: Entities with `device_class: occupancy` in the room area
- **Door Sensors**: Entities with `device_class: door` in accessible areas
- **Vacuum Location**: Tracks vacuum's current area for trap detection

You can filter occupancy sensors by platform using the `sensor_platform` option.

## Supported Vacuum Integrations

Veronika works with multiple vacuum brands through manufacturer detection:

- **Roborock**: Uses `vacuum.send_command` with `app_segment_clean`
- **Dreame**: Uses `dreame_vacuum.vacuum_clean_segment`
- **Others**: Falls back to `vacuum.start` (no segment support)

## Troubleshooting

### Room Stuck in "Initializing"
- Check that the area exists in Home Assistant
- Verify vacuum entity is available
- Check logs for specific errors

### Vacuum Not Cleaning Segments
- Ensure segments IDs are correct for your vacuum
- Enable `debug: true` to see the exact command being sent
- Check that your vacuum integration supports segment cleaning

### Occupancy Not Working
- Verify occupancy sensors have `device_class: occupancy`
- Check sensor platform filter if using `sensor_platform` option
- Review entity registry to ensure sensors are in the correct area

### Auto-Reset Not Working
- Check `min_segment_duration` setting (default: 180 seconds)
- Verify vacuum reports `current_segment` attribute
- For non-standard integrations, configure `segment_attribute`

## Error Notifications

Veronika creates persistent notifications for:
- Failed vacuum commands (with retry attempts)
- Switch reset failures
- Service call errors

Check your Home Assistant notifications for detailed error information.

## Development

### Code Quality
- Full type hints for better IDE support
- Comprehensive error handling
- Retry logic for transient failures
- Race condition prevention

### Contributing
Contributions are welcome! Please ensure:
- Code follows existing type hint patterns
- Error handling is comprehensive
- Changes are tested with real vacuums

## License

This project is licensed under the MIT License.

## Credits

Developed for managing multiple robot vacuums across complex home layouts with intelligent room state detection.
