"""Config flow for Light Palettes.

One config entry holds everything. Palettes and effects are config subentries,
added and edited from the integration page; their edit forms open pre-filled.
"""

from __future__ import annotations

import colorsys
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_COLOR_COUNT,
    CONF_COLORS,
    CONF_JITTER,
    CONF_LIGHTS,
    CONF_PALETTE,
    CONF_SOFT_FADE_INTERVAL,
    CONF_STAGGER,
    CONF_STEP,
    CONF_TOPIC_OVERRIDES,
    DEFAULT_JITTER,
    DEFAULT_SOFT_FADE_INTERVAL,
    DEFAULT_STEP,
    DOMAIN,
    MAX_COLORS,
    MAX_JITTER,
    MAX_STEP,
    MIN_COLORS,
    MIN_STEP,
    STARTER_PALETTES,
    SUBENTRY_EFFECT,
    SUBENTRY_PALETTE,
)
from .engine import parse_topic_overrides

CONF_STARTER_PALETTES = "starter_palettes"


def _color_key(index: int) -> str:
    return f"color_{index + 1}"


def _default_color(index: int, count: int) -> list[int]:
    """Spread new colours evenly round the hue wheel."""
    r, g, b = colorsys.hsv_to_rgb(index / max(count, 1), 1.0, 1.0)
    return [round(r * 255), round(g * 255), round(b * 255)]


def _titles(entry: ConfigEntry, subentry_type: str, exclude: str | None = None) -> set[str]:
    return {
        sub.title.casefold()
        for sub in entry.subentries.values()
        if sub.subentry_type == subentry_type and sub.subentry_id != exclude
    }


class LightPalettesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the integration itself."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            subentries: list[ConfigSubentryData] = []
            if user_input.get(CONF_STARTER_PALETTES, True):
                subentries = [
                    ConfigSubentryData(
                        data={CONF_COLORS: colors},
                        subentry_type=SUBENTRY_PALETTE,
                        title=name,
                        unique_id=None,
                    )
                    for name, colors in STARTER_PALETTES.items()
                ]
            return self.async_create_entry(title="Light Palettes", data={}, subentries=subentries)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_STARTER_PALETTES, default=True): BooleanSelector()}
            ),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_PALETTE: PaletteSubentryFlow,
            SUBENTRY_EFFECT: EffectSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LightPalettesOptionsFlow()


class LightPalettesOptionsFlow(OptionsFlow):
    """Integration-wide options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = user_input.get(CONF_TOPIC_OVERRIDES, "") or ""
            _, bad_lines = parse_topic_overrides(raw)
            if bad_lines:
                errors[CONF_TOPIC_OVERRIDES] = "bad_override"
            else:
                return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(CONF_TOPIC_OVERRIDES): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
                vol.Required(
                    CONF_SOFT_FADE_INTERVAL, default=DEFAULT_SOFT_FADE_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.5,
                        max=10,
                        step=0.5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self.config_entry.options
            ),
            errors=errors,
        )


class PaletteSubentryFlow(ConfigSubentryFlow):
    """Add or edit a palette: name and colour count first, then the colours."""

    def __init__(self) -> None:
        self._name: str = ""
        self._count: int = 3
        self._colors: list[list[int]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_details()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._name = sub.title
        self._colors = [list(c) for c in sub.data.get(CONF_COLORS, [])]
        self._count = max(MIN_COLORS, min(MAX_COLORS, len(self._colors)))
        return await self.async_step_details()

    @property
    def _editing(self) -> ConfigSubentry | None:
        return self._get_reconfigure_subentry() if self.source == "reconfigure" else None

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            editing = self._editing
            taken = _titles(
                self._get_entry(),
                SUBENTRY_PALETTE,
                exclude=editing.subentry_id if editing else None,
            )
            if not name:
                errors[CONF_NAME] = "name_required"
            elif name.casefold() in taken:
                errors[CONF_NAME] = "name_taken"
            else:
                self._name = name
                self._count = int(user_input[CONF_COLOR_COUNT])
                return await self.async_step_colors()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_COLOR_COUNT): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_COLORS, max=MAX_COLORS, step=1, mode=NumberSelectorMode.SLIDER
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="details",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input or {CONF_NAME: self._name, CONF_COLOR_COUNT: self._count},
            ),
            errors=errors,
        )

    async def async_step_colors(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            colors = [[int(v) for v in user_input[_color_key(i)]] for i in range(self._count)]
            data = {CONF_COLORS: colors}
            if editing := self._editing:
                return self.async_update_and_abort(
                    self._get_entry(), editing, title=self._name, data=data
                )
            return self.async_create_entry(title=self._name, data=data)

        suggested = {
            _color_key(i): (
                self._colors[i] if i < len(self._colors) else _default_color(i, self._count)
            )
            for i in range(self._count)
        }
        schema = vol.Schema(
            {vol.Required(_color_key(i)): ColorRGBSelector() for i in range(self._count)}
        )
        return self.async_show_form(
            step_id="colors",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders={"name": self._name},
        )


class EffectSubentryFlow(ConfigSubentryFlow):
    """Add or edit an effect: which lights, which palette, timing."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_effect(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self.async_step_effect(user_input)

    async def async_step_effect(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        palettes = [
            sub for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_PALETTE
        ]
        if not palettes:
            return self.async_abort(reason="no_palettes")

        editing = self._get_reconfigure_subentry() if self.source == "reconfigure" else None
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            lights = user_input.get(CONF_LIGHTS) or []
            if not name:
                errors[CONF_NAME] = "name_required"
            elif name.casefold() in _titles(
                entry, SUBENTRY_EFFECT, exclude=editing.subentry_id if editing else None
            ):
                errors[CONF_NAME] = "name_taken"
            elif not lights:
                errors[CONF_LIGHTS] = "no_lights"
            else:
                data = {
                    CONF_LIGHTS: list(lights),
                    CONF_PALETTE: user_input[CONF_PALETTE],
                    CONF_STEP: int(user_input[CONF_STEP]),
                    CONF_JITTER: int(user_input[CONF_JITTER]),
                    CONF_STAGGER: bool(user_input[CONF_STAGGER]),
                }
                if editing:
                    return self.async_update_and_abort(entry, editing, title=name, data=data)
                return self.async_create_entry(title=name, data=data)

        current: dict[str, Any]
        if user_input is not None:
            current = user_input
        elif editing:
            current = {CONF_NAME: editing.title, **editing.data}
        else:
            current = {
                CONF_PALETTE: palettes[0].subentry_id,
                CONF_STEP: DEFAULT_STEP,
                CONF_JITTER: DEFAULT_JITTER,
                CONF_STAGGER: False,
            }

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_LIGHTS): EntitySelector(
                    EntitySelectorConfig(domain="light", multiple=True)
                ),
                vol.Required(CONF_PALETTE): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=sub.subentry_id, label=sub.title)
                            for sub in palettes
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_STEP): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STEP,
                        max=MAX_STEP,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_JITTER): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=MAX_JITTER,
                        step=5,
                        unit_of_measurement="%",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(CONF_STAGGER): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="effect",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
        )
