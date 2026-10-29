# Changelog

All notable changes to DayNight Lighting will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.19.42] - 2026-10-29

### Fixed
- A light listed twice (any case) in `included_lights` or the legacy `lights`
  field was passed through as-is, so the "Lights controlled" monitor counted
  and listed it twice. `get_effective_lights` now deduplicates case-insensitively,
  keeping first-seen order.

## [1.19.41] - 2026-10-29

### Fixed
- The select dropdowns in the options flow (day-mode fallback, night-mode
  fallback, night-mode start, on-enter-night) had their labels hard-coded in
  English and were never translated. They now use translation keys, so the
  German UI shows German option labels.

### Changed
- README options reference: documented `excluded_motion_sensors`, moved the
  LUX-smoothing/anti-flapping settings into the Day Mode section (there is no
  separate "Advanced" section), and described the light/motion sensor fields as
  the multi-selects they became in 1.19.37.

## [1.19.40] - 2026-10-29

### Fixed
- Turning area discovery off carried the area's `included_lights` into the
  manual `lights` field but left the selection in `included_lights` as well, so
  the same lights showed in both "Additional lights" and the area section. The
  selection is now moved (not copied): `included_lights` is cleared when it is
  carried over to `lights`.

## [1.19.39] - 2026-10-26

### Fixed
- With `on_enter_night: "turn_off"` and presence already active, the lights
  were switched off on entering night and only re-applied on the next tick, so
  they visibly flickered off for up to ~30 s. Entering night with presence now
  skips the off and re-applies the night target to the lights that are already
  on, exactly like the "leave" path; the off-timer still switches them off once
  the room empties.

## [1.19.38] - 2026-10-23

### Fixed
- Day mode's circadian colour updates went out as colour-only `light.turn_on`
  commands. Hue lights (via the Hue bridge) drop to a low brightness in
  response to a colour-only command, so the external-control detector read a
  real brightness drop as a manual override and put the room on hold even
  though nobody touched the lights. Day mode now re-affirms the current
  brightness on every colour update, so the light always receives brightness
  and colour together.

## [1.19.37] - 2026-10-21

### Added
- Manual configuration now accepts **multiple** motion and illuminance sensors,
  matching area discovery. Multiple illuminance sensors are averaged (as
  before); multiple motion sensors use OR logic (light stays on while any
  sensor reports motion). Legacy single-entity options keep working and are
  upgraded in place.

## [1.19.36] - 2026-10-19

### Fixed
- With `on_enter_night: "leave"`, the first motion after sunset held the lights
  as an "external scene" (`hold`, reason `detected`) instead of dimming them to
  the night target. The still-day-valued lights were misread as a foreign
  override. The first motion event now re-applies the night target, and only
  later divergences are treated as external scenes.

## [1.19.35] - 2026-10-19

### Fixed
- Instances without a light sensor spammed "No light_sensor configured" many
  times per tick (the monitor sensors read LUX repeatedly). The notice is now
  logged once per instance lifetime instead of on every read.

## [1.19.34] - 2026-10-19

### Added
- `excluded_motion_sensors` option: with area discovery enabled, these motion
  sensors are dropped from the discovered set (e.g. a camera AI-detection
  sensor that latches on). A manually configured motion sensor is still
  honoured, and illuminance sensors are unaffected.

## [1.19.33] - 2026-10-19

### Fixed
- Turning area discovery off while the light selection was still recorded
  under the area section (`included_lights`) left the legacy `lights` field
  empty, so day mode logged "No lights configured" and skipped applying. The
  effective-light resolution now falls back to `included_lights` in legacy
  mode, and the options flow carries the selection over into `lights` when
  discovery is disabled — so the lights no longer silently vanish.

## [1.19.32] - 2026-10-19

### Fixed
- A light that briefly went `unavailable` (e.g. a Zigbee device drop) was
  treated as "externally turned off" by the external-control detector and put
  on hold with reason `detected` — a false positive, because nobody switched
  it off, the device just lost connectivity for a few seconds. The detector
  now skips `unavailable`/`unknown` states instead of judging them, matching
  the guard already used for sensor readings.

## [1.19.31] - 2026-10-19

### Fixed
- Pressing "Reset brightness" in a motion-lit night did nothing at first and
  then put the light on hold. Resetting the dial re-applied the mode through
  the motion handler, which saw the still-dimmed light as a divergence from
  the restored target and held it "detected" on the spot. The reset now
  re-applies the configured brightness to the lights already on (exactly like
  a dial change), so the dimmed light returns to the configured value without
  a hold, and an off light stays off.

## [1.19.30] - 2026-10-19

### Changed
- Code cleanup, no behaviour change. The night re-apply skip test
  (`_matches_target_tightly`) no longer hand-rolls its own mired/xy colour
  maths — it now goes through the same `compare_light_to_target` single source
  of truth, using a new `strict` flag plus tight tolerances (1 % brightness /
  30 K) so a missing attribute still means "re-apply". The release-hold path
  gained a self-describing `reapply_after_release()` instead of a boolean
  `handle_motion_on(force=True)`, and the empty `pass` branch in
  `release_hold()` was restructured away.

## [1.19.29] - 2026-10-19

### Fixed
- "Release hold" did nothing in a motion-lit night while the scene was still
  active. Releasing cleared the hold, but the motion re-apply then saw the
  light still showing the scene's values and re-held it on the spot, so the
  light never returned to night mode. The release path now *forces* the
  released lights back to the night target (`handle_motion_on(force=True)`)
  instead of re-holding them, and still respects a service-started
  sleep/wake-up that outranks the schedule.

