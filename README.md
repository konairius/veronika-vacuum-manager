# Veronika Vacuum Manager

A custom Home Assistant integration to manage complex vacuum cleaning schedules, room states, and safety checks.

## Features

- **Room State Monitoring**: Checks if rooms are ready for cleaning (doors open, unoccupied).
- **Smart Scheduling**: Only cleans rooms that are enabled and ready.
- **Safety Checks**: Prevents vacuum from entering rooms where it might get trapped.
- **Custom Card**: Includes a Lovelace card to visualize the cleaning plan.

## Installation

### HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Add this repository as a custom repository in HACS:
   - Go to HACS > Integrations > 3 dots > Custom repositories.
   - URL: `URL_TO_THIS_REPO`
   - Category: Integration
3. Click "Install".
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/veronika` folder to your `config/custom_components/` directory.
2. Copy `www/veronika-plan-card.js` to your `config/www/` directory.
3. Restart Home Assistant.

## Configuration

Add the following to your `configuration.yaml`:

```yaml
veronika:
  rooms:
    - name: "Living Room"
      vacuum: vacuum.roborock_s7
      area: "living_room"
      segments: [16, 17]
    - name: "Kitchen"
      vacuum: vacuum.roborock_s7
      area: "kitchen"
      segments: [18]
```

## Lovelace Card

Add the resource `/hacsfiles/veronika/veronika-plan-card.js` (if installed via HACS) or `/local/veronika-plan-card.js` (if manual).

```yaml
type: custom:veronika-plan-card
entity: sensor.veronika_cleaning_plan
```
