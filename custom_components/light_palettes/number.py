"""Timing controls of each effect."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LightPalettesConfigEntry
from .const import (
    CONF_JITTER,
    CONF_STEP,
    DEFAULT_JITTER,
    DEFAULT_STEP,
    MAX_JITTER,
    MAX_STEP,
    MIN_STEP,
)
from .engine import EffectManager
from .entity import EffectEntity, effect_subentries


@dataclass(frozen=True, kw_only=True)
class EffectNumberDescription(NumberEntityDescription):
    default: float


NUMBERS: tuple[EffectNumberDescription, ...] = (
    EffectNumberDescription(
        key=CONF_STEP,
        translation_key=CONF_STEP,
        native_min_value=MIN_STEP,
        native_max_value=MAX_STEP,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        default=DEFAULT_STEP,
    ),
    EffectNumberDescription(
        key=CONF_JITTER,
        translation_key=CONF_JITTER,
        native_min_value=0,
        native_max_value=MAX_JITTER,
        native_step=5,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        default=DEFAULT_JITTER,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LightPalettesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    for sub in effect_subentries(manager):
        async_add_entities(
            [EffectNumber(manager, sub, desc) for desc in NUMBERS],
            config_subentry_id=sub.subentry_id,
        )


class EffectNumber(EffectEntity, NumberEntity):
    """Seconds per colour or timing randomness."""

    entity_description: EffectNumberDescription

    def __init__(
        self, manager: EffectManager, subentry, description: EffectNumberDescription
    ) -> None:
        super().__init__(manager, subentry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        key = self.entity_description.key
        return self.effect.data.get(key, self.entity_description.default)

    async def async_set_native_value(self, value: float) -> None:
        self.manager.update_effect(
            self.effect.subentry_id, {self.entity_description.key: int(value)}
        )
