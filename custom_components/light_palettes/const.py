"""Constants for Light Palettes."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "light_palettes"

SUBENTRY_PALETTE: Final = "palette"
SUBENTRY_EFFECT: Final = "effect"

# Palette subentry data
CONF_COLORS: Final = "colors"
CONF_COLOR_COUNT: Final = "color_count"
MIN_COLORS: Final = 2
MAX_COLORS: Final = 8

# Effect subentry data
CONF_LIGHTS: Final = "lights"
CONF_PALETTE: Final = "palette"
CONF_STEP: Final = "step"
CONF_JITTER: Final = "jitter"
CONF_STAGGER: Final = "stagger"

DEFAULT_STEP: Final = 60
MIN_STEP: Final = 2
MAX_STEP: Final = 3600
DEFAULT_JITTER: Final = 0
MAX_JITTER: Final = 50

# Entry options
CONF_TOPIC_OVERRIDES: Final = "topic_overrides"
CONF_SOFT_FADE_INTERVAL: Final = "soft_fade_interval"
DEFAULT_SOFT_FADE_INTERVAL: Final = 2.0

# OpenBeken
OBK_FAST_LERP: Final = 10000
OBK_SMOOTH_TRANSITIONS_FLAG: Final = 18

# Shortest fade we'll ever schedule, whatever the randomness rolls.
MIN_FADE_SECONDS: Final = 1.0

SIGNAL_EFFECT_UPDATED: Final = f"{DOMAIN}_effect_updated_{{}}"

# Palettes created with a fresh install so there's something to try right away.
STARTER_PALETTES: Final = {
    "Sunset": [[255, 48, 0], [255, 0, 96], [120, 0, 255]],
    "Ocean": [[0, 80, 255], [0, 200, 180], [0, 255, 90]],
    "Aurora": [[0, 255, 120], [0, 120, 255], [180, 0, 255]],
    "Embers": [[255, 20, 0], [255, 90, 0], [255, 40, 10]],
}