## [1.19.28] - 2026-10-19

### Changed
- The "does this light differ from the target" comparison is now a single
  source of truth (`compare_light_to_target`). The event-driven detector and
  the night motion handler both call it, so a scene is judged with the *same*
  tolerances on every path. Previously the motion handler used a looser
  adoption tolerance (10 % brightness / 75 mired), while the detector used
  5 % / 200 K — leaving a 6–10 % band where the detector said "external" but
  motion re-applied the light anyway (re-arming the grace period and
  suppressing detection). The hold decision now uses the detector's exact
  night tolerances, closing that band. The mode tolerance constants moved to
  module level and `_mired_to_kelvin` now tolerates malformed/zero values
  instead of crashing.

## [1.19.27] - 2026-10-19

### Fixed
- A scene that diverges a controlled light in night mode now ends in a
  `detected` hold, not just "left alone". 1.19.26 stopped the motion re-apply
  that overwrote the scene, but set no hold, so the scene was still dropped by
  the motion-off timer and there was no "On hold" state / release button to
  return to normal. The motion handler now holds a diverged light itself —
  unless it is still inside its own grace period (our own in-flight ramp),
  which is left alone without a hold.

## [1.19.26] - 2026-10-19

### Fixed
- Night mode with a motion sensor no longer overwrites an external scene
  before the event-driven detector can hold it. Two root causes were fixed:
  (1) XY-native bulbs (e.g. Hue, reporting `xy_color`/`color_mode: "xy"`)
  never matched the night target *tightly*, so every motion/LUX tick re-applied
  an unchanged circadian white and permanently re-armed the grace period — which
  swallowed the scene's state change. The tight-match check now compares
  chromaticity to the commanded white via the CIE 1976 u'v' distance. (2) A
  controlled light that *strongly* diverges from the night target (beyond the
  adoption tolerance) is now left alone instead of being force-matched, so a
  scene or manual override survives until the detector sets a `detected` hold.

## [1.19.25] - 2026-10-19

### Fixed
- A detected hold (a scene or manual intervention) now survives a day/night
  phase change instead of being silently dropped. The mode transition cleared
  every hold, so a Hue scene that was active at sunset was lost as soon as the
  night mode touched the light (motion, or "turn off on entering night"). Only
  *service* holds (`turn_on`/`turn_off` with `hold: true`) are phase-scoped and
  still end at the transition; a *detected* hold now persists until the user
  releases it explicitly (button or `release_hold` service).

## [1.19.24] - 2026-10-18

### Reverted
- The "Release hold" and "Reset brightness" buttons are once again only
  available when they actually have something to do (a hold exists, or the
  brightness dial is dialled in) — restoring the previous, intentional UX.
  The always-available change from 1.19.23 is reverted. To avoid HomeKit's
  "Referenced entities … are missing or not currently available" warning,
  do not expose these two buttons to the HomeKit bridge (they are actions,
  not state; the "On hold" binary sensor already carries the state).

## [1.19.23] - 2026-10-18

### Fixed
- The "Release hold" and "Reset brightness" buttons no longer report
  `unavailable` whenever there is nothing to do. Exposed to HomeKit (or
  referenced by an automation/dashboard) they produced a
  "Referenced entities … are missing or not currently available" warning on
  every press with no active hold/dim. A button is an *action*, not a state,
  so both buttons now stay available and simply no-op when there is nothing
  to release or reset (the "On hold" binary sensor already reports the state).

## [1.19.22] - 2026-10-18

### Fixed
- Circadian rooms no longer go on hold after the RGB/HS/XY scene detection
  (1.19.19). Colour bulbs such as Philips Hue are XY-native: when told a
  colour temperature they report the resulting white back as `xy_color`/
  `color_mode: "xy"` (without `color_temp`), which the 1.19.19 check mistook
  for a coloured scene and held. The detector now converts the reported
  colour to CIE chromaticity and measures its distance from the white point
  of the Kelvin it commanded: our own circadian white is accepted, while a
  saturated scene or a clearly different white is still held.

## [1.19.21] - 2026-10-18

### Fixed
- Area discovery no longer re-scans the registries on every registry update
  event. HA fires one `entity_registry_updated`/`device_registry_updated`/
  `area_registry_updated` event per restored item at startup, so a boot with
  dozens of entities and five instances produced hundreds of "Area entities
  changed (registry update)" lines and hundreds of redundant scans. Registry
  events are now debounced: they (re)arm a short quiet-period timer, and the
  area is re-discovered once the event stream pauses (~5 s). A newly added
  lamp or sensor is still adopted within seconds, but the startup burst now
  collapses into a single pass.

## [1.19.20] - 2026-10-18

### Fixed
- Startup race: at HA boot the just-restored lights report their state
  asynchronously, and colour bulbs briefly show an RGB/HS/XY colour before
  the persisted colour temperature lands. The new RGB detection (1.19.19)
  misread that transient as an external scene and held every light in the
  room. Restored lights are now marked "just applied" when the instance
  starts (and when it is switched on), so the detector's grace period covers
  the restore window.

## [1.19.19] - 2026-10-18

### Fixed
- External-control detection now recognises RGB/HS/XY colours. A Hue scene or
  colour picker that sets an `rgb_color`/`hs_color`/`xy_color` (instead of a
  colour temperature) previously went unnoticed, because the detector only
  compared `color_temp`; the next tick then overwrote the colour with the
  circadian temperature. Such a colour is now treated as an intervention and
  holds the light until released. A brightness-only white bulb (no colour
  attributes) is still not flagged.

## [1.19.18] - 2026-10-18

