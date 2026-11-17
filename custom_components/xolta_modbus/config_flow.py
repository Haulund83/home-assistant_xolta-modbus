"""Config flow: only an IP address and whether writing is allowed."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_ALLOW_WRITE,
    CONF_REPEAT_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .modbus import (
    XoltaConnectionRefused,
    XoltaExceptionResponse,
    XoltaModbusClient,
    XoltaModbusError,
)
from .registers import MAIN_BLOCK, decode

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_PORT: DEFAULT_PORT,
    CONF_UNIT_ID: DEFAULT_UNIT_ID,
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    CONF_REPEAT_INTERVAL: DEFAULT_REPEAT_INTERVAL,
}


async def validate_connection(host: str, port: int, unit_id: int) -> str | None:
    """Read the main block and check that the state of charge is plausible.

    Returns an error key for the form, or None when the controller answers.
    """
    client = XoltaModbusClient(host, port, unit_id)
    try:
        main = await client.read_input_registers(*MAIN_BLOCK)
    except XoltaConnectionRefused:
        return "connection_refused"
    except XoltaExceptionResponse:
        return "not_xolta"
    except XoltaModbusError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error while validating %s", host)
        return "unknown"
    finally:
        await client.close()
    soc = decode(main, [0, 0, 0, 0]).get("state_of_charge")
    if soc is None or not 0 <= soc <= 100:
        return "not_xolta"
    return None


def _host_schema(default: str = "") -> vol.Schema:
    return vol.Schema({vol.Required(CONF_HOST, default=default): selector.TextSelector()})


class XoltaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Xolta site controller."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the IP address and the write switch."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: host})
            error = await validate_connection(host, DEFAULT_PORT, DEFAULT_UNIT_ID)
            if error is None:
                return self.async_create_entry(
                    title="Xolta battery",
                    data={CONF_HOST: host},
                    options={
                        **DEFAULT_OPTIONS,
                        CONF_ALLOW_WRITE: user_input[CONF_ALLOW_WRITE],
                    },
                )
            errors["base"] = error

        schema = _host_schema().extend(
            {vol.Required(CONF_ALLOW_WRITE, default=False): selector.BooleanSelector()}
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the IP address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if host != entry.data[CONF_HOST]:
                self._async_abort_entries_match({CONF_HOST: host})
            error = await validate_connection(
                host,
                entry.options.get(CONF_PORT, DEFAULT_PORT),
                entry.options.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
            )
            if error is None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_host_schema(entry.data[CONF_HOST]),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return XoltaOptionsFlow()


def _seconds(minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class XoltaOptionsFlow(OptionsFlow):
    """Write switch plus advanced settings (all have sensible defaults)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_ALLOW_WRITE: user_input[CONF_ALLOW_WRITE],
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_REPEAT_INTERVAL: int(user_input[CONF_REPEAT_INTERVAL]),
                    CONF_PORT: int(user_input[CONF_PORT]),
                    CONF_UNIT_ID: int(user_input[CONF_UNIT_ID]),
                }
            )
        current = {**DEFAULT_OPTIONS, CONF_ALLOW_WRITE: False, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_ALLOW_WRITE): selector.BooleanSelector(),
                vol.Required(CONF_SCAN_INTERVAL): _seconds(5, 300),
                vol.Required(CONF_REPEAT_INTERVAL): _seconds(5, 60),
                vol.Required(CONF_PORT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_UNIT_ID): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=247, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
        )
