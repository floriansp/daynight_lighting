# Debug logging for DayNight Lighting

## Via configuration.yaml (recommended)

Like [HACS and other integrations](https://www.hacs.xyz/docs/use/troubleshooting/logs/), the most reliable way to get full debug logs (including startup) is via `configuration.yaml`. The UI "Enable debug logging" option may not show this integration or capture logs from early startup.

Add or extend the `logger` section:

```yaml
logger:
  default: info
  logs:
    custom_components.daynight_lighting: debug
```

Then **restart Home Assistant**. Remove the entry when you're done troubleshooting.

## Via Home Assistant UI (optional)

If the integration appears in the logging list (the integration registers its logger in `manifest.json`):

1. **Settings** → **System** → **Logging** (or **Developer tools** → **Logging**).
2. Find **DayNight Lighting** or **custom_components.daynight_lighting**.
3. Set the level to **Debug**.

This may not include startup logs; use the YAML method above for full coverage.

## Viewing logs

- **SSH / Terminal (Home Assistant OS):** `ha core logs` — streams the core log.
- **Settings** → **System** → **Logs**, or **Developer Tools** → **Logs**

*Note: The file `config/home-assistant.log` was removed in Home Assistant 2025.11; use the UI or `ha core logs` instead.*

## What to search for

Every message is prefixed with the instance name in square brackets, e.g.
`[Kitchen]`. Search for the parts you care about:

| Topic | Message fragments |
| --- | --- |
| Mode changes | `Mode transition:`, `Tick: mode=` |
| Day (LUX) | `Day: lux=`, `Day: circadian`, `Day: fallback=` |
| Night / motion | `Night motion ON:`, `Night motion OFF:`, `Night off timer:` |
| Sleep | `Sleep Mode: Started`, `Sleep Mode: Block`, `Sleep Mode: Duration complete` |
| Wake-up | `Wake-up Mode: Started`, `Wake-up: progress=` |
| External control | `External control:`, `External control detected` |
| Holds | `all lights held, skipping`, `holds released`, `lights held`, `Release hold pressed` |
| Transitions | `expects lights ON after transition`, `expects lights OFF after transition` |
| Area discovery | `Area discovery:`, `Area entities changed`, `Subscribed to` |

The most common case is night behaviour: `Night motion ON:` / `Night motion
OFF:` show each movement and the off timer, and `all lights held, skipping`
shows when a visitor's hold is keeping the automation from touching a room.
