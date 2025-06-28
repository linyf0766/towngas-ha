"""The Towngas integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Towngas from a config entry."""
    # �滻Ϊ�µ� async_forward_entry_setups ����
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # ����ԭ����async_forward_entry_unload ��Ȼ����ȷ�ķ���
    return await hass.config_entries.async_forward_entry_unload(entry, "sensor")