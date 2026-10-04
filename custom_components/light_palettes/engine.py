"""The effect engine.

Every running effect owns a set of lights and runs one independent loop per
light. Each loop picks the next palette colour, works out how long this fade
should take (base time ± per-light randomness) and hands the colour to the
light's backend:

* OpenBeken bulbs fade on the bulb itself: the integration sets the bulb's
  interpolation speed so the fade lasts exactly that long, then sends the
  target colour over MQTT. One message per fade, perfectly smooth.
* Any other colour light gets ``light.turn_on`` with ``transition`` if it
  supports transitions, or a software fade made of small steps if it doesn't.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.components.light import (
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    COLOR_MODES_COLOR,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
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
    MIN_FADE_SECONDS,
    OBK_FAST_LERP,
    OBK_SMOOTH_TRANSITIONS_FLAG,
    SIGNAL_EFFECT_UPDATED,
    SUBENTRY_EFFECT,
    SUBENTRY_PALETTE,
)

_LOGGER = logging.getLogger(__name__)

RGB = tuple[int, int, int]


def parse_topic_overrides(raw: str) -> tuple[dict[str, str], list[str]]:
    """Parse ``light.x=topic`` lines. Returns (overrides, unparseable lines)."""
    overrides: dict[str, str] = {}
    bad: list[str] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entity_id, sep, topic = line.partition("=")
        entity_id, topic = entity_id.strip(), topic.strip()
        if not sep or not entity_id.startswith("light.") or not topic or " " in topic:
            bad.append(line)
            continue
        overrides[entity_id] = topic
    return overrides, bad


def expand_lights(hass: HomeAssistant, entity_ids: Iterable[str]) -> list[str]:
    """Replace light groups (and old-style groups) with their member lights."""
    found: list[str] = []

    def _walk(entity_id: str, seen: set[str]) -> None:
        if entity_id in seen:
            return
        seen.add(entity_id)
        state = hass.states.get(entity_id)
        members = state.attributes.get(ATTR_ENTITY_ID) if state else None
        if isinstance(members, (list, tuple)) and members:
            for member in members:
                _walk(member, seen)
        elif entity_id.startswith("light.") and entity_id not in found:
            found.append(entity_id)

    for entity_id in entity_ids:
        _walk(entity_id, set())
    return found


def _is_on(state: State | None) -> bool:
    return state is not None and state.state == STATE_ON


# --------------------------------------------------------------------------- backends


class Backend:
    """How colours reach one light."""

    kind = "base"

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        self.hass = hass
        self.entity_id = entity_id

    @callback
    def prepare(self, turn_on: bool) -> None:
        """Called once before the first fade."""

    @callback
    def fade_to(self, rgb: RGB, seconds: float) -> None:
        raise NotImplementedError

    @callback
    def stop(self) -> None:
        """Stop any fade in progress (no cleanup on the light)."""

    @callback
    def release(self) -> None:
        """The effect no longer drives this light: restore normal behaviour."""
        self.stop()


class OpenBekenBackend(Backend):
    """Fades on the bulb using OpenBeken's built-in colour interpolation."""

    kind = "openbeken"

    def __init__(self, hass: HomeAssistant, entity_id: str, topic: str) -> None:
        super().__init__(hass, entity_id)
        self.topic = topic

    def _publish(self, command: str, payload: str) -> None:
        self.hass.async_create_task(
            self.hass.services.async_call(
                "mqtt",
                "publish",
                {"topic": f"cmnd/{self.topic}/{command}", "payload": payload},
            ),
            eager_start=True,
        )

    @callback
    def prepare(self, turn_on: bool) -> None:
        # Smooth transitions only write flash if the flag actually changes.
        commands = [f"SetFlag {OBK_SMOOTH_TRANSITIONS_FLAG} 1"]
        if turn_on:
            commands.append("led_enableAll 1")
        self._publish("backlog", "; ".join(commands))

    @callback
    def fade_to(self, rgb: RGB, seconds: float) -> None:
        # Speed is in colour units per second; 255 / seconds lets even a full
        # 0 -> 255 swing on one channel finish right as the next fade starts.
        speed = round(255 / max(seconds, MIN_FADE_SECONDS), 2)
        r, g, b = rgb
        self._publish("backlog", f"led_lerpSpeed {speed}; led_basecolor_rgb {r},{g},{b}")

    @callback
    def release(self) -> None:
        self._publish("led_lerpSpeed", str(OBK_FAST_LERP))


