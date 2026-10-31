# Features

Overview of the modes, transitions, external-control detection and the hold
model of the DayNight Lighting integration.

## 1. Modes

The integration has four modes (`const.py`): `day`, `night`, `sleep`, `wakeup`.
Each has its own handler (`handlers/day.py`, `night.py`, `sleep.py`,
`wakeup.py`).

| Mode | Driver | Brightness | Colour | Notes |
|---|---|---|---|---|
| **Day** | LUX sensor (interpolation `lux_on` ↔ `lux_off`) | `day_min` ↔ `day_max`, optional weather modifier | Circadian (sun elevation, `min` ↔ `max` K) | Damping: sends only on a change > `brightness_change_threshold_pct` (brightness) or ≥ 50 K (colour). **Fallback without LUX**: `skip` (default), `fixed`, `circadian_only`, `off` |
| **Night** | Motion sensor (on/off) | `night_brightness` (fixed) or a dialled-in value | Circadian (at night ≈ `min_kelvin`) | Off timer after motion (`motion_off_delay_min`). **Fallback without motion**: `skip` (default), `on`, `off`, `keep` |
| **Sleep** | Time window or service | Ramp from start value → `target_brightness` | Ramp → `target_kelvin` | Dim → OFF → "block" (dark lock, auto-clear after 2 h). Service can override duration/brightness/Kelvin |
| **Wake-up** | Time window or service | Ramp `start_brightness` → end (day max or night brightness) | Circadian / `end_kelvin` | Scheduled or service-triggered ramp. Ends in day or night |

There is also a **sensorless mode** (fallbacks, see above) and a priority
logic: service-started sleep/wake-up states (`_run_service_mode`) override the
schedule.

## 2. Transitions

Three transition contexts, each with its own duration option (all default `0` =
instant):

| Context | Option | Used for | Limit |
|---|---|---|---|
| `initial` | `initial_transition_seconds` | First turn-on (motion ON, switch ON) | — |
| `mode` | `mode_transition_seconds` | Mode change day ↔ night, end of sleep/wake-up | — |
| `tick` | `transition_seconds` | Regular updates (LUX day, circadian night, sleep/wake ramps) | max. 57 s (`MAX_TICK_TRANSITION_SECONDS`), must finish before the next tick |

The `TransitionCoordinator` calls `exit()` on the old handler and `enter()` on
the new one on a mode change, plus specific transition logic for 6 pairs
(`night→wakeup`, `wakeup→day`, `wakeup→night`, `day→sleep`, `sleep→night`,
`night→day`). On transition the target mode's state is applied (e.g. OFF when
the day fallback is `off`).

## 3. External-control detector (`manual_control.py`)

**Event-driven**: on every state change of a controlled light
(`_on_light_state_change`) the actual state is compared to the **persisted
expected state** (`StateController._expected_states`) that we stored when we
last commanded the light.

| Check | Rule |
|---|---|
| Grace period | 5 s after our own command is skipped (`mark_applied`) — covers async latency |
| No expected state | Light is skipped (we never commanded it) |
| **On/off divergence** | Always detected (ON ↔ OFF) |
| Brightness | Tolerance per mode |
| Colour | mired → Kelvin comparison; for RGB/HS/XY (e.g. Hue) u'v' distance (`COLOR_DISTANCE_THRESHOLD_UV = 0.02`) |

Tolerances per mode (`get_tolerances_for_mode`):

| Mode | Brightness | Kelvin |
|---|---|---|
| Day **with** LUX | 10 % | 300 K |
| Day **without** LUX | 5 % | 200 K |
| Night | 5 % | 200 K |
| Sleep / Wake-up | 8 % | 250 K |

**During a sleep/wake-up ramp** only on/off is judged (brightness/colour off,
because the ramp legitimately moves them) — an external OFF ends the whole ramp
(`interrupt_into_block`).

**Second path (night + motion only):** `handle_motion_on()` checks on every
motion whether a controlled light diverges from the night target and holds it
as `detected` on divergence — with the same tolerances as the event detector
(`compare_light_to_target` as the single source of truth).

## 4. Hold model (`state_controller.py`)

`held_lights` is a dict `{light_id: reason}` with two reasons:

| Reason | Trigger | Lifetime |
|---|---|---|
| `detected` | External intervention (scene, manual dimming, other automation) | **Survives** mode changes, ends only via explicit `release_hold` |
| `service` | `turn_on`/`turn_off` with `hold: true` (wall button / hold service) | Ends on mode change (`clear_holds(keep_detected=False)`) |

### Effect on normal behaviour

| Function | Effect on a held light |
|---|---|
| **Tick** (day/night/sleep/wake) | Light is filtered out via `exclude_held` — not touched |
| **Off timer (night)** | Skips held lights — they stay on |
| **Motion re-apply (night)** | Skips held lights |
| **Ramps (sleep/wake)** | Skip held lights |
| **Dial / re-apply** | Skip held lights |
| **Phase change** | `detected` is kept, `service` is cleared |

**`release_hold()`** (button/service): clears all holds, resets the brightness
dials to the configured values, forgets stored commands
(`_forget_applied_values`), and re-applies the mode — in a motion-lit night via
`reapply_after_release()` (actively brings lights back instead of holding them
again immediately), otherwise via `_apply_mode_now()`.

## Known open points

- The **grace period (5 s)** uses `datetime.now(timezone.utc)`, while
  `expected_states` uses `time.time()` — two different clocks for the same
  "just commanded" context.
- In the **night motion loop** a non-controlled light with "unexpected values"
  aborts the whole room (behaviour depends on the order of the light list).

Neither is an acute bug, but both are candidates for a later cleanup round.
