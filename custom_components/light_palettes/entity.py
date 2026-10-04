"""Shared base for the per-effect entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_EFFECT_UPDATED, SUBENTRY_EFFECT
from .engine import Effect, EffectManager


def effect_subentries(manager: EffectManager) -> list[ConfigSubentry]:
    return [
        sub for sub in manager.entry.subentries.values() if sub.subentry_type == SUBENTRY_EFFECT
    ]


class EffectEntity(Entity):
    """An entity that belongs to one effect (one device per effect)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: EffectManager, subentry: ConfigSubentry, key: str) -> None:
        self.manager = manager
        self.effect: Effect = manager.effects[subentry.subentry_id]
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Light Palettes",
            model="Palette effect",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_EFFECT_UPDATED.format(self.effect.subentry_id),
                self.async_write_ha_state,
            )
        )
