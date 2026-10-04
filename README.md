# Light Palettes

Slow, smooth colour-palette effects for Home Assistant lights. Create palettes,
create effects that play a palette on a set of lights, and switch them on from
any dashboard.

It was built for **OpenBeken** bulbs, which can fade on the bulb itself. The
integration sends one MQTT message per fade, so even minute-long fades are
perfectly smooth and don't flood your network. Other colour lights work too,
using Home Assistant's `transition`, or a gentle software fade if a light
doesn't support transitions.

## Features

- **Palettes** with 2–8 colours, picked with colour wheels. Edit forms open with
  the current colours filled in.
- **Effects**: a name, a set of lights (bulbs and light groups), a palette and
  the timing. Make as many as you like, e.g. one per room.
- Each effect gets its own device with:
  - an on/off **switch**
  - a **palette** dropdown (its attributes include the colours, for dashboard previews)
  - **seconds per colour** and **timing randomness** controls
- **Per-light randomness**: every bulb runs its own loop and varies each fade by
  up to ± the set percentage, so the lights drift out of step and the room
  ripples through the palette instead of changing all at once.
- **Spread across the palette**: optionally start each light on a different colour.
- Plays nicely with normal use:
  - Switch a bulb off and it leaves the effect right away; switch it back on and it rejoins.
  - When the last bulb of an effect goes off, the effect switches itself off.
  - A light can only follow one running effect. Starting another effect that
    uses it takes it over, and an effect that loses all its lights stops.
  - Changing the palette or timing while an effect runs applies immediately and
    fades from wherever the lights are.
  - Running effects resume after a Home Assistant restart, on the lights that are on.

## Installation

### HACS

1. HACS -> ⋮ -> **Custom repositories** -> add this repository's URL with type **Integration**.
2. Install **Light Palettes** and restart Home Assistant.
3. **Settings -> Devices & services -> Add integration -> Light Palettes.**

### Manual

Copy `custom_components/light_palettes` into your `config/custom_components/`
folder and restart Home Assistant.

Requires Home Assistant 2026.2 or newer.

## Usage

On the integration's page (**Settings -> Devices & services -> Light Palettes**):

- **Add palette**: name and number of colours, then pick the colours.
- **Add effect**: name, lights, palette, seconds per colour, randomness and spread.
- Use the ⋮ menu next to any palette or effect to **edit** or **delete** it.

Then switch the effect on from its device page or a dashboard.

### Dashboard example

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: switch.living_room
  - type: tile
    entity: select.living_room_palette
    features:
      - type: select-options
  - type: markdown
    content: >
      {% for c in state_attr('select.living_room_palette', 'colors') or [] %}<font color="{{ c }}">⬤</font> {% endfor %}
  - type: entities
    entities:
      - number.living_room_seconds_per_colour
      - number.living_room_timing_randomness
```

## OpenBeken bulbs

OpenBeken bulbs connected to Home Assistant through MQTT discovery are detected
automatically. Their MQTT topic is taken from the device name, which OpenBeken
sets to its short name, and that is also its MQTT client topic unless you've
changed it.

The integration turns on OpenBeken's smooth-transition flag (flag 18) by itself.
That only writes to flash if the flag was off. While a fade runs the bulb's
interpolation speed is slowed down; when the bulb leaves the effect it is set
back to instant, typically within a fraction of a second of the bulb being
switched off.

Optional: to make off-commands instant even during a fade, add this line to the
bulb's `autoexec.bat` (Web Application -> LittleFS):

```
addEventHandler LEDState 0 led_lerpSpeed 10000
```

### Topic overrides

If a bulb isn't detected, or its MQTT client topic differs from its short name,
add a line to **Configure** on the integration page:

```
light.desk_lamp=obk_desk
```

This also forces any light to be treated as an OpenBeken bulb.

## Other lights

Any light with a colour mode can be used. Lights that support `transition`
(most Zigbee lights, Hue, WLED, etc.) fade natively. Others get a software fade
made of small colour steps, every 2 seconds by default (adjustable under
**Configure**). Prefer short step intervals only for local lights; cloud-based
lights may rate-limit you.

Lights without colour (white-only or on/off) are skipped and listed in the
effect switch's `skipped_lights` attribute.

## How fades are timed

For each fade, a light picks its duration as _seconds per colour_ ± a random
amount up to _timing randomness_. OpenBeken bulbs get an interpolation speed of
`255 / duration` units per second, so even a full swing on one colour channel
finishes just as the next fade starts and the light never stops moving.

## Development

```bash
pip install -r requirements_test.txt
python -m pytest
```

## License

MIT
