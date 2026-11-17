"""Tests for the bundled battery card."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from homeassistant.core import HomeAssistant
import pytest

from custom_components.xolta_modbus.card import CARD_FILE, async_register_card

ROOT = Path(__file__).parents[1] / "custom_components" / "xolta_modbus"


def test_card_version_matches_manifest() -> None:
    """The card's version string follows the integration version."""
    manifest = json.loads((ROOT / "manifest.json").read_text())
    card = CARD_FILE.read_text(encoding="utf-8")
    assert f'const VERSION = "{manifest["version"]}";' in card


def test_card_uses_only_existing_translation_keys() -> None:
    """Every translation key the card looks for exists in the integration."""
    card = CARD_FILE.read_text(encoding="utf-8")
    keys = set(
        re.findall(r'^\s+\w+: "(\w+)",$', card.split("const KEYS = {")[1].split("};")[0], re.M)
    )
    en = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    known = {k for platform in en["entity"].values() for k in platform}
    assert keys and keys <= known, keys - known


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_card_is_valid_javascript() -> None:
    """Syntax check with node (CI installs node)."""
    subprocess.run(["node", "--check", str(CARD_FILE)], check=True)


async def test_register_skips_without_frontend(hass: HomeAssistant) -> None:
    """In a Home Assistant without the frontend (e.g. tests) nothing is registered."""
    assert await async_register_card(hass) is False
