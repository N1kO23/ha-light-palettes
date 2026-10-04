"""Config, options and subentry flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.light_palettes.const import (
    CONF_COLORS,
    CONF_JITTER,
    CONF_LIGHTS,
    CONF_PALETTE,
    CONF_STAGGER,
    CONF_STEP,
    CONF_TOPIC_OVERRIDES,
    DOMAIN,
    STARTER_PALETTES,
    SUBENTRY_EFFECT,
    SUBENTRY_PALETTE,
)

from .conftest import RED_BLUE, palette


def _suggested(result, key):
    for field in result["data_schema"].schema:
        if str(field) == key:
            return (field.description or {}).get("suggested_value")
    raise KeyError(key)


async def test_setup_with_starter_palettes(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"starter_palettes": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    titles = sorted(s.title for s in entry.subentries.values())
    assert titles == sorted(STARTER_PALETTES)

    # Only one instance.
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT


async def test_add_and_edit_palette(hass: HomeAssistant, make_entry) -> None:
    entry = make_entry([palette("Existing", RED_BLUE, "p1")])
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PALETTE), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "details"

    # Names are unique (case-insensitive).
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "existing", "color_count": 3}
    )
    assert result["errors"] == {"name": "name_taken"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Forest", "color_count": 3}
    )
    assert result["step_id"] == "colors"
    # New slots come pre-filled with colours spread round the wheel.
    assert _suggested(result, "color_1") == [255, 0, 0]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"color_1": [0, 80, 0], "color_2": [40, 160, 20], "color_3": [120, 200, 0]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    forest = next(s for s in entry.subentries.values() if s.title == "Forest")
    assert forest.data[CONF_COLORS] == [[0, 80, 0], [40, 160, 20], [120, 200, 0]]

    # Editing opens with the current values and keeps them when count grows.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PALETTE),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": forest.subentry_id},
    )
    assert _suggested(result, "name") == "Forest"
    assert _suggested(result, "color_count") == 3
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Deep forest", "color_count": 4}
    )
    assert _suggested(result, "color_2") == [40, 160, 20]
    assert _suggested(result, "color_4") is not None
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "color_1": [0, 80, 0],
            "color_2": [40, 160, 20],
            "color_3": [120, 200, 0],
            "color_4": [0, 40, 0],
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    forest = entry.subentries[forest.subentry_id]
    assert forest.title == "Deep forest"
    assert len(forest.data[CONF_COLORS]) == 4


async def test_effect_needs_a_palette(hass: HomeAssistant, make_entry) -> None:
    entry = make_entry([])
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_EFFECT), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_palettes"


async def test_effect_add_and_edit(hass: HomeAssistant, make_entry) -> None:
    entry = make_entry([palette("Sunset", RED_BLUE, "p1"), palette("Night", RED_BLUE, "p2")])
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_EFFECT), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "effect"
    user_input = {
        "name": "Living room",
        CONF_LIGHTS: [],
        CONF_PALETTE: "p2",
        CONF_STEP: 45,
        CONF_JITTER: 20,
        CONF_STAGGER: True,
    }
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)
    assert result["errors"] == {CONF_LIGHTS: "no_lights"}

    user_input[CONF_LIGHTS] = ["light.a", "light.b"]
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    eff = next(s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_EFFECT)
    assert dict(eff.data) == {
        CONF_LIGHTS: ["light.a", "light.b"],
        CONF_PALETTE: "p2",
        CONF_STEP: 45,
        CONF_JITTER: 20,
        CONF_STAGGER: True,
    }
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_EFFECT),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": eff.subentry_id},
    )
    assert _suggested(result, "name") == "Living room"
    assert _suggested(result, CONF_LIGHTS) == ["light.a", "light.b"]
    assert _suggested(result, CONF_PALETTE) == "p2"
    assert _suggested(result, CONF_JITTER) == 20


async def test_options_validation(hass: HomeAssistant, make_entry) -> None:
    entry = make_entry([])
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TOPIC_OVERRIDES: "desk lamp", "soft_fade_interval": 2}
    )
    assert result["errors"] == {CONF_TOPIC_OVERRIDES: "bad_override"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_TOPIC_OVERRIDES: "light.desk=obk_desk\n", "soft_fade_interval": 2},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TOPIC_OVERRIDES] == "light.desk=obk_desk\n"
