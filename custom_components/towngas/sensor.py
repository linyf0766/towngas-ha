"""Sensor platform for Towngas integration."""
from __future__ import annotations

import logging
import asyncio
import re
from datetime import datetime, timedelta
import async_timeout
import aiohttp
import json
from typing import Any
from urllib.parse import urlencode

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
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
    CONF_HOST,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    CONF_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# 请求头模板
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "{host}/",
    "X-Requested-With": "XMLHttpRequest",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Towngas sensor from a config entry."""
    config = entry.data
    options = entry.options

    update_interval = options.get(
        CONF_UPDATE_INTERVAL,
        config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
    )
    flaresolverr_url = options.get(
        CONF_FLARESOLVERR_URL,
        config.get(CONF_FLARESOLVERR_URL)
    )

    coordinator = TowngasCoordinator(
        hass,
        config[CONF_SUBS_CODE],
        config[CONF_ORG_CODE],
        config[CONF_HOST],
        update_interval,
        flaresolverr_url,
    )

    await coordinator.async_refresh()
    async_add_entities([TowngasSensor(coordinator, config, entry.entry_id)])


class TowngasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """数据协调器，自动切换普通请求和 FlareSolverr 模式。"""

    def __init__(
        self,
        hass: HomeAssistant,
        subs_code: str,
        org_code: str,
        host: str,
        update_interval: int,
        flaresolverr_url: str,
    ) -> None:
        self._subs_code = subs_code
        self._org_code = org_code
        self._host = host.rstrip("/")
        self._flaresolverr_url = flaresolverr_url
        self._api_url = f"{self._host}/openapi/uv1/biz/checkRouters"
        self.last_updated: datetime | None = None

        # 模式标志和会话ID（用于 FlareSolverr 会话复用和释放）
        self._use_flaresolverr = False
        self._flaresolverr_session_id: str | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self._subs_code}_{self._org_code}",
            update_interval=timedelta(minutes=update_interval),
        )

    async def _direct_request(self) -> tuple[int, str, str]:
        """轻量模式：直接使用 aiohttp 请求 API。"""
        params = {
            "token": "0",
            "scene": "2003",
            "subsCode": self._subs_code,
            "orgCode": self._org_code,
        }
        headers = BROWSER_HEADERS.copy()
        headers["Referer"] = headers["Referer"].format(host=self._host)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                self._api_url,
                params=params,
                headers=headers,
                ssl=False,
            ) as resp:
                text = await resp.text()
                return resp.status, resp.headers.get("Content-Type", ""), text

    async def _flaresolverr_request(self) -> tuple[int, str, str]:
        """FlareSolverr 模式：通过无头浏览器代理请求，并自动提取 <pre> 标签内的 JSON。"""
        params = {
            "token": "0",
            "scene": "2003",
            "subsCode": self._subs_code,
            "orgCode": self._org_code,
        }
        full_url = f"{self._api_url}?{urlencode(params)}"

        # 如果没有会话ID，则创建一个新的会话
        if self._flaresolverr_session_id is None:
            create_payload = {"cmd": "sessions.create"}
            async with aiohttp.ClientSession() as session:
                async with session.post(self._flaresolverr_url, json=create_payload, timeout=30) as resp:
                    result = await resp.json()
                    if result.get("status") == "ok":
                        self._flaresolverr_session_id = result.get("session")
                        _LOGGER.info("Created FlareSolverr session: %s", self._flaresolverr_session_id)
                    else:
                        _LOGGER.warning("Failed to create FlareSolverr session, using sessionless mode")

        payload = {
            "cmd": "request.get",
            "url": full_url,
            "maxTimeout": 60000,
        }
        if self._flaresolverr_session_id:
            payload["session"] = self._flaresolverr_session_id

        async with aiohttp.ClientSession() as session:
            async with session.post(self._flaresolverr_url, json=payload, timeout=70) as resp:
                result = await resp.json()
                if result.get("status") != "ok":
                    error_msg = result.get("message", "Unknown error")
                    raise UpdateFailed(f"FlareSolverr error: {error_msg}")

                solution = result.get("solution", {})
                status_code = solution.get("status", 0)
                content_type = solution.get("headers", {}).get("Content-Type", "")
                response_text = solution.get("response", "")

                # 关键修复：如果响应是 HTML 但包含 <pre> 标签内的 JSON，提取出来
                if "text/html" in content_type and "<pre>" in response_text:
                    match = re.search(r"<pre>(.*?)</pre>", response_text, re.DOTALL)
                    if match:
                        cleaned = match.group(1).strip()
                        _LOGGER.debug("Extracted JSON from HTML <pre>: %s", cleaned[:200])
                        # 覆盖原始响应，以便后续解析
                        response_text = cleaned
                        # 同时强制修改 content_type 为 application/json，避免后续检查失败
                        content_type = "application/json"

                _LOGGER.debug(
                    "FlareSolverr response: status=%s, content_type=%s, response_len=%d",
                    status_code, content_type, len(response_text)
                )
                return status_code, content_type, response_text

    async def _destroy_flaresolverr_session(self) -> None:
        """主动销毁 FlareSolverr 会话，释放浏览器资源。"""
        if self._flaresolverr_session_id:
            destroy_payload = {"cmd": "sessions.destroy", "session": self._flaresolverr_session_id}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self._flaresolverr_url, json=destroy_payload, timeout=10) as resp:
                        _LOGGER.debug("Destroyed FlareSolverr session: %s", self._flaresolverr_session_id)
            except Exception as e:
                _LOGGER.warning("Failed to destroy FlareSolverr session: %s", e)
            finally:
                self._flaresolverr_session_id = None

    async def _async_update_data(self) -> dict[str, Any]:
        """获取燃气余额数据，自动选择请求模式。"""
        # 如果已经切换到 FlareSolverr 模式，直接使用
        if self._use_flaresolverr:
            try:
                async with async_timeout.timeout(70):
                    status, content_type, text = await self._flaresolverr_request()
                    return self._parse_response(status, content_type, text)
            except Exception as err:
                # 如果是会话失效，尝试重置会话
                if "session" in str(err).lower():
                    await self._destroy_flaresolverr_session()
                raise UpdateFailed(f"FlareSolverr request failed: {err}")

        # 轻量模式：先尝试直接请求，若检测到反爬则切换模式并重试
        try:
            async with async_timeout.timeout(20):
                status, content_type, text = await self._direct_request()

                # 检测是否为反爬页面 (HTML 或 202/403)
                if status in (202, 403, 429) or "html" in content_type:
                    _LOGGER.info("⚠️ Anti-bot detected (status=%s), switching to FlareSolverr mode", status)
                    self._use_flaresolverr = True
                    # 立即用 FlareSolverr 重试
                    return await self._async_update_data()

                # 正常响应，直接解析
                return self._parse_response(status, content_type, text)

        except asyncio.TimeoutError:
            _LOGGER.error("Direct request timeout, switching to FlareSolverr")
            self._use_flaresolverr = True
            return await self._async_update_data()
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.exception("Direct request error, switching to FlareSolverr: %s", err)
            self._use_flaresolverr = True
            return await self._async_update_data()

    def _parse_response(self, status: int, content_type: str, text: str) -> dict[str, Any]:
        """解析 API 响应，提取余额。"""
        # 放宽状态码检查：允许 200, 202, 206 等，只要不是明显的错误（4xx,5xx）
        if status >= 400:
            raise UpdateFailed(f"HTTP error status {status}")

        # 处理非 JSON 内容：尝试从 HTML 中提取 JSON 片段
        original_text = text
        if "json" not in content_type:
            # 尝试从 HTML 中找到 {} 或 [] 包裹的内容（简单启发式）
            # 但更精确的是之前的 <pre> 提取，这里作为后备
            match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if match:
                text = match.group(1)
                _LOGGER.debug("Extracted JSON fragment from non-JSON response")
            else:
                # 如果无法提取，记录错误
                _LOGGER.error("Cannot extract JSON from response, preview: %s", original_text[:300])
                raise UpdateFailed(f"Response does not contain valid JSON (content-type={content_type})")

        # 处理 JSONP
        if text.startswith("callback(") and text.endswith(")"):
            text = text[8:-1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            _LOGGER.error("JSON decode error: %s, preview: %s", err, text[:300])
            raise UpdateFailed(f"Invalid JSON response: {err}")

        if not isinstance(data, dict):
            raise UpdateFailed(f"Response is not a JSON object, type={type(data)}")

        if "code" in data and data["code"] != 0:
            error_msg = data.get("msg", data.get("message", "Unknown error"))
            raise UpdateFailed(f"API error: {error_msg} (code={data['code']})")

        balance_data = data.get("data") if "data" in data else data
        if "savingSum" not in balance_data:
            _LOGGER.error("Response keys: %s", list(balance_data.keys()))
            raise UpdateFailed(f"Missing 'savingSum' in response. Keys: {list(balance_data.keys())}")

        self.last_updated = dt_util.utcnow()
        _LOGGER.info("✅ Fetched balance: %.2f for %s", balance_data["savingSum"], self._subs_code)
        return balance_data

    async def async_shutdown(self) -> None:
        """关闭协调器，释放 FlareSolverr 会话资源。"""
        await self._destroy_flaresolverr_session()
        await super().async_shutdown()


class TowngasSensor(SensorEntity):
    """燃气余额传感器实体。"""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CNY"
    _attr_icon = "mdi:currency-cny"
    _attr_should_poll = False

    def __init__(self, coordinator: TowngasCoordinator, config: dict, entry_id: str) -> None:
        self._coordinator = coordinator
        self._subs_code = config[CONF_SUBS_CODE]
        self._org_code = config[CONF_ORG_CODE]
        self._host = config[CONF_HOST]
        self._entry_id = entry_id

        self._attr_name = f"Towngas Balance {self._subs_code}"
        self._attr_unique_id = f"towngas_balance_{self._subs_code}_{self._org_code}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": self._attr_name,
            "manufacturer": "Towngas",
            "configuration_url": self._host,
        }

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        if self._coordinator.data is None:
            return None
        return self._coordinator.data.get("savingSum")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._coordinator.data is None:
            return None
        attrs = {
            "subs_code": self._subs_code,
            "org_code": self._org_code,
            "host": self._host,
            "using_flaresolverr": self._coordinator._use_flaresolverr,
        }
        if self._coordinator.last_updated:
            attrs["last_update"] = self._coordinator.last_updated.isoformat()
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )
