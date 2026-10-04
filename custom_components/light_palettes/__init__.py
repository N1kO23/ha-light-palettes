"""Light Palettes: slow, smooth colour-palette effects for groups of lights."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .engine import EffectManager

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SELECT, Platform.SWITCH]

type LightPalettesConfigEntry = ConfigEntry[EffectManager]


async def async_setup_entry(hass: HomeAssistant, entry: LightPalettesConfigEntry) -> bool:
    """Set up Light Palettes from a config entry."""
    entry.runtime_data = EffectManager(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: LightPalettesConfigEntry) -> None:
    """Palettes or effects added, removed or renamed need new entities, so reload.
    Anything else (timing, colours, chosen palette, lights) is applied live."""
    manager = entry.runtime_data
    if EffectManager.structure_signature(entry) != manager.structure:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        manager.apply_entry_update()


async def async_unload_entry(hass: HomeAssistant, entry: LightPalettesConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove the entities first so the switches' last state ("on") is what gets
    # restored after a reload, then stop the loops. On shutdown MQTT may already
    # be gone, so don't try to reset the bulbs then.
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.shutdown(release=not hass.is_stopping)
    return unloaded