class GenericBackend(Backend):
    """Any Home Assistant colour light."""

    kind = "generic"

    def __init__(self, hass: HomeAssistant, entity_id: str, soft_interval: float) -> None:
        super().__init__(hass, entity_id)
        self.soft_interval = soft_interval
        self._soft_unsub: CALLBACK_TYPE | None = None

    @property
    def native_transition(self) -> bool:
        state = self.hass.states.get(self.entity_id)
        features = state.attributes.get(ATTR_SUPPORTED_FEATURES, 0) if state else 0
        return bool(features & LightEntityFeature.TRANSITION)

    def _turn_on(self, rgb: RGB, transition: float | None) -> None:
        data: dict[str, Any] = {ATTR_ENTITY_ID: self.entity_id, ATTR_RGB_COLOR: list(rgb)}
        if transition is not None:
            data[ATTR_TRANSITION] = round(transition, 1)
        self.hass.async_create_task(
            self.hass.services.async_call("light", "turn_on", data), eager_start=True
        )

    @callback
    def fade_to(self, rgb: RGB, seconds: float) -> None:
        self.stop()
        if self.native_transition:
            self._turn_on(rgb, seconds)
            return

        # Software fade: walk from the current colour in small steps.
        state = self.hass.states.get(self.entity_id)
        start = state.attributes.get(ATTR_RGB_COLOR) if state else None
        steps = max(1, round(seconds / self.soft_interval))
        if not start or steps == 1:
            self._turn_on(rgb, None)
            return
        start_rgb = tuple(int(v) for v in start)
        interval = seconds / steps

        position = 0

        @callback
        def _step(_now: Any = None) -> None:
            nonlocal position
            position += 1
            t = position / steps
            colour = tuple(round(s + (e - s) * t) for s, e in zip(start_rgb, rgb, strict=True))
            self._turn_on(colour, None)  # type: ignore[arg-type]
            self._soft_unsub = (
                async_call_later(self.hass, interval, _step) if position < steps else None
            )

        _step()

    @callback
    def stop(self) -> None:
        if self._soft_unsub:
            self._soft_unsub()
            self._soft_unsub = None


# --------------------------------------------------------------------------- runners


class LightRunner:
    """The palette loop for one light."""

    def __init__(self, effect: Effect, backend: Backend, start_index: int) -> None:
        self.effect = effect
        self.backend = backend
        self.index = start_index
        self._unsub: CALLBACK_TYPE | None = None

    @callback
    def start(self, turn_on: bool) -> None:
        self.backend.prepare(turn_on)
        self._step()

    @callback
    def _step(self, _now: Any = None) -> None:
        colors = self.effect.colors
        if not colors:
            return
        rgb = colors[self.index % len(colors)]
        self.index += 1
        seconds = self.effect.next_duration()
        self.backend.fade_to(rgb, seconds)
        self._unsub = async_call_later(self.effect.hass, seconds, self._step)

    @callback
    def stop(self, release: bool) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if release:
            self.backend.release()
        else:
            self.backend.stop()


