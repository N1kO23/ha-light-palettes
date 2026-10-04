"""Fixtures for Light Palettes tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.components.light import ColorMode, LightEntityFeature
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.light_palettes.const import (
    CONF_COLORS,
    CONF_JITTER,
    CONF_LIGHTS,
    CONF_PALETTE,
    CONF_STAGGER,
    CONF_STEP,
    DOMAIN,
    SUBENTRY_EFFECT,
    SUBENTRY_PALETTE,
)

RED_BLUE = [[255, 0, 0], [0, 0, 255]]
GREEN_WHITE = [[0, 255, 0], [255, 255, 255]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mqtt_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "mqtt", "publish")


@pytest.fixture
def light_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "light", "turn_on")


def palette(title: str, colors: list[list[int]], sid: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        data={CONF_COLORS: colors},
        subentry_type=SUBENTRY_PALETTE,
        title=title,
        unique_id=None,
        subentry_id=sid,
    )


def effect(
    title: str, lights: list[str], palette_id: str, sid: str, **extra: Any
) -> ConfigSubentryData:
    data = {
        CONF_LIGHTS: lights,
        CONF_PALETTE: palette_id,
        CONF_STEP: 10,
        CONF_JITTER: 0,
        CONF_STAGGER: False,
    } | extra
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_EFFECT, title=title, unique_id=None, subentry_id=sid
    )


@pytest.fixture
def make_entry(hass: HomeAssistant) -> Callable[..., MockConfigEntry]:
    def _make(subentries: list[ConfigSubentryData], options: dict | None = None) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Light Palettes",
            data={},
            options=options or {},
            subentries_data=subentries,
        )
        entry.add_to_hass(hass)
        return entry

    return _make


@pytest.fixture
def add_obk_light(hass: HomeAssistant) -> Callable[..., str]:
    """Register an MQTT light that looks like OpenBeken discovery made it."""
    mqtt_entry = MockConfigEntry(domain="mqtt")
    mqtt_entry.add_to_hass(hass)

    def _add(short_name: str, state: str = "on") -> str:
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=mqtt_entry.entry_id,
            identifiers={("mqtt", f"{short_name}_long")},
            name=short_name,
            configuration_url="http://192.168.1.50/index",
        )
        ent = er.async_get(hass).async_get_or_create(
            "light",
            "mqtt",
            f"{short_name}_light",
            device_id=device.id,
            suggested_object_id=short_name,
            config_entry=mqtt_entry,
        )
        hass.states.async_set(
            ent.entity_id,
            state,
            {"supported_color_modes": [ColorMode.RGB], "supported_features": 0},
        )
        return ent.entity_id

    return _add


def add_generic_light(
    hass: HomeAssistant, entity_id: str, transition: bool, state: str = "on", rgb=(10, 10, 10)
) -> str:
    hass.states.async_set(
        entity_id,
        state,
        {
            "supported_color_modes": [ColorMode.HS],
            "supported_features": LightEntityFeature.TRANSITION if transition else 0,
            "rgb_color": list(rgb),
        },
    )
    return entity_id


def payloads(calls: list[ServiceCall], topic_prefix: str) -> list[str]:
    return [c.data["payload"] for c in calls if c.data["topic"].startswith(topic_prefix)]