### Fixed
- Area discovery no longer adopts the integration's own mirror entities
  (`lux`, `illuminance_sensors`, `motion`). Their names and device classes
  match the sensor keywords, so they were being fed back into the inputs they
  mirror — corrupting the LUX average and re-triggering the tick on every
  mirror write, which produced an endless debug-log loop.

## [1.19.17] - 2026-10-18

### Added
- New instance sensors so the device card shows what area discovery found and
  what the instance currently senses:
  - `sensor.<name>_daynight_lighting_lights_controlled` (count, `lights` attribute)
  - `sensor.<name>_daynight_lighting_motion_sensors` (count, `sensors`/`active`)
  - `sensor.<name>_daynight_lighting_illuminance_sensors` (count, `sensors`)
  - `sensor.<name>_daynight_lighting_lux` (raw LUX, `compensated` attribute)
  - `binary_sensor.<name>_daynight_lighting_motion` (motion present now)
- The discovery/live sensors are pushed through the monitor signal, so the LUX
  and motion mirrors refresh on the underlying sensor change and the minute
  tick; the LUX mirror reads raw state without touching the smoothing buffer.

## [1.19.14] - 2026-10-18

### Changed
- Rewrote `docs/FLOW.md` for the per-light hold model: the "manual control"
  lifecycle and the removed "scene blocker" section are gone, replaced by
  "The life of a hold" (`detected` vs. `service`) and an updated tick flow.
- Updated `docs/DEBUG_LOGGING.md` with the current message fragments and a
  search-by-topic table; the stale pre-hold log strings are removed.

### Removed
- Deleted the remaining obsolete docs (`NIGHT_BRIGHTNESS.md`, `PITFALLS.md`,
  `STATE_CONTROLLER_IDEA.md`, `TESTING.md`, and the hold-merge plan).
  `README.md` no longer links to them; `FLOW.md`, `MONITORING.md` and
  `DEBUG_LOGGING.md` are the living documentation.

## [1.19.15] - 2026-10-18

### Fixed
- Restored `docs/MONITORING.md` and its ready-made dashboard
  `day_night_monitoring.yaml`, which had been removed by mistake. The
  dashboard's stale "manual control" entity was replaced with the `on_hold`
  binary sensor.

## [1.19.16] - 2026-10-18

### Changed
- Restored `docs/day_night_light.yaml` (the pre-integration automation
  blueprint) without the scene blocker: the `light_scene_blocker` input, its
  variable binding, and the blocking condition are removed.

## [1.19.13] - 2026-10-18

### Removed
- Dead code that had accumulated across the refactor to the per-light hold
  model: the unused `types.py` module, the `IlluminanceProvider` and
  `WeatherProvider` protocols, the unused `LightState` and `TimeWindow` domain
  models, and the unused `add_transition` helper. The duplicated brightness
  conversion (`_brightness_to_pct` in `manual_control.py`) was folded into the
  shared `brightness_to_pct` in `domain/brightness.py`.
- Two misdirected transition mappings in the transition coordinator
  (`wakeup → sleep` pointed at the wake-up-to-day handler and `sleep → wakeup`
  at the sleep-to-night handler), plus the empty `day → night` handler.

### Changed
- Removed the leftover "scene blocker", "manual control switch" and
  `keep_on_in_night_mode` references from the documentation. `README.md` now
  describes the hold model (`detected` vs. `service`), the `hold_all` service,
  and the current options. Obsolete planning notes at the repository root were
  deleted; `CHANGELOG.md` and `README.md` remain the living documentation.

### Fixed
- Minor lint issues: unused `Any` import in `manual_control.py`, an unused
  `area_name` computation in the options flow, and ambiguous one-letter loop
  variables in `config.py`.

## [1.19.12] - 2026-10-18

### Changed
- The night-motion re-apply skip (1.19.11) now uses a *tight* comparison
  against the exact night target instead of the loose adoption tolerances
  (10% brightness / 75 mired). A controlled light still follows the circadian
  curve step by step — any real colour drift, however small, re-applies on the
  next motion — while the flat part of the night curve stays quiet. Missing
  brightness/colour attributes re-apply instead of skipping.

## [1.19.11] - 2026-10-18

### Changed
- Night motion no longer re-sends `light.turn_on` to a light that is already
  on, controlled by us, and already matches the night values (brightness and
  circadian colour). Deep in the night the circadian curve is flat, so every
  movement used to re-apply the identical values — four "Expected state saved"
  lines plus a "turned on" per movement, per room. A matching light is now
  skipped; the re-apply still happens when the colour actually drifted
  (circadian moved) or the brightness dial changed, so the gradual colour
  refresh and the dial are unaffected.

## [1.19.10] - 2026-10-18

### Fixed
- The registry-update event constants were imported from `homeassistant.const`,
  where they were removed in HA 2025/2026 (they now live as typed `EventType`
  objects in the registry helper modules). This broke every instance on setup
  in HA 2026.10. The integration now uses the plain, stable event-name strings
  directly, so event-driven area discovery works across HA versions.

## [1.19.9] - 2026-10-18

### Changed
- Area discovery is now event-driven: the instance listens to the entity,
  device and area registries and re-discovers the moment something changes, so
  a newly added lamp, motion sensor or illuminance sensor in the area is
  adopted within seconds. The previous per-minute re-scan is gone — the cache
  is only invalidated on an actual registry update or options change, with a
  five-minute safety net in case an event is ever missed. A registry event
  that leaves the adopted entity set unchanged (e.g. an area rename) no longer
  re-applies the lights.

## [1.19.8] - 2026-10-18

