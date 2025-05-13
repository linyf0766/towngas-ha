"""Config flow for Towngas integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SUBS_CODE): str,
        vol.Required(CONF_ORG_CODE): str,
        vol.Optional(
            CONF_UPDATE_INTERVAL,
            default=DEFAULT_UPDATE_INTERVAL,
        ): int,
    }
)

class TowngasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Towngas."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_SUBS_CODE]}_{user_input[CONF_ORG_CODE]}"
            )
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Towngas {user_input[CONF_SUBS_CODE]}", 
                data=user_input
            )

        return self.async_show_form(
            step_id="user", 
            data_schema=DATA_SCHEMA, 
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TowngasOptionsFlowHandler(config_entry)

class TowngasOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Towngas."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): int,
                }
            ),
        )