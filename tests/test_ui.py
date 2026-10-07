"""The integration's face: every entity has an icon, an English and a Hungarian name; every
error a user can see is translatable; the brand images meet the brands spec.

These are class guards -- each one fails the build when a new entity, select option,
string or raise site arrives without its counterpart -- and each has a positive control
proving it still bites.
"""

import json
import re
import struct
from pathlib import Path

import pytest
from homeassistant.components.brands.const import ALLOWED_IMAGES
from homeassistant.helpers import entity_registry as er

from custom_components.sb_katana.const import DOMAIN

from .fakes import FAKE_ADDRESS

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "sb_katana"
EN = json.loads((PACKAGE / "translations" / "en.json").read_text(encoding="utf-8"))
HU = json.loads((PACKAGE / "translations" / "hu.json").read_text(encoding="utf-8"))
ICONS = json.loads((PACKAGE / "icons.json").read_text(encoding="utf-8"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")
ICON = re.compile(r"^mdi:[a-z0-9]+(-[a-z0-9]+)*$")


def _leaves(tree: dict, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], str]:
    out: dict[tuple[str, ...], str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            out |= _leaves(value, (*prefix, key))
        else:
            out[(*prefix, key)] = value
    return out


def _entities(hass, entry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


def test_strings_json_is_the_english_translation():
    assert json.loads((PACKAGE / "strings.json").read_text(encoding="utf-8")) == EN


def test_hungarian_covers_exactly_what_english_does_with_the_same_placeholders():
    en, hu = _leaves(EN), _leaves(HU)
    assert sorted(set(en) - set(hu)) == [], "missing in hu.json"
    assert sorted(set(hu) - set(en)) == [], "in hu.json but not in English"
    for path, text in en.items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(hu[path])), path
        assert hu[path].strip(), path


async def test_every_entity_has_an_icon_and_both_names(hass, entry):
    seen = 0
    for ent in _entities(hass, entry):
        if ent.translation_key is None:  # the media player: named after the device
            continue
        seen += 1
        platform = ent.domain
        icon = ICONS["entity"].get(platform, {}).get(ent.translation_key)
        assert icon and ICON.match(icon["default"]), (platform, ent.translation_key)
        for lang, tree in (("en", EN), ("hu", HU)):
            assert tree["entity"][platform][ent.translation_key]["name"], (lang, platform, ent.translation_key)
    assert seen > 40  # positive control: the registry really was walked


async def test_icon_and_translation_keys_all_belong_to_real_entities(hass, entry):
    live = {(e.domain, e.translation_key) for e in _entities(hass, entry) if e.translation_key}
    for platform, keys in ICONS["entity"].items():
        for key, spec in keys.items():
            assert (platform, key) in live, f"icons.json has {platform}.{key}, which no entity uses"
            for icon in [spec["default"], *spec.get("state", {}).values()]:
                assert ICON.match(icon), icon
    for platform, keys in EN["entity"].items():
        for key in keys:
            assert (platform, key) in live, f"strings.json names {platform}.{key}, which no entity uses"
    assert set(ICONS["services"]) == set(EN["services"])


async def test_every_select_option_is_translated_or_named_by_the_soundbar(hass, entry):
    from custom_components.sb_katana.select import SELECTS

    translated = {d.key for d in SELECTS if d.translated}
    assert translated >= {"input", "output", "decoder", "auto_standby", "display"}  # positive control
    for ent in _entities(hass, entry):
        if ent.domain != "select":
            continue
        options = hass.states.get(ent.entity_id).attributes["options"]
        states_en = EN["entity"]["select"][ent.translation_key].get("state", {})
        states_hu = HU["entity"]["select"][ent.translation_key].get("state", {})
        icon_states = ICONS["entity"]["select"][ent.translation_key].get("state", {})
        if ent.translation_key in translated:
            assert set(options) <= set(states_en), (ent.translation_key, set(options) - set(states_en))
            assert set(states_en) == set(states_hu), ent.translation_key
            assert set(icon_states) <= set(states_en), ent.translation_key
        else:
            assert not states_en and not icon_states, ent.translation_key


# --- errors a user can see ------------------------------------------------------------

_RAISE = re.compile(r"raise (\w+)\(")
_KATANA_ERRORS = {"KatanaCommandError", "KatanaRejectedError", "KatanaUnconfirmedError", "StreamTargetError"}
_HA_ERRORS = {"HomeAssistantError", "ServiceValidationError", "ConfigEntryNotReady"}


def _call_body(source: str, start: int) -> str:
    """The text of the call whose '(' is at ``start``, up to its matching ')'."""
    depth = 0
    for i in range(start, len(source)):
        depth += {"(": 1, ")": -1}.get(source[i], 0)
        if depth == 0:
            return source[start : i + 1]
    raise AssertionError("unbalanced call")


def untranslated_raises(source: str) -> list[str]:
    """Every user-visible raise without a translation key, as its first line."""
    bad = []
    for m in _RAISE.finditer(source):
        cls, body = m.group(1), _call_body(source, m.end() - 1)
        if cls in _KATANA_ERRORS:
            # (message, "translation_key", ...): the key is the second positional argument.
            ok = re.match(r'\(\s*(?:f?"(?:[^"\\]|\\.)*"\s*)+,\s*"[a-z0-9_]+"', body) is not None
        elif cls in _HA_ERRORS:
            ok = "translation_key=" in body
        else:
            continue
        if not ok:
            bad.append(source[m.start() : source.index("\n", m.start())].strip())
    return bad


def raised_translation_keys(source: str) -> set[str]:
    keys = set(re.findall(r'translation_key="([a-z0-9_]+)"', source))
    keys |= set(
        re.findall(r'(?:Katana\w*Error|StreamTargetError)\(\s*(?:f?"(?:[^"\\]|\\.)*"\s*)+,\s*"([a-z0-9_]+)"', source)
    )
    return keys


def test_every_user_visible_raise_is_translatable():
    for path in sorted(PACKAGE.glob("*.py")):
        assert untranslated_raises(path.read_text(encoding="utf-8")) == [], path.name


def test_the_raise_guard_bites():
    assert untranslated_raises('raise KatanaCommandError("soundbar not connected")\n')
    assert untranslated_raises('raise HomeAssistantError(f"oops {x}")\n')
    assert not untranslated_raises('raise KatanaCommandError(\n    f"no answer to {x}",\n    "no_answer",\n)\n')
    assert not untranslated_raises('raise ServiceValidationError("x", translation_key="unknown_option")\n')
    assert not untranslated_raises(
        'raise KatanaUnconfirmedError(\n    f"{a} is not"\n    " confirmed",\n    "unconfirmed",\n)\n'
    )


def test_every_raised_key_has_both_translations():
    raised: set[str] = set()
    for path in PACKAGE.glob("*.py"):
        raised |= raised_translation_keys(path.read_text(encoding="utf-8"))
    assert len(raised) > 15  # positive control
    for key in sorted(raised):
        for lang, tree in (("en", EN), ("hu", HU)):
            assert key in tree["exceptions"] or key in tree["issues"], (lang, key)


async def test_the_ui_gets_the_translation_key_from_a_refused_write(hass, entry, monkeypatch):
    import dataclasses

    from homeassistant.exceptions import HomeAssistantError

    from custom_components.sb_katana import families

    monkeypatch.setitem(
        families.FAMILIES, "energy_saving", dataclasses.replace(families.FAMILIES["energy_saving"], confirmed=False)
    )

    eid = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{FAKE_ADDRESS}_energy_saving")
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    assert caught.value.translation_domain == DOMAIN
    assert caught.value.translation_key == "unconfirmed"
    assert "control" in caught.value.translation_placeholders


# --- brand images (homeassistant/components/brands serves custom_components/<d>/brand/) ---


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def test_brand_images_meet_the_brands_spec():
    images = {p.name: _png_size(p) for p in (PACKAGE / "brand").iterdir()}
    assert {"icon.png", "icon@2x.png", "logo.png", "logo@2x.png"} <= set(images)
    assert set(images) <= ALLOWED_IMAGES
    for name, (w, h) in images.items():
        hidpi = "@2x" in name
        if "icon" in name:
            assert (w, h) == ((512, 512) if hidpi else (256, 256)), name
        else:
            low, high = (256, 512) if hidpi else (128, 256)
            assert low <= min(w, h) <= high, name
            assert w >= h, f"{name}: landscape preferred"
