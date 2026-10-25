"""Config flow for Salzburg Netz."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_API_KEY, CONF_GPNR, CONF_PRICE_ENTITY, CONF_ZP, DOMAIN

CONF_NAME = "name"


def _check(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not re.fullmatch(r"1\d{7}", data[CONF_GPNR]):
        errors[CONF_GPNR] = "invalid_gpnr"
    if not re.fullmatch(r"AT00\w{29}|003\d{7}", data[CONF_ZP]):
        errors[CONF_ZP] = "invalid_zp"
    if len(data[CONF_API_KEY]) < 10:
        errors[CONF_API_KEY] = "invalid_key"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_NAME: user_input.get(CONF_NAME, "").strip(),
        CONF_API_KEY: user_input[CONF_API_KEY].strip(),
        CONF_GPNR: re.sub(r"\s", "", user_input[CONF_GPNR]),
        CONF_ZP: re.sub(r"\s", "", user_input[CONF_ZP]).upper(),
    }


class SalzburgNetzConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for API key, customer number and metering point.

    The key is not tested here on purpose: the API allows only a few requests a
    day, so the first daily sync is the test (its result shows on the Status sensor).
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SalzburgNetzOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            if not (errors := _check(data)):
                await self.async_set_unique_id(data[CONF_ZP])
                self._abort_if_unique_id_configured()
                title = data.pop(CONF_NAME) or "Salzburg Netz"
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default="St. Gilgen"): str,
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(CONF_GPNR): str,
                    vol.Required(CONF_ZP): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paste a new API key (keys are valid for at most two years)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if len(key) < 10:
                errors[CONF_API_KEY] = "invalid_key"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )


class SalzburgNetzOptionsFlow(OptionsFlow):
    """Pick the sensor that holds the electricity price (optional)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_PRICE_ENTITY: user_input.get(CONF_PRICE_ENTITY) or ""}
            )
        current = self.config_entry.options.get(CONF_PRICE_ENTITY) or None
        key = (
            vol.Optional(CONF_PRICE_ENTITY, description={"suggested_value": current})
            if current
            else vol.Optional(CONF_PRICE_ENTITY)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({key: EntitySelector(EntitySelectorConfig(domain="sensor"))}),
        )
