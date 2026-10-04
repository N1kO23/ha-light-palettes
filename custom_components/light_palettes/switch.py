"""The on/off switch of each effect."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started

from . import LightPalettesConfigEntry
from .engine import backend_kinds
from .entity import EffectEntity, effect_subentries

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightPalettesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    for sub in effect_subentries(manager):
        async_add_entities(
            [EffectSwitch(manager, sub, "effect")], config_subentry_id=sub.subentry_id
        )


class EffectSwitch(EffectEntity, SwitchEntity, RestoreEntity):
    """Runs or stops the effect."""

    _attr_name = None  # the device (effect) name
    _attr_translation_key = "effect"

    @property
    def is_on(self) -> bool:
        return self.effect.running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        effect = self.effect
        return {
            "palette": self.manager.palettes.get(effect.palette_id or ""),
            "lights": effect.members,
            "active_lights": sorted(effect.runners),
            "skipped_lights": effect.skipped,
            "backends": backend_kinds(self.manager, effect.members),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.effect.start(turn_lights_on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.effect.stop(release=True)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state != STATE_ON:
            return

        @callback
        def _resume(_hass: HomeAssistant) -> None:
            # After a restart or reload, carry on with the lights that are on;
            # the others join as soon as they come on.
            try:
                self.effect.start(turn_lights_on=False)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not resume %s: %s", self.effect.title, err)

        self.async_on_remove(async_at_started(self.hass, _resume))
