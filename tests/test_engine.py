"""Effect engine and entities."""

from __future__ import annotations

from datetime import timedelta
from types import MappingProxyType

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.light_palettes.const import (
    CONF_JITTER,
    CONF_PALETTE,
    CONF_STEP,
    CONF_TOPIC_OVERRIDES,
)
from custom_components.light_palettes.engine import parse_topic_overrides

from .conftest import GREEN_WHITE, RED_BLUE, add_generic_light, effect, palette, payloads

SWITCH = "switch.living_room"
SELECT = "select.living_room_palette"
STEP = "number.living_room_seconds_per_colour"
JITTER = "number.living_room_timing_randomness"


async def _advance(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _switch(hass: HomeAssistant, on: bool, entity_id: str = SWITCH) -> None:
    await hass.services.async_call(
        "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_entities_created(hass: HomeAssistant, make_entry, add_obk_light) -> None:
    bulb = add_obk_light("obk1")
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [bulb], "p1", "e1")]
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(SWITCH).state == "off"
    sel = hass.states.get(SELECT)
    assert sel.state == "Sunset"
    assert sel.attributes["options"] == ["Sunset"]
    assert sel.attributes["colors"] == ["#ff0000", "#0000ff"]
    assert hass.states.get(STEP).state == "10"
    assert hass.states.get(JITTER).state == "0"
    reg = er.async_get(hass)
    assert reg.async_get(SWITCH).config_subentry_id == "e1"


