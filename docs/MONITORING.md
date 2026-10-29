# Monitoring

Every instance exposes four sensors that make its decisions visible. They
mirror the instance and never influence it — reading them cannot change how
the lights behave.

| Entity suffix | What it shows |
| --- | --- |
| `_mode` | Current mode: `day`, `night`, `sleep` or `wakeup` |
| `_target_brightness` | Brightness the instance last asked its lights for, in percent |
| `_target_color_temperature` | Colour temperature it last asked for, in Kelvin |
| `_mode_progress` | How far the sleep or wake-up ramp has run, unknown in other modes |

Entity IDs follow the device name, so an instance named *Kitchen* gets
`sensor.daynight_lighting_kitchen_mode` and so on. Adjust the examples below
to your instance names.

## Why these are entities and not attributes

Home Assistant records entity **states**. Only states appear as a timeline in
the history, produce logbook entries and can be used as automation triggers.
The three numeric sensors additionally carry a state class, so Home Assistant
keeps long-term statistics for them — the normal history is purged after ten
days, the statistics survive for years.

The mode sensor is an enum and therefore has no long-term statistics; see
[Hours per mode](#hours-per-mode) if you want to keep that beyond the purge
window.

## Target versus actual

`_target_brightness` is what the integration commanded, not what the lamp
reports. That difference is the point: if the two drift apart, something else
is driving the light.

Lamp brightness lives in an attribute, and core history cards can only draw
states, so expose it as a template sensor first:

```yaml
# configuration.yaml
template:
  - sensor:
      - name: Kitchen light brightness
        unique_id: kitchen_light_brightness
        unit_of_measurement: "%"
        state_class: measurement
        state: >
          {% set b = state_attr('light.kitchen_ceiling', 'brightness') %}
          {{ (b | float(0) / 255 * 100) | round(0) if b else 0 }}
```

With [ApexCharts](https://github.com/RomRider/apexcharts-card) you can plot
the attribute directly and skip the template sensor.

## Dashboard

A ready-made view is in [`day_night_monitoring.yaml`](day_night_monitoring.yaml).
Paste it into a dashboard via *Edit dashboard → Raw configuration editor*.

## Hours per mode

To keep "how long was this room in sleep mode" beyond the recorder purge
window, add a `history_stats` helper per mode you care about. These are
numeric and therefore get long-term statistics:

```yaml
# configuration.yaml
sensor:
  - platform: history_stats
    name: Kitchen sleep mode today
    entity_id: sensor.daynight_lighting_kitchen_mode
    state: "sleep"
    type: time
    start: "{{ today_at('00:00') }}"
    end: "{{ now() }}"
```

## Mode change event

Each mode change also fires `daynight_lighting_mode_changed` on the event bus,
which is the cheapest automation trigger:

```yaml
automation:
  - alias: Notify when a room starts its wake-up ramp
    trigger:
      - platform: event
        event_type: daynight_lighting_mode_changed
        event_data:
          to_mode: wakeup
    action:
      - service: notify.persistent_notification
        data:
          message: "{{ trigger.event.data.instance }} started waking up"
```

The event carries `entry_id`, `instance`, `area_id`, `from_mode` and
`to_mode`. On startup `from_mode` is `null`.