class Effect:
    """One effect (a config subentry): lights, palette and timing."""

    def __init__(self, manager: EffectManager, subentry: ConfigSubentry) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.subentry_id = subentry.subentry_id
        self.title = subentry.title
        self.data: dict[str, Any] = dict(subentry.data)
        self.running = False
        self.runners: dict[str, LightRunner] = {}
        self.members: list[str] = []
        self.skipped: list[str] = []
        self._unsub_state: CALLBACK_TYPE | None = None
        self._rng = random.Random()

    # ---- config -------------------------------------------------------------

    @property
    def palette_id(self) -> str | None:
        return self.data.get(CONF_PALETTE)

    @property
    def colors(self) -> list[RGB]:
        return self.manager.palette_colors(self.palette_id)

    @property
    def step(self) -> float:
        return float(self.data.get(CONF_STEP, DEFAULT_STEP))

    @property
    def jitter(self) -> float:
        return float(self.data.get(CONF_JITTER, DEFAULT_JITTER))

    @property
    def stagger(self) -> bool:
        return bool(self.data.get(CONF_STAGGER, False))

    def next_duration(self) -> float:
        """This fade's length for one light: base time ± random jitter."""
        spread = self.jitter / 100
        factor = 1 + spread * self._rng.uniform(-1, 1) if spread else 1
        return round(max(MIN_FADE_SECONDS, self.step * factor), 2)

    @callback
    def apply_data(self, title: str, data: Mapping[str, Any], palette_changed: bool) -> None:
        """Take new settings. Timing changes apply from the next fade on;
        lights, palette or stagger changes restart the loops."""
        old = self.data
        self.title = title
        self.data = dict(data)
        restart = palette_changed or any(
            old.get(k) != self.data.get(k) for k in (CONF_LIGHTS, CONF_PALETTE, CONF_STAGGER)
        )
        if self.running and restart:
            self._restart()
        self.notify()

    @callback
    def notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_EFFECT_UPDATED.format(self.subentry_id))

    # ---- running ------------------------------------------------------------

    @callback
    def start(self, turn_lights_on: bool = True) -> None:
        """Start the effect.

        ``turn_lights_on`` is False when resuming after a restart: only lights
        that are already on take part, the rest join when they come on.
        """
        if len(self.colors) < 2:
            raise HomeAssistantError(
                f"{self.title}: pick a palette with at least two colours first"
            )
        if self.running:
            self.stop(release=False)
        self.running = True
        self._resolve_members()
        if not self.members:
            self.running = False
            self.notify()
            raise HomeAssistantError(f"{self.title}: none of its lights can show colour")

        for position, entity_id in enumerate(self.members):
            state = self.hass.states.get(entity_id)
            if not turn_lights_on and (
                not _is_on(state) or self.manager.owner(entity_id) not in (None, self)
            ):
                # Resuming: lights that are off join when they come on, and
                # lights another running effect already has stay with it.
                continue
            self._start_light(entity_id, position, turn_on=not _is_on(state))

        self._unsub_state = async_track_state_change_event(
            self.hass, self.members, self._on_light_state
        )
        if self.skipped:
            _LOGGER.warning(
                "%s: skipping lights that can't show colour: %s",
                self.title,
                ", ".join(self.skipped),
            )
        self.notify()

    @callback
    def stop(self, release: bool = True) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_runners(release=release)
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        self.manager.release_all(self)
        self.notify()

    @callback
    def _restart(self) -> None:
        """Re-run on the lights currently taking part, without turning others on."""
        if not self.running:
            return
        active = set(self.runners)
        self.stop(release=False)
        try:
            self.start(turn_lights_on=False)
        except HomeAssistantError as err:
            _LOGGER.warning("%s", err)
            return
        # Lights that were running but are off can't be in ``active``, so this
        # only matters for lights the new config no longer includes.
        for entity_id in active - set(self.members):
            backend = self.manager.backend_for(entity_id)
            if backend:
                backend.release()

    @callback
    def _resolve_members(self) -> None:
        self.members, self.skipped = [], []
        for entity_id in expand_lights(self.hass, self.data.get(CONF_LIGHTS, [])):
            if self.manager.backend_for(entity_id) is None:
                self.skipped.append(entity_id)
            else:
                self.members.append(entity_id)

    def _start_index(self, position: int) -> int:
        if not self.stagger or not self.members:
            return 0
        return int(position * len(self.colors) / len(self.members))

    @callback
    def _start_light(self, entity_id: str, position: int, turn_on: bool) -> None:
        backend = self.manager.backend_for(entity_id)
        if backend is None:
            return
        self.manager.claim(self, entity_id)
        runner = LightRunner(self, backend, self._start_index(position))
        self.runners[entity_id] = runner
        runner.start(turn_on=turn_on)

    @callback
    def drop_light(self, entity_id: str, release: bool) -> None:
        if runner := self.runners.pop(entity_id, None):
            runner.stop(release=release)

    @callback
    def _stop_runners(self, release: bool) -> None:
        for entity_id in list(self.runners):
            self.drop_light(entity_id, release)

    @callback
    def _on_light_state(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        if not self.running:
            return

        if _is_on(new):
            # Came back on (or became available): rejoin unless another effect has it.
            if entity_id not in self.runners and self.manager.owner(entity_id) in (None, self):
                self._start_light(entity_id, self.members.index(entity_id), turn_on=False)
                self.notify()
            return

        if entity_id in self.runners:
            # Off: put the bulb back to instant changes. Unavailable: nothing to talk to.
            self.drop_light(entity_id, release=new is not None and new.state == STATE_OFF)
            self.manager.release(self, entity_id)
            if (
                new is not None
                and new.state == STATE_OFF
                and not self.runners
                and not any(_is_on(self.hass.states.get(e)) for e in self.members)
            ):
                # The last light of the effect was switched off: end the effect.
                self.stop(release=True)
                return
            self.notify()


class EffectManager:
    """Owns all effects and palettes of the config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.effects: dict[str, Effect] = {}
        self._owners: dict[str, Effect] = {}
        self._backends: dict[str, Backend] = {}
        self._palette_snapshot: dict[str, list[RGB]] = {}
        self._options_snapshot: dict[str, Any] = dict(entry.options)
        self.structure = self.structure_signature(entry)
        self.load()

    @staticmethod
    def structure_signature(entry: ConfigEntry) -> tuple:
        """What needs a reload (entities to add/remove or new select options)."""
        return tuple(
            sorted(
                (sub.subentry_type, sub.subentry_id, sub.title) for sub in entry.subentries.values()
            )
        )

    @callback
    def load(self) -> None:
        for sub in self.entry.subentries.values():
            if sub.subentry_type == SUBENTRY_EFFECT:
                self.effects[sub.subentry_id] = Effect(self, sub)
        self._palette_snapshot = self._read_palettes()

    def _read_palettes(self) -> dict[str, list[RGB]]:
        return {
            sub.subentry_id: [tuple(int(v) for v in c) for c in sub.data.get(CONF_COLORS, [])]
            for sub in self.entry.subentries.values()
            if sub.subentry_type == SUBENTRY_PALETTE
        }

    # ---- palettes -----------------------------------------------------------

    @property
    def palettes(self) -> dict[str, str]:
        """Palette id -> title, in the order they were added."""
        return {
            sub.subentry_id: sub.title
            for sub in self.entry.subentries.values()
            if sub.subentry_type == SUBENTRY_PALETTE
        }

    def palette_colors(self, palette_id: str | None) -> list[RGB]:
        return self._palette_snapshot.get(palette_id or "", [])

    # ---- config changes -------------------------------------------------------

    @callback
    def apply_entry_update(self) -> None:
        """Live-apply a change that didn't alter the structure."""
        to_resume: list[Effect] = []
        if dict(self.entry.options) != self._options_snapshot:
            # Topic overrides or the soft-fade interval changed: rebuild backends
            # and restart running effects so they pick them up.
            self._options_snapshot = dict(self.entry.options)
            to_resume = [e for e in self.effects.values() if e.running]
            for effect in to_resume:
                effect.stop(release=True)
            self._backends.clear()
        new_palettes = self._read_palettes()
        changed_palettes = {
            pid for pid, colors in new_palettes.items() if self._palette_snapshot.get(pid) != colors
        }
        self._palette_snapshot = new_palettes
        for sub in self.entry.subentries.values():
            if sub.subentry_type != SUBENTRY_EFFECT:
                continue
            effect = self.effects[sub.subentry_id]
            effect.apply_data(
                sub.title,
                sub.data,
                palette_changed=sub.data.get(CONF_PALETTE) in changed_palettes,
            )
        for effect in to_resume:
            try:
                effect.start(turn_lights_on=False)
            except HomeAssistantError as err:
                _LOGGER.warning("%s", err)

    @callback
    def update_effect(self, subentry_id: str, changes: Mapping[str, Any]) -> None:
        """Persist a change made from an entity (palette, timing)."""
        sub = self.entry.subentries[subentry_id]
        self.hass.config_entries.async_update_subentry(
            self.entry, sub, data={**sub.data, **changes}
        )

    # ---- ownership ----------------------------------------------------------

    def owner(self, entity_id: str) -> Effect | None:
        return self._owners.get(entity_id)

    @callback
    def claim(self, effect: Effect, entity_id: str) -> None:
        """A light can only follow one effect: the latest one started wins."""
        previous = self._owners.get(entity_id)
        self._owners[entity_id] = effect
        if previous is None or previous is effect:
            return
        previous.drop_light(entity_id, release=False)
        if previous.running and not previous.runners:
            previous.stop(release=False)
        else:
            previous.notify()

    @callback
    def release(self, effect: Effect, entity_id: str) -> None:
        if self._owners.get(entity_id) is effect:
            del self._owners[entity_id]

    @callback
    def release_all(self, effect: Effect) -> None:
        for entity_id in [e for e, owner in self._owners.items() if owner is effect]:
            del self._owners[entity_id]

    # ---- backends -----------------------------------------------------------

    def backend_for(self, entity_id: str) -> Backend | None:
        if entity_id in self._backends:
            return self._backends[entity_id]
        backend = self._make_backend(entity_id)
        if backend is not None:
            self._backends[entity_id] = backend
        return backend

    def _make_backend(self, entity_id: str) -> Backend | None:
        overrides, _ = parse_topic_overrides(self.entry.options.get(CONF_TOPIC_OVERRIDES, ""))
        if topic := overrides.get(entity_id):
            return OpenBekenBackend(self.hass, entity_id, topic)
        if topic := openbeken_topic(self.hass, entity_id):
            return OpenBekenBackend(self.hass, entity_id, topic)

        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
        if COLOR_MODES_COLOR.isdisjoint(modes):
            return None
        interval = float(
            self.entry.options.get(CONF_SOFT_FADE_INTERVAL, DEFAULT_SOFT_FADE_INTERVAL)
        )
        return GenericBackend(self.hass, entity_id, interval)

    # ---- lifecycle ----------------------------------------------------------

    @callback
    def shutdown(self, release: bool) -> None:
        for effect in self.effects.values():
            effect.stop(release=release)


def openbeken_topic(hass: HomeAssistant, entity_id: str) -> str | None:
    """Work out an OpenBeken bulb's MQTT topic from its discovery info.

    OpenBeken registers its device under its short name, which is also its MQTT
    client topic unless changed, and points the configuration URL at
    ``http://<ip>/index``. Other MQTT lights don't match that.
    """
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None or ent.platform != "mqtt" or ent.device_id is None:
        return None
    device = dr.async_get(hass).async_get(ent.device_id)
    if device is None or not device.name:
        return None
    url = (device.configuration_url or "").rstrip("/")
    if not url.endswith("/index"):
        return None
    return device.name


def backend_kinds(manager: EffectManager, entity_ids: Iterable[str]) -> dict[str, str]:
    """Which backend drives each light (for entity attributes)."""
    return {e: backend.kind for e in entity_ids if (backend := manager.backend_for(e)) is not None}
