# DayNight Lighting

A Home Assistant custom integration for automatic light control based on time of day. **Day mode** uses an illuminance (LUX) sensor to set brightness dynamically; **night mode** uses motion detection to turn lights on and off.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Flow Diagrams](docs/FLOW.md) — which mode runs, what a button press does, how a hold ends
- [Modes Explained](#modes-explained)
  - [Day Mode](#day-mode)
  - [Night Mode](#night-mode)
  - [Sensorless Mode (Without Sensors)](#sensorless-mode-without-sensors)
- [External Control Detection & Hold](#external-control-detection--hold)
  - [How It Works](#how-it-works)
  - [Hold (Detected vs. Service)](#hold-detected-vs-service)
- [Smooth Transitions](#smooth-transitions)
- [Sleep Mode](#sleep-mode)
  - [Configuration](#sleep-mode-configuration)
  - [What Happens After Sleep Ends](#what-happens-after-sleep-ends)
- [Wake-Up Mode](#wake-up-mode)
  - [Configuration](#wake-up-mode-configuration)
  - [What Happens After Wake-Up Ends](#what-happens-after-wake-up-ends)
- [LUX Flapping Prevention](#lux-flapping-prevention)
- [Monitoring](docs/MONITORING.md)
- [Services](#services)
- [Options Reference](#options-reference)
- [Possible Pitfalls](#possible-pitfalls)
- [Debug Logging](#debug-logging)

---

## Installation

### Manual

1. Copy the `custom_components/daynight_lighting` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **DayNight Lighting**.

### HACS

1. Add this repository as a custom integration in HACS.
2. Install **DayNight Lighting** and restart Home Assistant.

---

## Quick Start

1. **Add the integration:** **Settings → Devices & Services → Add Integration → DayNight Lighting**
2. Enter an **instance name** (e.g., "Bedroom", "Living Room")
3. **Configure options:** Click the integration → **Configure** to set lights, sensors, and behavior
4. **Turn on the main switch:** `switch.<instance>_daynight_lighting`

### Entities Created

| Entity | Purpose |
|--------|---------|
| `switch.<name>_daynight_lighting` | Main switch — turn ON to enable automatic control |
| `switch.<name>_daynight_lighting_control_brightness` | When OFF, integration doesn't change brightness |
| `switch.<name>_daynight_lighting_control_color` | When OFF, integration doesn't change color temperature |
| `switch.<name>_daynight_lighting_block_wall_buttons` | When ON at night with a motion sensor, our services are ignored (safety lock) |
| `number.<name>_daynight_lighting_night_brightness` | Night brightness in effect — a dial that a button press or slider moves, reset when night begins |
| `number.<name>_daynight_lighting_day_brightness` | Day brightness in effect for the *fixed* fallback — the same kind of dial for the day |
| `sensor.<name>_daynight_lighting_mode` | Active mode: day, night, sleep or wakeup |
| `sensor.<name>_daynight_lighting_target_brightness` | What the integration last commanded |
| `sensor.<name>_daynight_lighting_target_color_temperature` | Same, for colour |
| `sensor.<name>_daynight_lighting_mode_progress` | Ramp progress in sleep and wake-up |
| `sensor.<name>_daynight_lighting_lights_controlled` | How many lights the instance manages; the attribute `lights` lists them |
| `sensor.<name>_daynight_lighting_motion_sensors` | How many motion/presence sensors were found; `sensors`/`active` attributes list them |
| `sensor.<name>_daynight_lighting_illuminance_sensors` | How many LUX sensors were found; the `sensors` attribute lists them |
| `sensor.<name>_daynight_lighting_lux` | Current raw LUX reading; the `compensated` attribute is the ambient value day mode compares against `lux_on`/`lux_off` |
| `binary_sensor.<name>_daynight_lighting_on_hold` | ON while at least one light is held (visitor override or detected external control) |
| `binary_sensor.<name>_daynight_lighting_motion` | ON while motion/presence is present, across all sensors |
| `button.<name>_daynight_lighting_release_hold` | Press to drop the hold and restore the configured state |

The discovery sensors (`lights_controlled`, `motion_sensors`,
`illuminance_sensors`) answer "what did area discovery find?" in the device
card; the `lux` and `motion` sensors mirror live readings. See
[MONITORING.md](docs/MONITORING.md) for a ready-made card.

---

## Modes Explained

The integration runs in different modes depending on the time of day and your configuration.

### Day Mode

**When:** From sunrise until night start time (or configured time)

**Behavior:** Brightness is calculated from the LUX sensor using linear interpolation:

```
Low LUX (dark) → High brightness
High LUX (bright) → Low brightness or OFF
```

**Configuration:**
- `lux_on` — Below this LUX, use maximum brightness (default: 10)
- `lux_off` — Above this LUX, use minimum brightness or turn off (default: 100)
- `day_min_brightness` — Minimum brightness % (0 = off when LUX is high)
- `day_max_brightness` — Maximum brightness % at low LUX

**With circadian color enabled:** Color temperature follows the sun (warm at sunrise/sunset, cool at midday).

### Night Mode

**When:** From night start time until sunrise

**Behavior:** Motion-based lighting:
1. Motion detected → Lights turn ON at configured night brightness
2. Motion clears → Timer starts
3. Timer expires → Lights turn OFF

**Configuration:**
- `night_mode_start_time` — When night begins (e.g., 22:00)
- `night_mode_start` — "At sunset" (sun-based) or "At configured time only"
- `motion_off_delay_min` — Minutes to wait before turning off after motion clears
- `night_brightness` — Brightness % when motion turns lights on

**Motion and holds:** Motion does not override a hold. While a light is held, motion leaves it alone; once the hold is released, motion that is still present turns the lights on at the night values right away. See [FLOW.md](docs/FLOW.md#who-may-touch-the-lights).

### Sensorless Mode (Without Sensors)

The integration can operate without sensors using configurable fallback behaviors.

#### Day Mode Without LUX Sensor

| Fallback | Behavior | Use Case |
|----------|----------|----------|
| **Skip** (default) | Do nothing | Manual control during day |
| **Off** | Turn lights off | Rooms with sufficient daylight |
| **Circadian only** | Set color only, leave brightness unchanged | User controls brightness manually |
| **Fixed** | Fixed brightness with optional circadian color | Windowless rooms |

#### Night Mode Without Motion Sensor

| Fallback | Behavior | Use Case |
|----------|----------|----------|
| **Skip** (default) | Do nothing | Manual control at night |
| **Keep** | Keep current state | Maintain whatever was set |
| **Off** | Turn lights off | Unused rooms at night |
| **On** | Turn on at night brightness | Always-on night lighting (hallways) |

**Example: Guest Bedroom (No Sensors)**
```
Day fallback: Fixed (60%)
Night fallback: On (30%)
Circadian: Enabled
Night start: 22:00
```
Result: Fully automated lighting without any sensors.

---

## External Control Detection & Hold

### How It Works

The integration detects when lights have been changed externally (scenes, manual adjustments, other automations) by comparing **actual state** to **expected state**:

1. Whenever the integration applies values, it stores the expected state of each light
2. When a light reports a state change, the new state is compared to that stored expectation
3. If values differ beyond the mode's tolerance, external control is detected

**This approach is:**
- **Reboot-safe** — Expected states are persisted, and a detected override survives a restart
- **Event-driven** — A change is noticed when the light reports it, not on the next tick
- **Race-free** — A short grace period after our own commands covers their async latency
- **Attribute-specific** — Respects Control Brightness/Control Color switches

| Control Brightness | Control Color | Brightness Changed | Color Changed | Result |
|-------------------|---------------|-------------------|---------------|--------|
| ON | ON | Yes | — | Hold (`detected`) |
| ON | ON | — | Yes | Hold (`detected`) |
| OFF | ON | Yes | — | No violation (you control brightness) |
| ON | OFF | — | Yes | No violation (you control color) |
| OFF | OFF | Yes | Yes | No violation (we control nothing) |

**Tolerances:**
- Brightness: 5-10% depending on mode
- Color: 200-300K depending on mode

### Hold (Detected vs. Service)

When external control is detected, the integration puts the affected light on
**hold** and steps back. A held light is simply left alone until the hold ends.

A light can be held for one of two reasons, shown per-light on the `on_hold`
binary sensor:

- **`detected`** — somebody outside the integration changed the light (scene,
  dimmer, another automation). A detected hold deliberately has **no timeout**
  and does not auto-reset on stability: it ends only when you release it (via
  `release_hold`) or the mode changes.
- **`service`** — your automation called `turn_on`/`turn_off` with
  `hold: true`, or called `hold_all`. It is released with `release_hold` or
  automatically on the next mode transition.

The integration's own services never set a `detected` hold — an automation
that wants the room announces itself with a `hold: true` service call instead,
and while a light is held a wall button can still dim, because nothing here is
fighting it.

However a hold ends, the mode's values are applied immediately and the
integration forgets what it last commanded.

To hold every light of an instance at once (the replacement for the old
"manual control" switch), call `daynight_lighting.hold_all`; drop it again
with `daynight_lighting.release_hold`. See [Services](#services).

---

## Smooth Transitions

The integration supports configurable fade durations using native Home Assistant light transitions.

| Setting | Default | Used For |
|---------|---------|----------|
| `transition_seconds` | 0 (instant) | Regular tick updates (LUX changes, circadian refresh) |
| `initial_transition_seconds` | 0 (instant) | First turn-on (motion ON, switch ON) |
| `mode_transition_seconds` | 0 (instant) | Mode switches (day ↔ night) |

**Tips:**
- Set `transition_seconds=30` for gradual brightness changes as LUX varies
- Set `initial_transition_seconds=2` for gentle fade-in on motion
- Regular transitions are capped at 57 seconds (to complete before next tick)

**Note:** Not all lights support transitions. Simple WiFi bulbs and some MQTT lights apply values instantly.

---

## Sleep Mode

A gradual "go to bed" mode that dims lights over time, then turns them OFF.

### Sleep Mode Configuration

| Option | Description |
|--------|-------------|
| `sleep_enabled` | Enable sleep mode |
| `sleep_start_time` | When sleep begins (e.g., 21:00) |
| `sleep_duration_min` | Duration in minutes (15-240, **required**) |
| `sleep_use_auto_values` | Use day/night brightness and color as start values |
| `sleep_target_brightness` | Target brightness % at end (default: 20) |
| `sleep_target_kelvin` | Target color temperature in Kelvin (default: 2200) |

**Auto-values:** When enabled, sleep mode starts with the current mode's brightness and color:
- If sleep starts during **day mode**: Starts at `day_max_brightness` with circadian color
- If sleep starts during **night mode**: Starts at `night_brightness` with night circadian color

This provides a seamless transition from normal lighting into the sleep dimming phase.

**Duration Precedence:** When starting sleep mode, the duration is determined in this order:
1. **Service call** (`duration_min` parameter) — temporary override for this activation only
2. **Configuration** (`sleep_duration_min` setting) — your saved default
3. **Hardcoded default** (60 minutes) — fallback if not configured

### What Happens After Sleep Ends

**At sleep end time:**
1. Lights turn OFF
2. **Sleep block activates** — lights stay OFF until:
   - Motion is detected (if motion sensor configured), OR
   - Sunrise occurs (sensorless mode), OR
   - Manual override (user turns lights on manually)

**Example timeline:**
```
21:00 — Sleep starts
        ↓
        Gradual dimming: brightness ↓, color warms
        ↓
22:00 — Sleep ends
        ↓
        Lights turn OFF
        Sleep block activates
        ↓
22:30 — Motion detected
        ↓
        Sleep block clears
        Lights turn ON at night brightness
```

**Manual override during sleep:**
- If you change lights during sleep or the sleep block, sleep mode is cancelled immediately
- Normal control resumes

---

## Wake-Up Mode

A gradual brightening mode that simulates sunrise in the morning.

### Wake-Up Mode Configuration

| Option | Description |
|--------|-------------|
| `wakeup_enabled` | Enable wake-up mode |
| `wakeup_time` | When wake-up completes (e.g., 07:00) |
| `wakeup_duration_min` | Duration in minutes (default: 30) |
| `wakeup_use_auto_values` | Use day/night brightness and color as end values |
| `wakeup_start_brightness` | Starting brightness % (default: 1) |
| `wakeup_end_kelvin` | End color temperature in Kelvin (default: 5500) |

**Auto-values:** When enabled, wake-up mode ends with the destination mode's brightness and color:
- If wake-up ends during **day mode**: Ramps to `day_max_brightness` with circadian color
- If wake-up ends during **night mode**: Ramps to `night_brightness` with night circadian color

This provides a seamless transition from wake-up into normal lighting.

**Duration Precedence:** When starting wake-up mode, the duration is determined in this order:
1. **Service call** (`duration_min` parameter) — temporary override for this activation only
2. **Configuration** (`wakeup_duration_min` setting) — your saved default
3. **Hardcoded default** (30 minutes) — fallback if not configured

### What Happens After Wake-Up Ends

**At wake-up end time:**
1. Wake-up mode completes
2. **Normal mode resumes** — day mode or night mode depending on time/sunrise
3. Lights remain at the brightness reached during wake-up

**Target brightness:**
- **With auto-values enabled:** Ramps to the destination mode's brightness and color
  - If wake-up ends during **DAY** → Ramps to `day_max_brightness` with circadian color
  - If wake-up ends during **NIGHT** → Ramps to `night_brightness` with night color
- **With auto-values disabled:** Ramps to configured `wakeup_end_kelvin` and:
  - **With LUX sensor:** Ramps to LUX-based brightness (adaptive)
  - **Without LUX sensor:**
    - If wake-up ends during DAY → Ramps to `day_max_brightness`
    - If wake-up ends during NIGHT → Ramps to `night_brightness`

**Example timeline:**
```
06:30 — Wake-up starts
        Lights turn ON at 1%
        ↓
        Gradual brightening
        ↓
07:00 — Wake-up ends
        ↓
        Normal day mode continues
        Lights at final wake-up brightness
        LUX-based control takes over
```

**Note:** Wake-up is an **independent override mode** — it runs regardless of sunrise timing. If sunrise occurs mid-wake-up, the wake-up continues uninterrupted.

### Mode Priority & Day/Night Transitions

Both sleep and wake-up modes operate as **independent time windows** with priority over the base day/night modes:

**Priority order:**
1. **Sleep Mode** (highest priority)
2. **Wake-up Mode**
3. **Day Mode / Night Mode** (base modes)

**Behavior during transitions:**

| Scenario | Behavior |
|----------|----------|
| **Sleep active** | Sleep takes priority; dims regardless of day/night |
| **Sleep ends during night** | Sleep block stays active; lights off until motion or day |
| **Sleep ends during day** | Block clears; normal day control resumes |
| **Wake-up active** | Wake-up takes priority; brightens regardless of day/night |
| **Wake-up ends during day** | Hands off to day mode; LUX-based control takes over |
| **Wake-up ends during night** | Hands off to night mode; motion-based control takes over |

**Important:** These modes are **not** tied to night_start or sunrise times — they use their own configured time windows (`sleep_start_time` and `wakeup_time`).

---

## LUX Flapping Prevention

LUX sensors often measure total room light including your controlled lights, creating a feedback loop. Three layers of protection:

### 1. LUX Smoothing (Rolling Average)
Averages the last N samples to reduce sensor noise. Default: 3 samples.

### 2. Brightness Change Threshold
Only sends new brightness if it differs from the last applied value by at least X%. Default: 3%.

### 3. Flapping Detection & Freeze
If brightness direction changes 3+ times in 5 minutes, freezes brightness updates for a configurable period. Default: 5 minutes.

### 4. LUX Calibration (Recommended)

The most effective solution — measure and subtract lamp contribution:

1. After sunset, in a dark room (curtains closed)
2. Call the calibration service
3. Integration measures LUX with lights at 100%, then off
4. Stores the lamp contribution
5. Future readings subtract estimated lamp contribution

**Usage:**
```yaml
service: daynight_lighting.calibrate_lux
target:
  entity_id: switch.livingroom_daynight_lighting
```

Run once per room after sunset. Re-calibrate if you move the sensor or change lighting.

---

## Services

### `daynight_lighting.turn_on`

Turn on lights with optional parameters. Without brightness/color data, uses
integration's calculated values.

By default (`hold: false`) the lights are only switched on, and the day/night
automation keeps managing them — this is the right call for a system
automation. Set `hold: true` for a visitor interaction (a wall button): the
lights are then held on until the next mode transition, so the day/night
automation does not undo the visitor's choice — use `release_hold` to hand
back early.

```yaml
service: daynight_lighting.turn_on
target:
  entity_id: switch.bedroom_daynight_lighting
data:
  brightness_pct: 80
  # hold: true                # Optional: visitor hold until the phase ends
```

### `daynight_lighting.turn_off`

Turn off lights and clean up internal state. By default (`hold: false`) the
lights are only switched off and the day/night automation keeps managing
them. Set `hold: true` to hold them off until the next mode transition; use
`release_hold` to hand back early.

```yaml
service: daynight_lighting.turn_off
target:
  entity_id: switch.bedroom_daynight_lighting
data:
  hold: true  # Optional: visitor hold until the phase ends
```

### `daynight_lighting.start_sleep_mode`

Immediately start sleep mode regardless of schedule. Optional parameters override configured values.

```yaml
service: daynight_lighting.start_sleep_mode
target:
  entity_id: switch.bedroom_daynight_lighting
data:
  duration_min: 45 # Optional: override configured duration
  brightness_pct: 10 # Optional: override target brightness
  color_temp_kelvin: 2000 # Optional: override target color
```

### `daynight_lighting.start_wakeup_mode`

Immediately start wake-up mode regardless of schedule. Optional parameters override configured values.

```yaml
service: daynight_lighting.start_wakeup_mode
target:
  entity_id: switch.bedroom_daynight_lighting
data:
  duration_min: 60 # Optional: override configured duration
  start_brightness_pct: 5 # Optional: override start brightness
  end_brightness_pct: 80 # Optional: override end brightness
  color_temp_kelvin: 5000 # Optional: override end color
```

### `daynight_lighting.stop_sleep_mode`

Immediately stop sleep mode and return to normal day/night schedule. This also clears the sleep block.

```yaml
service: daynight_lighting.stop_sleep_mode
target:
  entity_id: switch.bedroom_daynight_lighting
```

### `daynight_lighting.stop_wakeup_mode`

Immediately stop wake-up mode and return to normal day/night schedule.

```yaml
service: daynight_lighting.stop_wakeup_mode
target:
  entity_id: switch.bedroom_daynight_lighting
```

### `daynight_lighting.adjust_brightness`

Dim or brighten by a step, meant for a wall button. What a press does depends
on what the instance is doing at the time, and the instance decides that
itself — no conditions or templates are needed in the automation. **A hold is
never detected**: a press is our own doing, not an intervention to step aside
for.

| Situation | Effect |
|---|---|
| Night | Moves the night brightness dial; motion, colour and the off timer keep running |
| Day with a LUX sensor | Ignored — the LUX curve keeps regulating |
| Day, no LUX sensor, fallback skip | Steps the lights — day mode sets no brightness here |
| Day, no LUX sensor, fallback fixed | Moves the day brightness dial |
| Day, no LUX sensor, fallback circadian only | Ignored — circadian controls colour only |
| Day, no LUX sensor, fallback off | Ignored — day mode wants these lights off |
| Sleep, Wake-up | Ignored — their ramps recompute every tick |
| Night with a motion sensor, block wall buttons on | Ignored — the safety lock blocks our services |

Dimming stops at 10 % on every path (5 % at night with a motion sensor), so a
button can never switch a light off. A dim press also releases the hold that
`turn_on`/`turn_off` placed, so you can dim again right after switching the
lights off. The full picture with a diagram:
[FLOW.md](docs/FLOW.md#a-button-press).

```yaml
service: daynight_lighting.adjust_brightness
target:
  entity_id: switch.livingroom_daynight_lighting
data:
  step: -10 # negative dims, positive brightens
```

### `daynight_lighting.reset_night_brightness`

Drop a dialled-in night brightness and go back to the configured value. This
also happens automatically when night mode begins.

```yaml
service: daynight_lighting.reset_night_brightness
target:
  entity_id: switch.livingroom_daynight_lighting
```

### `daynight_lighting.reset_day_brightness`

Drop a dialled-in day brightness and go back to the configured fixed
brightness. This also happens automatically when day mode begins.

```yaml
service: daynight_lighting.reset_day_brightness
target:
  entity_id: switch.livingroom_daynight_lighting
```

### `daynight_lighting.hold_all`

Hold every light of the instance at once — the bulk replacement for the old
"manual control" switch. While held, the day/night automation leaves all
lights of the instance alone. Use `release_hold` to hand back early; the hold
also clears by itself on the next mode transition.

```yaml
service: daynight_lighting.hold_all
target:
  entity_id: switch.livingroom_daynight_lighting
```

### `daynight_lighting.release_hold`

Drop the holds that a `turn_on`/`turn_off` (with `hold: true`) or `hold_all`
placed on the lights, so the day/night automation takes over again. It also
resets the brightness dials to their configured starting points, so the room
returns to the configured state rather than a value a visitor dialled in.
Normally the hold clears by itself on the next mode transition.

```yaml
service: daynight_lighting.release_hold
target:
  entity_id: switch.livingroom_daynight_lighting
```

### `daynight_lighting.calibrate_lux`

Measure lamp contribution for LUX compensation.

```yaml
service: daynight_lighting.calibrate_lux
target:
  entity_id: switch.livingroom_daynight_lighting
```

---

## Options Reference

### Devices Section

| Option | Description |
|--------|-------------|
| **Additional lights** | Extra light entities beyond area discovery |
| **Additional light sensor(s)** | LUX sensor(s) for day mode (multiple allowed, averaged) |
| **Additional motion/presence sensor(s)** | Binary sensor(s) for night mode (multiple allowed, OR logic) |

### Area Discovery Section

| Option | Default | Description |
|--------|---------|-------------|
| Use area discovery | On (with area) | Auto-discover lights and sensors from the selected area |
| Included lights | — | Lights explicitly controlled when area discovery is on |
| Excluded motion sensors | — | Motion sensors to ignore during discovery (e.g. a camera AI sensor that latches on) |

### Day Mode Section

| Option | Default | Description |
|--------|---------|-------------|
| LUX below this: max brightness | 10 | Use max brightness at or below this LUX |
| LUX above this: min brightness or off | 100 | Use min brightness at or above this LUX |
| Day: minimum brightness % | 0 | 0 = off when LUX is high |
| Day: maximum brightness % | 100 | Brightness at low LUX |
| LUX smoothing samples | 3 | Rolling average size (1 = disabled) |
| Brightness change threshold % | 3 | Minimum change to send command |
| Flapping freeze duration (min) | 5 | Freeze time after oscillation detected |
| Day mode without LUX sensor | Skip | Fallback when no LUX sensor |
| Fixed brightness % | 80 | Used with "Fixed" fallback |

### Night Mode Section

| Option | Default | Description |
|--------|---------|-------------|
| Night mode start time | 22:00 | When night begins (if using "At time") |
| Night mode starts | At configured time only | "At sunset" or "At configured time only" |
| Minutes until lights off after motion | 5 | Motion-off delay |
| Night brightness % | 100 | Brightness when motion turns lights on |
| When entering night mode | Leave as is | "Leave as is" or "Turn lights off" |
| Night mode without motion sensor | Skip | Fallback when no motion sensor |

### Transitions Section

| Option | Default | Max | Description |
|--------|---------|-----|-------------|
| Regular updates | 0 | 57s | Tick updates, LUX changes |
| First turn-on | 0 | 120s | Motion ON, switch ON |
| Mode change | 0 | 300s | Day ↔ Night transitions |

### Circadian Section

| Option | Default | Description |
|--------|---------|-------------|
| Circadian color temperature | On | Enable sun-based color temperature |
| Min Kelvin (warm) | 2700 | Color at low sun / night |
| Max Kelvin (cool) | 5500 | Color at midday |

### Sleep Mode Section

| Option | Default | Description |
|--------|---------|-------------|
| Enable sleep mode | Off | Enable gradual dimming |
| Sleep start time | 21:00 | When sleep begins |
| Sleep duration (min) | 60 | How long sleep lasts (15-240) |
| Use automatic start values | On | Use day/night values as start |
| Target brightness % | 20 | End brightness (when auto off) |
| Target Kelvin | 2200 | End color temperature (when auto off) |

### Wake-Up Section

| Option | Default | Description |
|--------|---------|-------------|
| Enable wake-up light | Off | Enable gradual brightening |
| Wake-up completion time | 07:00 | When wake-up ends |
| Wake-up duration (min) | 30 | How long wake-up lasts |
| Use automatic end values | On | Use day/night values as end |
| Start brightness % | 1 | Beginning brightness |
| End Kelvin | 5500 | End color temperature (when auto off) |

### Weather Section

| Option | Default | Description |
|--------|---------|-------------|
| Enable weather brightness | Off | Adjust brightness by weather |
| Weather entity | — | e.g., `weather.home` |

---

## Possible Pitfalls

### 1. Lights Oscillate (Brightness Flapping)

**Cause:** LUX sensor measures both ambient light and your lights, creating a feedback loop.

**Solution:**
1. Run `daynight_lighting.calibrate_lux` after sunset in a dark room
2. Increase `lux_smoothing_samples` (try 5)
3. Increase `brightness_change_threshold_pct` (try 5-10%)
4. Move the sensor away from direct light

### 2. Integration Doesn't Take Control After Stability Period

**Cause:** Lights are not actually "stable" — tiny fluctuations reset the counter.

**Solution:** The v1.7.2+ fix uses tolerances (~1% brightness, ~50K color). Upgrade if using an older version.

### 2b. Lights Stay at a Stale Brightness After a Detected Override Ends

**Cause:** Fixed in v1.12.0. Day mode only sent a brightness when it differed
from the last one it had sent itself, and that reference was stale after
somebody else changed a lamp. On a bright day the LUX-derived target barely
moves, so every tick decided it was already at its target — most visible in a
calibrated room, since calibration makes the reading independent of your own
lamps.

**Check on older versions:** the log shows
`Brightness change 62% → 61% (Δ=1%) below threshold (3%), skipping` on every
tick. Reloading the integration clears it.

### 3. External Control Detected Unexpectedly

**Possible causes:**
- Control Brightness/Color switches are ON but you're adjusting those values
- Another automation is running
- Light hardware reports slightly different values than sent

**Solution:**
- Turn OFF Control Brightness if you want to control brightness manually
- Turn OFF Control Color if you want to control color manually

### 4. Wake-Up Starts Late or Doesn't Run

**Cause:** Wake-up window calculated incorrectly, or Sleep Mode is active.

**Check:**
- `wakeup_time` is the **end** time, not start
- `wakeup_duration_min` determines the start time (end minus duration)
- Sleep Mode has higher priority than Wake-Up Mode

### 5. Night Mode Doesn't Turn Lights On

**Causes:**
- Motion sensor not configured
- Night fallback set to "Skip" or "Off"
- The light is held (see the `on_hold` binary sensor) — release the hold

### 6. Lights Turn Off Unexpectedly at Night

**Causes:**
- Motion-off timer expired
- `hold: true` not set when calling `turn_on` — without it the night motion
  logic keeps managing the light and turns it off again
- Night fallback is "Off"

**Solution:** Use `hold: true` in your automation for a visitor interaction:
```yaml
service: daynight_lighting.turn_on
data:
  hold: true
```

### 7. Day Mode Keeps Turning Lights Off

**Cause:** `day_min_brightness` is 0 and LUX is above `lux_off`.

**Solution:** Set `day_min_brightness` to a value > 0 if you want lights to stay on.

### 8. Circadian Color Not Applied

**Causes:**
- Circadian disabled in options
- Control Color switch is OFF
- Light doesn't support color temperature

### 9. Options Changes Don't Take Effect

**Cause:** Should be instant, but if not working:

**Check:** Main switch is ON — options only apply when the integration is active.

### 10. Lights Get Held Unexpectedly

**Cause:** The integration detected an external change (scene, manual adjustment, other automation) and put the light on hold.

**To prevent:** Turn OFF Control Brightness or Control Color for attributes you want to manage manually. To drop the hold, call `daynight_lighting.release_hold`.

### 11. A Wall Button Does Nothing During the Day

**Cause:** Since v1.15.0 a press in day mode is ignored when a LUX sensor
regulates the brightness — a closed loop would regulate a step away within a
tick or two, so there is nothing to hold. It is also ignored when:
- the day fallback is *circadian only* (controls colour only) or *off*;
- the `number.…_day_brightness` entity is disabled
  (`no day brightness dial, ignored`).

Day *skip* steps the lights, day *fixed* moves the day brightness dial.

**If you want to hold a value regardless of LUX:** call `hold_all` from the
same automation. That stops the regulation, and the button then steps the
lights directly. When you release the hold, the current mode is applied again
immediately. See [FLOW.md](docs/FLOW.md#a-button-press).

### 12. Values Passed to `turn_on` Are Gone a Minute Later

**Cause:** Changed in v1.13.0. An explicit `brightness_pct` used to switch
manual control on so the value would stand for half an hour. It no longer
does — our own service is never "somebody outside", so it does not create a
detected hold.

**Solution:** pass `hold: true` with the `turn_on` call (or use `hold_all`)
for as long as the values should stand, and call `release_hold` when your
automation is done.

---

## Debug Logging

Enable detailed logging:

```yaml
logger:
  default: info
  logs:
    custom_components.daynight_lighting: debug
```

Logs include:
- Mode transitions (day ↔ night ↔ sleep ↔ wake-up)
- LUX readings and brightness calculations
- Motion events and off-timer scheduling
- External control detection and holds

See [DEBUG_LOGGING.md](docs/DEBUG_LOGGING.md) for how to view the logs and
which message fragments to search for.

---

## Requirements

- Home Assistant (recent versions)
- **Sun** entity (built-in) for day/night calculation
- For full day mode: LUX sensor
- For full night mode: Motion/presence sensor

---

## License

See repository or integration manifest.
