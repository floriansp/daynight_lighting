# DayNight Lighting

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Automatic light control for Home Assistant, driven by the time of day.

- **Day mode** reads an illuminance (LUX) sensor and sets brightness dynamically,
  with optional circadian colour temperature that follows the sun.
- **Night mode** uses motion/presence to switch lights on and off.
- **Sensorless** fallbacks for rooms without a LUX or motion sensor.
- **Sleep** and **wake-up** modes for gradual dimming/brightening.
- Per-light **holds** that step aside when a scene, wall button or another
  automation takes over.

## Installation

Add this repository as a custom integration in
[HACS](https://hacs.xyz), install **DayNight Lighting**, and restart Home
Assistant. Then add the integration via **Settings → Devices & Services → Add
Integration** and create one instance per room/area.

Full documentation: [README](https://github.com/floriansp/daynight_lighting#readme).
