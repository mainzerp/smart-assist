"""Frontend panel registration for Smart Assist Dashboard.

Registers a custom sidebar panel in Home Assistant that serves
the Smart Assist dashboard as a Lit Web Component.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

from homeassistant.components.frontend import async_register_built_in_panel

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Path to the www directory containing the panel JS
PANEL_DIR = pathlib.Path(__file__).parent / "www"
PANEL_URL = f"/api/{DOMAIN}/panel"
PANEL_FILENAME = "smart-assist-panel.js"

# Sidebar configuration
SIDEBAR_TITLE = "Smart Assist"
SIDEBAR_ICON = "mdi:brain"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the Smart Assist frontend panel."""
    # Register static path to serve the panel JS file
    try:
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_URL, str(PANEL_DIR), cache_headers=False)]
        )
        _LOGGER.debug("Registered static path: %s -> %s", PANEL_URL, PANEL_DIR)
    except ImportError:
        # Fallback for older HA versions
        hass.http.register_static_path(PANEL_URL, str(PANEL_DIR), cache_headers=False)
        _LOGGER.debug("Registered static path (legacy): %s -> %s", PANEL_URL, PANEL_DIR)
    except Exception as err:
        _LOGGER.error("Failed to register static path: %s", err)
        return

    # Register the panel in the sidebar
    try:
        # Remove existing panel first to avoid conflicts on reload
        try:
            from homeassistant.components.frontend import async_remove_panel
            if hass.data.get("frontend_panels", {}).get(DOMAIN):
                async_remove_panel(hass, DOMAIN)
                _LOGGER.debug("Removed existing Smart Assist panel before re-registration")
        except Exception:
            pass

        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=SIDEBAR_TITLE,
            sidebar_icon=SIDEBAR_ICON,
            frontend_url_path=DOMAIN,
            config={
                "_panel_custom": {
                    "name": "smart-assist-panel",
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"{PANEL_URL}/{PANEL_FILENAME}",
                }
            },
            require_admin=True,
        )
        _LOGGER.info("Smart Assist dashboard panel registered in sidebar")
    except Exception as err:
        _LOGGER.error("Failed to register Smart Assist panel: %s", err)