async def test_openbeken_loop(hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls) -> None:
    on_bulb = add_obk_light("obk1")
    off_bulb = add_obk_light("obk2", state="off")
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [on_bulb, off_bulb], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _switch(hass, True)
    assert hass.states.get(SWITCH).state == "on"
    assert payloads(mqtt_calls, "cmnd/obk1/") == [
        "SetFlag 18 1",
        "led_lerpSpeed 25.5; led_basecolor_rgb 255,0,0",
    ]
    # The bulb that was off gets switched on first.
    assert payloads(mqtt_calls, "cmnd/obk2/")[0] == "SetFlag 18 1; led_enableAll 1"
    assert hass.states.get(SWITCH).attributes["backends"] == {
        on_bulb: "openbeken",
        off_bulb: "openbeken",
    }

    await _advance(hass, 10.5)
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1] == "led_lerpSpeed 25.5; led_basecolor_rgb 0,0,255"
    await _advance(hass, 21)
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1] == "led_lerpSpeed 25.5; led_basecolor_rgb 255,0,0"

    # One bulb off: it leaves at once and goes back to instant changes.
    hass.states.async_set(on_bulb, "on", {"supported_color_modes": ["rgb"]})
    hass.states.async_set(off_bulb, "on", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    hass.states.async_set(off_bulb, "off", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    assert payloads(mqtt_calls, "cmnd/obk2/")[-1] == "10000"
    assert hass.states.get(SWITCH).state == "on"
    assert hass.states.get(SWITCH).attributes["active_lights"] == [on_bulb]

    # Back on: it rejoins without a second loop.
    hass.states.async_set(off_bulb, "on", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    assert sorted(hass.states.get(SWITCH).attributes["active_lights"]) == sorted(
        [on_bulb, off_bulb]
    )

    # Everything off: the effect ends itself.
    hass.states.async_set(on_bulb, "off", {"supported_color_modes": ["rgb"]})
    hass.states.async_set(off_bulb, "off", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "off"

    sent = len(mqtt_calls)
    await _advance(hass, 60)
    assert len(mqtt_calls) == sent  # no stray fades after stopping


async def test_jitter_is_per_light(hass: HomeAssistant, make_entry, add_obk_light) -> None:
    bulbs = [add_obk_light(f"obk{i}") for i in range(3)]
    entry = make_entry(
        [
            palette("Sunset", RED_BLUE, "p1"),
            effect("Living room", bulbs, "p1", "e1", jitter=50, step=100),
        ]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    effect_obj = entry.runtime_data.effects["e1"]
    durations = [effect_obj.next_duration() for _ in range(2000)]
    assert 50 <= min(durations) < 55
    assert 145 < max(durations) <= 150
    assert len(set(durations)) > 100


async def test_stagger(hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls) -> None:
    bulbs = [add_obk_light(f"obk{i}") for i in range(2)]
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", bulbs, "p1", "e1", stagger=True)]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    assert payloads(mqtt_calls, "cmnd/obk0/")[-1].endswith("255,0,0")
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1].endswith("0,0,255")


async def test_generic_transition(hass: HomeAssistant, make_entry, light_calls) -> None:
    lamp = add_generic_light(hass, "light.hue_lamp", transition=True)
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [lamp], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    assert len(light_calls) == 1
    assert light_calls[0].data == {"entity_id": lamp, "rgb_color": [255, 0, 0], "transition": 10.0}


async def test_generic_software_fade(hass: HomeAssistant, make_entry, light_calls) -> None:
    lamp = add_generic_light(hass, "light.cheap_strip", transition=False, rgb=(0, 0, 0))
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [lamp], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    # 10 s fade at the default 2 s interval = 5 colour steps.
    for _ in range(4):
        await _advance(hass, 2.01)
    colours = [c.data["rgb_color"] for c in light_calls]
    assert colours == [[51, 0, 0], [102, 0, 0], [153, 0, 0], [204, 0, 0], [255, 0, 0]]
    assert all("transition" not in c.data for c in light_calls)


async def test_light_groups_are_expanded(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    a, b = add_obk_light("obka"), add_obk_light("obkb")
    hass.states.async_set(
        "light.group", "on", {"entity_id": [a, b], "supported_color_modes": ["rgb"]}
    )
    hass.states.async_set("light.white_only", "on", {"supported_color_modes": ["color_temp"]})
    entry = make_entry(
        [
            palette("Sunset", RED_BLUE, "p1"),
            effect("Living room", ["light.group", a, "light.white_only"], "p1", "e1"),
        ]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    attrs = hass.states.get(SWITCH).attributes
    assert attrs["lights"] == [a, b]
    assert attrs["skipped_lights"] == ["light.white_only"]


async def test_latest_effect_takes_over_shared_light(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    shared = add_obk_light("obkshared")
    entry = make_entry(
        [
            palette("Sunset", RED_BLUE, "p1"),
            effect("Living room", [shared], "p1", "e1"),
            effect("Party", [shared], "p1", "e2"),
        ]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True, "switch.living_room")
    await _switch(hass, True, "switch.party")
    assert hass.states.get("switch.party").state == "on"
    # Living room lost its only light, so it switched itself off.
    assert hass.states.get("switch.living_room").state == "off"
    # And only one loop drives the bulb.
    before = len(payloads(mqtt_calls, "cmnd/obkshared/"))
    await _advance(hass, 10.5)
    assert len(payloads(mqtt_calls, "cmnd/obkshared/")) == before + 1


async def test_entities_update_settings_live(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    bulb = add_obk_light("obk1")
    entry = make_entry(
        [
            palette("Sunset", RED_BLUE, "p1"),
            palette("Meadow", GREEN_WHITE, "p2"),
            effect("Living room", [bulb], "p1", "e1"),
        ]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)

    # Timing: saved, and used from the next fade without restarting.
    await hass.services.async_call(
        "number", "set_value", {"entity_id": STEP, "value": 30}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": JITTER, "value": 25}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.subentries["e1"].data[CONF_STEP] == 30
    assert entry.subentries["e1"].data[CONF_JITTER] == 25
    assert hass.states.get(STEP).state == "30"
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1].endswith("255,0,0")  # not restarted

    # Palette: saved and restarts the loop on the new colours.
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": "Meadow"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.subentries["e1"].data[CONF_PALETTE] == "p2"
    assert hass.states.get(SELECT).state == "Meadow"
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1].endswith("0,255,0")
    assert hass.states.get(SWITCH).state == "on"

    # Editing the palette's colours restarts effects that use it.
    hass.config_entries.async_update_subentry(
        entry, entry.subentries["p2"], data={"colors": [[1, 2, 3], [4, 5, 6]]}
    )
    await hass.async_block_till_done()
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1].endswith("1,2,3")


async def test_adding_palette_reloads_and_resumes(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    bulb = add_obk_light("obk1")
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [bulb], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)

    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType({"colors": GREEN_WHITE}),
            subentry_type="palette",
            title="Meadow",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).attributes["options"] == ["Sunset", "Meadow"]
    # The effect came back on by itself after the reload.
    assert hass.states.get(SWITCH).state == "on"


async def test_topic_override_and_options_restart(
    hass: HomeAssistant, make_entry, mqtt_calls
) -> None:
    # A plain MQTT-less light made OpenBeken by an override.
    add_generic_light(hass, "light.desk", transition=False)
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", ["light.desk"], "p1", "e1")],
        options={CONF_TOPIC_OVERRIDES: "light.desk=obk_desk"},
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    assert payloads(mqtt_calls, "cmnd/obk_desk/")[-1].endswith("255,0,0")

    hass.config_entries.async_update_entry(
        entry, options={CONF_TOPIC_OVERRIDES: "light.desk=obk_desk_2"}
    )
    await hass.async_block_till_done()
    assert payloads(mqtt_calls, "cmnd/obk_desk/")[-1] == "10000"
    assert payloads(mqtt_calls, "cmnd/obk_desk_2/")[-1].endswith("255,0,0")


async def test_resume_after_restart_only_uses_lit_lights(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    lit, dark = add_obk_light("obk1"), add_obk_light("obk2", state="off")
    mock_restore_cache(hass, [State(SWITCH, "on")])
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [lit, dark], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "on"
    assert payloads(mqtt_calls, "cmnd/obk1/")
    assert not payloads(mqtt_calls, "cmnd/obk2/")  # not switched on by a restart


async def test_unload_resets_bulbs(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    bulb = add_obk_light("obk1")
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [bulb], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert payloads(mqtt_calls, "cmnd/obk1/")[-1] == "10000"


def test_parse_overrides() -> None:
    overrides, bad = parse_topic_overrides(
        "light.a=obk_a\n# comment\n\n light.b = obk_b \nnonsense\nlight.c=has space"
    )
    assert overrides == {"light.a": "obk_a", "light.b": "obk_b"}
    assert bad == ["nonsense", "light.c=has space"]


async def test_turning_on_twice_keeps_one_loop(
    hass: HomeAssistant, make_entry, add_obk_light, mqtt_calls
) -> None:
    bulb = add_obk_light("obk1")
    entry = make_entry(
        [palette("Sunset", RED_BLUE, "p1"), effect("Living room", [bulb], "p1", "e1")]
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _switch(hass, True)
    await _switch(hass, True)
    before = len(payloads(mqtt_calls, "cmnd/obk1/"))
    await _advance(hass, 10.5)
    assert len(payloads(mqtt_calls, "cmnd/obk1/")) == before + 1
    # And switching a light off and on still rejoins only once.
    hass.states.async_set(bulb, "off", {"supported_color_modes": ["rgb"]})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "off"
