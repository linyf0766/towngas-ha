"""Sensor platform for Towngas integration."""
from __future__ import annotations

import logging
from datetime import datetime
from datetime import timedelta
import async_timeout
import aiohttp
import json

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Towngas sensor from a config entry."""
    config = entry.data
    options = entry.options

    coordinator = TowngasCoordinator(
        hass,
        config[CONF_SUBS_CODE],
        config[CONF_ORG_CODE],
        options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )

    # Perform initial data refresh
    try:
        await coordinator.async_refresh()
    except Exception as err:
        _LOGGER.error("Failed to refresh Towngas data: %s", err)
        raise

    async_add_entities([TowngasSensor(coordinator, config, entry.entry_id)])

class TowngasCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Towngas data."""

    def __init__(self, hass, subs_code, org_code, update_interval):
        """Initialize global Towngas data updater."""
        self._subs_code = subs_code
        self._org_code = org_code
        self._api_url = "https://qingyuan.towngasvcc.com/openapi/uv1/biz/checkRouters"
        self.last_updated = None

        update_interval = timedelta(minutes=update_interval)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch data from Towngas API."""
        params = {
            "token": "0",
            "scene": "2003",
            "subsCode": self._subs_code,
            "orgCode": self._org_code,
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
        }

        try:
            async with async_timeout.timeout(15):
                async with aiohttp.ClientSession() as session:
                    _LOGGER.debug("Requesting URL: %s with params: %s", self._api_url, params)
                    
                    async with session.get(
                        self._api_url,
                        params=params,
                        headers=headers,
                      # ssl=False  # 临时用于调试，生产环境应移除
                    ) as response:
                        text = await response.text()
                        _LOGGER.debug("Raw API response: %s", text)
                        
                        # 尝试处理可能的JSONP响应
                        if text.startswith("callback(") and text.endswith(")"):
                            text = text[8:-1]
                        
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError as err:
                            _LOGGER.error("Failed to parse JSON response. Status: %s, Response: %s", 
                                         response.status, text)
                            raise UpdateFailed(f"Invalid JSON response: {err}")
                        
                        _LOGGER.debug("Parsed API data: %s", data)
                        
                        # 更灵活地处理API响应格式
                        if isinstance(data, dict):
                            # 检查是否有错误码
                            if "code" in data and data["code"] != 0:
                                error_msg = data.get("msg", data.get("message", "Unknown error"))
                                _LOGGER.error("API returned error: %s (code: %s)", 
                                             error_msg, data.get("code"))
                                raise UpdateFailed(f"API error: {error_msg}")
                            
                            # 尝试从不同位置获取数据
                            if "data" in data and "savingSum" in data["data"]:
                                self.last_updated = dt_util.utcnow()
                                return data["data"]
                            elif "savingSum" in data:
                                self.last_updated = dt_util.utcnow()
                                return data
                            else:
                                _LOGGER.error("Could not find balance data in API response")
                                raise UpdateFailed("Could not find balance data in API response")
                        else:
                            _LOGGER.error("Unexpected API response format")
                            raise UpdateFailed("Unexpected API response format")
        except aiohttp.ClientError as err:
            _LOGGER.error("HTTP request failed: %s", err, exc_info=True)
            raise UpdateFailed(f"HTTP request failed: {err}")
        except Exception as err:
            _LOGGER.error("Error communicating with API: %s", err, exc_info=True)
            raise UpdateFailed(f"Error communicating with API: {err}")

class TowngasSensor(SensorEntity):
    """Representation of a Towngas balance sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CNY"
    _attr_icon = "mdi:currency-cny"
    _attr_should_poll = False

    def __init__(self, coordinator, config, entry_id):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._subs_code = config[CONF_SUBS_CODE]
        self._org_code = config[CONF_ORG_CODE]
        self._entry_id = entry_id
        self._attr_name = f"Towngas Balance {self._subs_code}"
        self._attr_unique_id = f"towngas_balance_{self._subs_code}_{self._org_code}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": self._attr_name,
            "manufacturer": "Towngas",
        }

    @property
    def available(self):
        """Return if entity is available."""
        return self._coordinator.last_update_success

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._coordinator.data is None:
            return None
        return self._coordinator.data.get("savingSum")

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if self._coordinator.data is None:
            return None
            
        attrs = {
            "subs_code": self._subs_code,
            "org_code": self._org_code,
        }
        
        if hasattr(self._coordinator, 'last_updated'):
            attrs["last_update"] = self._coordinator.last_updated.isoformat()
            
        return attrs

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(
                self.async_write_ha_state
            )
        )
