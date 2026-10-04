"""The palette picker of each effect."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightPalettesConfigEntry
from .const import CONF_PALETTE
from .entity import EffectEntity, effect_subentries


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightPalettesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    for sub in effect_subentries(manager):
        async_add_entities(
            [PaletteSelect(manager, sub, "palette")], config_subentry_id=sub.subentry_id
        )


class PaletteSelect(EffectEntity, SelectEntity):
    """Which palette the effect plays."""

    _attr_translation_key = "palette"

    @property
    def options(self) -> list[str]:
        return list(self.manager.palettes.values())

    @property
    def current_option(self) -> str | None:
        return self.manager.palettes.get(self.effect.palette_id or "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The colours, so dashboards can show a preview."""
        return {"colors": ["#{:02x}{:02x}{:02x}".format(*rgb) for rgb in self.effect.colors]}

    async def async_select_option(self, option: str) -> None:
        for palette_id, title in self.manager.palettes.items():
            if title == option:
                self.manager.update_effect(self.effect.subentry_id, {CONF_PALETTE: palette_id})
                return
        raise ServiceValidationError(f"Unknown palette: {option}")
