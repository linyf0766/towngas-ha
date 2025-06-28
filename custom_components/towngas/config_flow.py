"""Config flow for Towngas integration."""
from __future__ import annotations

import logging
import json
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

def load_org_list() -> list[dict]:
    """Load organization list from local JSON file."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, "orglist.json")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("orgList", [])
    except Exception as err:
        _LOGGER.error("Failed to load organization list: %s", err)
        return []

class TowngasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Towngas."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.org_list = []
        self.selected_org = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        # 从本地文件加载机构列表
        if not self.org_list:
            self.org_list = await self.hass.async_add_executor_job(load_org_list)
            if not self.org_list:
                return self.async_abort(reason="no_orgs")

        if user_input is not None:
            # 保存选择的机构信息
            self.selected_org = next(
                (org for org in self.org_list if org["orgCode"] == user_input["org_code"]),
                None
            )
            
            if self.selected_org:
                # 转到下一步输入用户号
                return await self.async_step_account()
            errors["base"] = "invalid_org"

        # 构建机构选择下拉菜单
        org_options = {
            org["orgCode"]: f"{org['shortName']} ({org['desc']})"
            for org in self.org_list
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("org_code"): vol.In(org_options)
            }),
            errors=errors
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the account setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # 创建唯一ID并保存配置
            unique_id = f"{user_input[CONF_SUBS_CODE]}_{self.selected_org['orgCode']}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            config_data = {
                CONF_SUBS_CODE: user_input[CONF_SUBS_CODE],
                CONF_ORG_CODE: self.selected_org["orgCode"],
                CONF_HOST: self.selected_org["host"],
                CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL]
            }

            return self.async_create_entry(
                title=f"Towngas {self.selected_org['shortName']} {user_input[CONF_SUBS_CODE]}",
                data=config_data
            )

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({
                vol.Required(CONF_SUBS_CODE): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=DEFAULT_UPDATE_INTERVAL
                ): int,
            }),
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
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): int,
            }),
        )