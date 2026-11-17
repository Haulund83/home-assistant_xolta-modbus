"""Serve the Xolta battery card and load it on every dashboard (no manual resource needed)."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILE = Path(__file__).parent / "xolta-battery-card.js"
CARD_URL = f"/{DOMAIN}/xolta-battery-card.js"


async def async_register_card(hass: HomeAssistant) -> bool:
    """Register the static file and add it to the frontend. Returns False if skipped."""
    if hass.http is None or "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; the battery card is not registered")
        return False

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=True)]
    )
    # The version in the URL makes browsers fetch the new card after an update.
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True