### Changed
- Area discovery (lights, motion sensors, illuminance sensors) is now cached for
  a minute on the switch instead of re-scanning the registries on every state
  read and sensor event. This removes the flood of "Found N … sensors" DEBUG
  lines that could truncate the debug log within a couple of hours. The cache
  is dropped on every options change, and the one-minute TTL still lets
  sensors resolved late after startup appear promptly. No behaviour change —
  the discovered sensors and lights are still exposed as entity attributes.

## [1.19.7] - 2026-10-17

### Changed
- The external-control grace period is now opened in exactly one place — the
  `LightApplier` — instead of also being re-opened by several scattered call
  sites after the fact. The redundant `mark_applied` calls in
  `_step_brightness_directly`, the mode transition, the options reload and the
  re-apply helpers were removed. Only the service path, which calls the light
  domain directly (not via the applier), still marks its lights explicitly.
  No behaviour change, except that skipped lights (off lights in a dim step)
  are no longer needlessly exempted.

## [1.19.6] - 2026-10-16

### Fixed
- The flapping (anti-oscillation) detector only remembered the last five
  brightness changes, so a *slow* feedback loop — a LUX sensor reacting to its
  own lamps and swinging brightness over several minutes — never showed three
  direction changes at once and was never frozen. It now remembers a full
  cycle, so such a loop is detected and frozen instead of flapping
  indefinitely (e.g. 28% → 3% → 28% over five minutes).

## [1.19.5] - 2026-10-16

### Fixed
- A normal day/night tick sent its own `light.turn_on`/`turn_off` without
  opening the detection grace period, so with a non-zero transition the
  integration could mistake its own in-flight command for external control and
  hold a light "by itself". Every command now exempts exactly the lights it
  touched from detection while the command is in flight.

## [1.19.4] - 2026-10-16

### Fixed
- The `Day brightness` dial only reacts to the *first* configured LUX sensor,
  so a room with several illuminance sensors could wait up to a minute for the
  mean to refresh when a non-first sensor changed. All LUX sensors are now
  subscribed, so every sensor change recomputes the mean immediately (the mean
  itself was always calculated).

### Changed
- The `Day brightness` number is now unavailable in rooms where a LUX sensor
  drives the brightness: with a LUX curve there is no single fixed target, so
  the dial is meaningless and previously showed a value nothing read. It now
  hides itself, and follows area discovery so it reacts when sensors are found
  after startup. The `Night brightness` dial stays available — motion/presence
  sensors only toggle lights on/off, never the fixed night brightness target.

## [1.19.3] - 2026-10-16

### Fixed
- A wall-button `turn_on` stopped switching once a hold was active: the
  pre-1.19.0 `keep_on_in_night_mode` parameter that old wall-button automations
  still send was forwarded to `light.turn_on`, which rejects it ("not a valid
  option"). The key is now stripped before the forward, so old automations keep
  working — it is redundant with `hold: true` and is silently ignored.

## [1.19.2] - 2026-10-16

### Fixed
- The `Target brightness` / `Target color temperature` monitoring sensors and
  the persisted expected state recorded the freshly *computed* value even for
  an attribute the day-mode damper had skipped sending. In a room with a LUX
  sensor the brightness and colour are applied independently, so a brightness
  update carried the not-yet-applied colour (and vice versa), letting the
  target drift from what the light actually had. They now report the value
  actually sent, keeping the previous one for the skipped attribute.

## [1.19.1] - 2026-10-16

### Fixed
- A wall-button `turn_on` (`hold: true`) could not switch a light back on in
  day mode after it had been switched off: when the LUX curve wanted the
  light off (a bright room with `day_min_brightness` 0 and LUX at/above
  `lux_off`) the service computed brightness 0 and left the light off. It now
  falls back to the day mode's maximum brightness, so an explicit "on" always
  turns the light on.

## [1.19.0] - 2026-10-16

### Changed - One hold concept, per light
- The three override mechanisms (`manual_control`, `scene_blocker`, `keep_on`)
  are merged into a single per-light hold: `held_lights` now maps each light
  to the reason it is held — `detected` (a foreign intervention) or `service`
  (a `turn_on`/`turn_off` with `hold: true`). A hold lives until the release
  button/service or a mode change; there is no timer and no stability
  take-over.
- External-control detection writes per light into the hold state instead of
  flipping a room-wide manual-control switch.
- During a sleep/wake-up ramp detection is on/off-only: a foreign OFF ends the
  whole ramp and jumps into the dark block, exactly like a wall button
  `turn_off` with `hold: true`. `turn_off` with `hold: false` still only
  switches the light and lets the ramp run.
- New `daynight_lighting.hold_all` service as the bulk replacement for the
  removed manual-control switch.
- In a safety room (the "Force defaults" switch, formerly "Block wall
  buttons") a hold is ignored: the handlers enforce the configured defaults
  even on held lights.

### Breaking
- The "Manual control" switch entity is gone, together with its timer, the
  `detected_override` attribute, the stability take-over and the
  `manual_control_timeout_min` / `take_over_after_stability_min` options. Use
  `hold_all` and the release-hold button/service instead.
- The scene blocker (`light_scene_blocker`) option and its boolean entity are
  gone; a held light is protected the same way.
- The `keep_on` state and the `keep_on_in_night_mode` service parameter are
  gone; `hold: true` replaces their protection.

## [1.18.0] - 2026-10-16

### Added - `hold` flag on turn_on / turn_off
- `daynight_lighting.turn_on` and `turn_off` gain a `hold` field, defaulting
  to `false`. Without it a system automation only switches the lights and the
  day/night automation keeps managing them. Set `hold: true` for a visitor
  interaction (a wall button) to hold the lights until the phase ends and
  protect them from the night motion-off timer — the previous, now explicit,
  behaviour.

## [1.17.1] - 2026-10-16

### Fixed - Dimming now reaches the lights at once
- Moving the brightness dial (a wall-button press or the slider) re-applied
  the night brightness only while motion was present; a held-on light with
  motion cleared, or a night room without a motion sensor, showed the new
  value in the UI but left the lamps unchanged until they were switched off
  and on again. The dial now re-dims every light that is already on
  immediately — off lights stay off, and the blockers (manual control, scene
  blocker) still guard the change.

## [1.17.0] - 2026-10-15

### Added - A reset-brightness button for the wall-button dials
- Button `button.<name>_daynight_lighting_reset_brightness` to undo a dim
  press: a dim moves the night (or fixed-day) brightness dial without
  creating a hold, so the release-hold button had nothing to reset. This
  button drops the dialled-in value back to the configured brightness and
  re-applies the current mode. It is disabled while no dial is dialled in,
  and only the current phase's dial is touched.

## [1.16.2] - 2026-10-15

### Fixed - Releasing a hold in a motion-lit night now turns the light off
- `release_hold` with no motion present left a held-on light on forever: the
  night motion-off timer had already fired and skipped the held light, so
  there was no pending timer left to switch it off once the hold was gone.
  Releasing the hold now applies the configured "off with nobody present"
  state immediately, reusing the off timer's own selection (manual control,
  scene blocker and current motion still guard it).

## [1.16.1] - 2026-10-15

### Fixed - Holds now stay consistent between the UI and the motion timer
- Dimming after `turn_on` released the "On hold" flag but left the
  `keep_on_in_night_mode` protection behind, so the light no longer *looked*
  held while the night motion-off timer kept skipping it — it stayed on even
  though motion had cleared. Releasing a hold (dimming, `release_hold`, or a
  mode transition) now drops both halves together, so the light returns fully
  to the automation.
- A visitor's quick `turn_on` → `turn_off` → `turn_on` could leave the light
  off despite the hold: `turn_on` recorded its hold only *after* the light
  call, so a pending night motion-off timer could fire in between and switch
  it straight back off. The hold (and the off-timer cancel) now happen before
  the light switches. Entering night with "turn off on enter" also no longer
  turns off lights a visitor explicitly held on.

## [1.16.0] - 2026-10-15

### Added - Hold status and a release button
- Binary sensor `binary_sensor.<name>_daynight_lighting_on_hold`, ON while a
  `turn_on`/`turn_off` holds the lights. It is pushed through the monitor
  signal, so a dashboard or automation can see the visitor override live.
- Button `button.<name>_daynight_lighting_release_hold` to drop the hold and
  restore the configured state from the UI. It is disabled while nothing is
  held. Same effect as the `release_hold` service.

## [1.15.2] - 2026-10-15

### Changed
- `release_hold` now restores the configured state instead of just re-applying
  the mode: it resets the brightness dials to their configured starting
  points before the mode runs, so a visitor's dimmed value does not survive a
  hold release. The room returns to the configured defaults, exactly like
  entering the phase does.

## [1.15.1] - 2026-10-15

### Fixed
- A dim press after `turn_off` was swallowed by the hold: switching a light
  off holds it off, and the day/night handlers skipped it, so `adjust_brightness`
  moved the dial but never reached the light. A dim press is a visitor action
  like on/off, so it now releases the hold before applying the step — dimming
  works again right after switching off.

## [1.15.0] - 2026-10-15

### Added - Visitor control, a night floor and a safety lock
- **Phase-bound hold** set by `turn_on`/`turn_off`. A visitor's wall-button
  press reaches us as those services; the lights are now held in place until
  the phase (day/night) ends, so the automation does not immediately undo the
  visitor's choice. The hold is respected by day, night, sleep and wake-up
  alike, clears automatically on a mode transition, and can be dropped early
  with the new `daynight_lighting.release_hold` service.
- **"Block wall buttons" switch** per instance
  (`switch.<name>_daynight_lighting_block_wall_buttons`, default off). For a
  motion-lit room like a staircase: when on at night, our services
  (`turn_on`, `turn_off`, `adjust_brightness`) are ignored so motion alone
  decides and a visitor cannot switch the room off or dim it into darkness.
  It is a pure input gate — it never touches manual control, scene blockers
  or the dials.
- **Night-with-motion floor of 5 %**. With a motion sensor the night dial
  stops at 5 %, guaranteeing a nightlight; without one it keeps the 10 %
  button floor. A deliberately lower configuration still wins.

### Changed - Day brightness becomes an absolute dial
- The day brightness *offset* is replaced by an absolute **day brightness**
  dial (`number.<name>_daynight_lighting_day_brightness`, 0–100 %), used for
  the *fixed* day fallback without a LUX sensor. It starts from the configured
  fixed brightness, resets on entering day mode and on an options change, and
  is restored across restarts — mirroring the night dial.
- `adjust_brightness` routing: day with a LUX sensor ignores the press (the
  curve keeps regulating); day *fixed* moves the day dial; day *skip* steps
  the lights; day *circadian only* or *off* is ignored.

### Breaking
- The `…_day_brightness_offset` entity is gone, replaced by
  `…_day_brightness`. Existing automations referencing the offset entity must
  be updated.

## [1.14.2] - 2026-09-27

### Fixed
- Area discovery really skips Hue rooms, zones and groups now. The 1.14.1
  filter keyed on a missing device, but Hue group entities carry a device
  entry just like real bulbs, so they were still picked up. The reliable
  signal is the entity registry `translation_key`: `hue_grouped_light` for a
  group, `hue_light` for a bulb. The filter now skips any translation key
  ending in `_grouped_light` (and still native `group` platforms).

## [1.14.1] - 2026-09-27

### Fixed
- "Leave empty for all area lights" now actually works. With area discovery
  and no `included_lights` chosen, the instance resolves every real
  (non-group) light in the area instead of controlling nothing.

## [1.14.0] - 2026-09-26

### Added - Dimming during the day
- Day brightness offset per instance
  (`number.daynight_lighting_<instance>_day_brightness_offset`, −100…+100 %).
  It shifts the day brightness while day mode keeps regulating: with a LUX
  sensor the curve moves, without one the fixed brightness does. It is added
  after the weather modifier, may brighten past the configured day maximum
  like the night dial, and stops at the 10 % floor when dimming.
- `adjust_brightness` in day mode with a LUX sensor now moves the offset
  instead of ignoring the press. Where the curve switches the lights off in a
  bright room the press is still ignored: an offset never switches a light on.
- Service `daynight_lighting.reset_day_brightness`. The offset also resets
  when day mode begins and on an options change, and it is restored across
  restarts.

### Changed
- The fixed day fallback is dimmed through the same offset. Before, the
  dialled-in value lived in the day handler, invisible and lost on restart.

## [1.13.1] - 2026-09-26

### Fixed
- A detected override survives a restart and an options change. It used to
  be a flag on the main switch that both reset, so afterwards the stability
  take-over never ran and manual control stayed on for good. The flag now
  lives with the Manual control switch and is restored with its state
  (attribute `detected_override`); a restored detected override still has no
  timer and still ends on stability.
- Ending manual control applies what the next tick would apply. Inside a
  sleep or wake-up ramp that is the ramp, during a service-started sleep or
  wake-up it is that mode, and in the dark block after a sleep it is nothing.
  Before, the release put day or night values into the ramp until the next
  tick restarted it. The scene blocker going off and the brightness dials
  follow the same rule.
- Weather option changes took effect only after a restart. The weather
  reader was built once at startup and never rebuilt.

### Changed
- One place wires the object graph: the main switch builds its collaborators
  lazily and rebuilds them on an options change. The separate startup
  factory, whose objects were replaced at the first options change anyway,
  is gone.
- The brightness formulas that actually run live in `domain/brightness.py`
  (LUX curve, weather modifier, ramp). The unused strategy layer and the
  domain functions that differed from the handlers' arithmetic are removed.
  The results are unchanged to the percent.
- The Manual control, Control Brightness and Control Color switches moved
  to `control_switches.py`. Entity IDs, names and unique IDs are unchanged.
- Entities find each other through `instance_data.py` and read each other's
  public state only.
- The deprecated `mode_handlers.py` re-export is removed; import from
  `handlers`.

### Documentation
- README: motion at night respects manual control and the scene blocker;
  detection is event-driven against persisted expected states; defaults for
  circadian colour (on) and night start (at configured time) match the code.

## [1.13.0] - 2026-09-26

### Changed
- **Manual control is now only ever set from outside.** It means one thing:
  somebody outside the integration has been at these lights. You switching
  it on and the detection seeing foreign values are the only two ways in.
  The integration's own services no longer set it, because stepping aside
  from ourselves makes no sense. An automation that wants the room announces
  itself with the scene blocker instead.
- `adjust_brightness` decides by one rule: a step is applied to the lights
  where nothing here controls their brightness, it moves the target where we
  aim at a fixed value, and it is ignored where neither is possible. The
  decision moved into the instance, which is the only object that knows its
  mode, its sensors and its configuration; the service resolves and logs.
- `turn_on` with an explicit brightness or colour records those values as
  ours instead of switching manual control on. They now hold until the mode
  recomputes; use the scene blocker to make them stand.

### Added
- With the scene blocker on, a wall button dims in **every** mode, including
  day with a LUX sensor. The blocker stops every handler, the transition, the
  detection and the take-over, so there is nothing left to overwrite a step.
  This is the way to hold a value during the day.
- Day mode without a LUX sensor can be dimmed by a button. With fallback
  *skip* or *circadian only* the step is simply applied, since day mode sets
  no brightness there. With *fixed* the fixed brightness itself moves and
  resets at the start of the next day, mirroring the night dial. Both the
  applied value and the value the detection checks against read the same
  accessor, so our own dimming cannot be reported as external control.
- The scene blocker going off now hands control back at once: the memory of
  our own commands is dropped and the current mode is applied. Without this
  a day–night change during an episode reached the lights only on the next
  event that happened to apply something — at night with a motion sensor,
  possibly hours later.

### Fixed
- A step now goes through the same applier every mode handler uses, so the
  values are recorded as ours. Sent any other way, the detection would read
  our own button press back as an outside intervention.

## [1.12.1] - 2026-09-26

### Fixed
- The Mode sensor kept showing the mode the instance had just left. The
  sensors are pushed during the mode change, but the new mode was recorded
  only afterwards, so they re-read the old one. In a day room the next
  brightness apply papered over it within a minute; in a night room with a
  motion sensor nothing else notifies the sensors until a light is actually
  switched, so the wrong mode stood until somebody walked past.

## [1.12.0] - 2026-09-26

### Fixed
- Lights could stay at a foreign brightness after manual control ended. Day
  mode damps a new brightness against the last one *it* sent, and that
  reference is stale once somebody else has been at a lamp. On a bright day
  the LUX-derived target barely moves, so every tick decided it was already
  at its target — permanently, and most likely in a calibrated room, where
  calibration makes the reading independent of our own lamps. Every release
  of manual control now forgets what was commanded. The flapping freeze is
  deliberately kept: a room that was oscillating still is.
- The auto-reset timeout no longer just flips the switch. It goes through the
  same release as everything else, so the mode's values are applied at once
  instead of at the next tick.
- A leftover auto-reset timer could end a later manual control episode early.
  Every transition now either starts or cancels the timer.

### Changed
- The manual control state has one owner. `async_set_manual_control()` on the
  switch entity is the only place it changes; the main switch asks instead of
  writing the entity's attribute. All three ways in and all three ways out run
  the same side effects, which is what made the two bugs above possible.
- An externally *detected* override still gets no timeout on purpose — it ends
  on stability, not on a clock. That intent is now explicit in the call
  (`start_timer=False`) rather than an accident of which code path was used.
- Mode handlers gained `forget_applied_values()`. Day mode drops its damping
  reference and its last colour; night, sleep and wake-up have nothing to
  forget and say so.

### Documentation
- `docs/FLOW.md` now shows all six exits of manual control converging on one
  release, and explains why forgetting is part of it.
- README: the timeout's actual scope, and a pitfall entry for the stuck
  brightness.

## [1.11.2] - 2026-09-26

### Documentation
- New `docs/FLOW.md` with six diagrams: which mode is running, what the tick
  does in which order, who may touch the lights, what a button press does in
  each mode, how manual control ends, and how night mode reacts to motion.
- The README lists the entities and services that arrived in 1.9.0 to 1.11.0:
  the night brightness dial, the four monitoring sensors, `adjust_brightness`
  and `reset_night_brightness`.
- New pitfall entry for the most likely surprise — a wall button that does
  nothing during the day in a room with a LUX sensor.

## [1.11.1] - 2026-09-26

### Fixed
- A button press was still switching lights in day mode in rooms whose LUX
  sensors come from area discovery. The check looked into the config entry,
  where only a manually added *additional light sensor* ever appears. It now
  asks the running instance, which is the only place that knows about
  discovered sensors.

## [1.11.0] - 2026-09-26

### Changed
- `adjust_brightness` now decides by mode what a button press can mean.
  Night moves the dial. Day with a LUX sensor ignores the press, because a
  closed loop regulates a step away within a tick or two and holding it would
  mean stopping the regulation for half an hour. Day without a LUX sensor
  steps the lights and switches manual control on, as before. Sleep and
  wake-up are left alone; their ramps recompute on every tick.
- Dimming now stops at 10 % everywhere, on the dial and on stepped lights
  alike. A staircase must not be dimmable into darkness. A configured night
  brightness below the floor is a deliberate decision and still wins.
- Stepped lights are no longer dimmed with `brightness_step_pct`, which walks
  past zero and switches a light off. The target is computed per light and
  clamped, and an off light stays off when dimming.

## [1.10.1] - 2026-09-26

### Fixed
- Changing the night brightness in the configuration dialog had no visible
  effect while a value was dialled in. The configured value is the baseline,
  so saving options now drops the dial and publishes the new value. The
  reverse direction stays deliberately absent: writing options rebuilds the
  instance and would kill running ramps.
- The dial no longer polls; it publishes its state on every change.

## [1.10.0] - 2026-09-26

### Added - Dimming at night
- Night brightness dial per instance
  (`number.daynight_lighting_<instance>_night_brightness`). Night mode runs
  open loop, so its target can be shifted while motion, colour, the off timer
  and the sleep and wake-up ramps keep working — and without manual control
  switching on.
- Service `daynight_lighting.adjust_brightness` with a `step`, meant for wall
  buttons. In night mode it moves the dial; in every other mode brightness is
  LUX-regulated and cannot be held, so it steps the lights and hands over to
  manual control as before.
- Service `daynight_lighting.reset_night_brightness` and an automatic reset
  when night mode is entered, so each night starts from the configured value.
- Documentation in `docs/NIGHT_BRIGHTNESS.md`. The configured night
  brightness is now the starting point rather than the only value.

### Fixed
- The monitoring sensors added in 1.9.0 stayed unknown until the first
  options change: the production object graph is built in `factory.py`, which
  did not pass the observer through. Target brightness and colour temperature
  now report from startup.
- `_light_matches_night_values` compared a light against the configured night
  brightness. With a dialled-in value that made a dimmed light look foreign
  and aborted the motion turn-on for the whole room.

## [1.9.0] - 2026-09-21

### Added - Monitoring
- Four sensors per instance: current mode, target brightness, target colour
  temperature and ramp progress. They make the history, the logbook and
  long-term statistics work for what used to live only in debug logs.
- Event `daynight_lighting_mode_changed` on every mode change, carrying
  `entry_id`, `instance`, `area_id`, `from_mode` and `to_mode`.
- Documentation in `docs/MONITORING.md` and a ready-made dashboard view in
  `docs/day_night_monitoring.yaml`.

### Fixed
- Reading wake-up progress no longer ends a running service-triggered ramp.
  The tick owns that lifecycle now, so nothing that merely observes the
  instance can change how it behaves.
- Unloading a config entry now unloads every platform instead of only the
  switch platform.

## [1.6.3] - 2025-02-17

### Changed - Sensorless Mode Only
- **Wake-up Mode Intelligent Target Brightness**: Wake-up in sensorless mode now uses intelligent target based on wake-up end time
- **During wake-up runtime**: Ramps to appropriate target brightness
  - If wake-up ends during DAY (after sunrise) → Ramps to `day_max_brightness`
  - If wake-up ends during NIGHT (before sunrise) → Ramps to `night_brightness`
- **After wake-up completes**: No special action, normal day/night mode continues
- Simpler and more predictable behavior than post-run fallback approach

### Added
- Intelligent target brightness selection in `_apply_wakeup_mode()` for sensorless mode
- Day/night context detection using `schedule.is_day_mode()` to determine target
- `_handle_wakeup_to_night()` transition handler for wake-up ending before sunrise

### Technical Details
- Wake-up with LUX sensor: unchanged (ramps to LUX-based brightness)
- Wake-up without LUX sensor: ramps to day_max_brightness or night_brightness based on end time
- Context determined during wake-up runtime, not at end (usually same for short durations)
- Backward compatible for configurations with LUX sensors
- Removed post-fallback logic (simpler implementation)

## [1.6.2] - 2025-02-17

### Changed
- **Wake-up Mode Context-Aware Sensorless**: Wake-up now automatically uses day or night mode UI options based on context
- Wake-up during day context uses "Day mode without LUX sensor" fallback options (skip, fixed, circadian_only, off)
- Wake-up during night context uses "Night mode without motion sensor" fallback options (skip, on, keep, off)
- Context detection is independent of wake-up mode itself (uses schedule's day/night determination)

### Added
- 7 new unit tests for night context wake-up behavior (16 total sensorless tests)
- Context-aware sensorless documentation in README.md with examples
- `is_day_context` parameter to `_apply_wakeup_mode_fallback()` method

## [1.6.1] - 2025-02-17

### Changed
- **Wake-up Mode Sensorless Support**: Wake-up service now respects "Day mode without LUX sensor" configuration
- Service-triggered wake-up follows user-selected fallback behavior: skip, fixed brightness, circadian only, or off
- Behavior is backward compatible (default: skip, which does nothing in sensorless mode)

### Added
- Comprehensive sensorless mode documentation for wake-up service in README.md
- Wake-up now supports all day_mode_fallback options: skip, fixed, circadian_only, off

## [1.6.0] - 2025-02-17

### Added
- **Immediate Start Services**: Two new services to trigger Sleep/Wake-up modes immediately, bypassing schedule
- `daynight_lighting.start_sleep_mode` - Immediately starts Sleep Mode regardless of schedule
- `daynight_lighting.start_wakeup_mode` - Immediately starts Wake-up Mode regardless of schedule
- Service-triggered modes follow priority order: Sleep > Wake-up > Day/Night
- Service-triggered wake-up uses actual start time for deterministic progress calculation
- Comprehensive service documentation in README.md with automation examples

### Changed
- Wake-up Mode progress calculation now supports both scheduled and service-triggered modes
- Manual override now clears service-triggered wake-up state (consistent with sleep behavior)

## [1.5.0] - 2025-02-16

### Changed
- **Wake-up Mode 2.0**: Wake-up is now an independent override mode, evaluated before day/night determination
- Wake-up Mode now activates during its configured time window regardless of sunrise or day mode state
- Priority order updated: Sleep Mode 2.0 → Wake-up Mode 2.0 → Day/Night Mode
- Wake-up Mode no longer requires "night hours" to activate

### Added
- Wake-up Mode 2.0 independence: works correctly when sunrise occurs during wake-up window
- Support for wake-up with `night_mode_start: sun_below_horizon` configuration
- 12 new comprehensive unit tests for Wake-up Mode 2.0 behavior (570 total tests)

### Fixed
- Wake-up Mode now activates correctly with early summer sunrises
- Wake-up Mode with sun-based night mode no longer skips wake-up when sun rises mid-window
- Wake-up Mode handles midnight crossing correctly in all scenarios

## [1.4.0] - 2025-02-16

### Changed - BREAKING
- **Sleep Mode 2.0 Redesign**: Sleep is now an independent "go to bed" override mode, not a transition to night
- Sleep always ends by turning lights OFF (no longer stays at target brightness)
- Post-sleep block prevents light control until manual override, motion event, or day mode starts
- `sleep_duration_min` is now REQUIRED (no implicit duration fallback to night_start_time)
- Inverted configurations (`sleep_start > night_start`) without explicit duration are NOT ALLOWED
- Emergency fallback: If duration missing, uses 60 minutes and logs ERROR

### Added
- Sleep block mechanism: prevents any light control after sleep ends until explicitly cleared
- Sleep block clearing: manual override, motion detection (night mode), or day mode start
- Validation: ERROR logged for inverted configs without duration
- Validation: INFO logged for inverted configs WITH duration (allowed)
- 9 new unit tests for Sleep Mode 2.0 behavior (558 total tests)

### Fixed
- Sleep mode now deterministic: based on actual start time, not clock-based time windows
- Sleep progression tracked from when sleep actually started (not configured time window)
- Manual override during sleep or sleep block correctly clears all sleep state

## [1.3.0] - 2025-02-16

### Added
- Optional `sleep_duration_min` slider (15-240 minutes) for explicit sleep mode duration
- Validation logging for sleep duration edge cases (short/long durations)
- Sleep/wake-up overlap warning (informational, non-blocking)
- 11 comprehensive unit tests for sleep duration functionality (549 total tests)

### Fixed
- Sleep mode activation now independent of night mode state (fixes inverted configurations where `night_mode_start_time < sleep_start_time`)
- Sleep mode now correctly handles midnight wrap-around scenarios

### Improved
- Midnight wrap-around handling for sleep mode duration calculations
- Sleep end time calculation now decoupled from night mode start time
- Backward compatibility: existing configs without `sleep_duration_min` continue to work using implicit duration (sleep_start → night_start)

## [1.2.2] - Previous Release

Previous features and fixes (see git history).
