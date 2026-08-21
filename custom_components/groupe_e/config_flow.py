"""Config flow for Groupe-E Energy integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupeEAPI, GroupeEApiError, GroupeEAuthError
from .const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_PARTNER,
    CONF_PREMISE,
    CONF_STAT_ID_DISCRIMINATOR,
    CONF_TARIFF_SCHEDULE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_TARIFF_SCHEDULE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _parse_tariff_schedule(value: str) -> list[dict[str, int]]:
    """Parse a tariff schedule string like '07:00-12:00,17:00-23:00'.

    Hours may be fractional ('07:30-12:00' -> start 7.5). Raises ValueError
    with a human-readable message when a segment is invalid.
    """
    periods: list[dict[str, int]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"Invalid period '{part}': expected 'HH:MM-HH:MM'")
        start_str, end_str = part.split("-", 1)

        def _parse_hour(hhmm: str) -> int:
            pieces = hhmm.strip().split(":")
            hours = int(pieces[0])
            minutes = int(pieces[1]) if len(pieces) > 1 else 0
            total = hours * 60 + minutes
            return total

        start_minutes = _parse_hour(start_str)
        end_minutes = _parse_hour(end_str)
        if not (0 <= start_minutes < end_minutes <= 24 * 60):
            raise ValueError(
                f"Invalid period '{part}': must satisfy 00:00 <= start < end <= 24:00"
            )
        periods.append({"start": start_minutes / 60, "end": end_minutes / 60})
    return periods


def _format_tariff_schedule(periods: list[dict]) -> str:
    """Format stored tariff periods back into 'HH:MM-HH:MM,...' form."""
    def _fmt(hours: float) -> str:
        total = round(hours * 60)
        return f"{total // 60:02d}:{total % 60:02d}"

    return ",".join(f"{_fmt(p['start'])}-{_fmt(p['end'])}" for p in periods)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate credentials and premise/partner against the live API.

    Raises GroupeEAuthError for bad credentials and GroupeEApiError for
    connectivity or premise/partner problems.
    """
    api = GroupeEAPI(
        async_get_clientsession(hass),
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
    )
    await api.async_validate_credentials(data[CONF_PREMISE], data[CONF_PARTNER])


class GroupeEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Groupe-E Energy."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "GroupeEOptionsFlowHandler":
        """Get the options flow for this handler."""
        return GroupeEOptionsFlowHandler()

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_USERNAME]}:{user_input[CONF_PREMISE]}:"
                f"{user_input[CONF_PARTNER]}"
            )
            self._abort_if_unique_id_configured()

            try:
                await _validate_input(self.hass, user_input)
            except GroupeEAuthError:
                errors["base"] = "invalid_auth"
            except (GroupeEApiError, HomeAssistantError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Groupe-E settings")
                errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_PREMISE): str,
                    vol.Required(CONF_PARTNER): str,
                    vol.Required(CONF_NT_PRICE): vol.All(
                        vol.Coerce(float), vol.Range(min=0)
                    ),
                    vol.Required(CONF_HT_PRICE): vol.All(
                        vol.Coerce(float), vol.Range(min=0)
                    ),
                    vol.Optional(CONF_STAT_ID_DISCRIMINATOR): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Handle reconfiguration of the integration."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            new_unique_id = (
                f"{user_input[CONF_USERNAME]}:{user_input[CONF_PREMISE]}:"
                f"{user_input[CONF_PARTNER]}"
            )
            if new_unique_id != entry.unique_id:
                collision = any(
                    other.entry_id != entry.entry_id
                    and other.unique_id == new_unique_id
                    for other in self.hass.config_entries.async_entries(DOMAIN)
                )
                if collision:
                    errors["base"] = "already_configured"
                    user_input = None
            if not errors:
                # data_updates merges into existing data so keys not present in
                # the reconfigure form (e.g. prices) are preserved.
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                    unique_id=new_unique_id,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME)
                    ): str,
                    vol.Required(
                        CONF_PASSWORD, default=entry.data.get(CONF_PASSWORD)
                    ): str,
                    vol.Required(
                        CONF_PREMISE, default=entry.data.get(CONF_PREMISE)
                    ): str,
                    vol.Required(
                        CONF_PARTNER, default=entry.data.get(CONF_PARTNER)
                    ): str,
                    vol.Optional(
                        CONF_STAT_ID_DISCRIMINATOR,
                        description={"suggested_value": entry.data.get(
                            CONF_STAT_ID_DISCRIMINATOR, ""
                        )},
                    ): str,
                }
            ),
            errors=errors,
        )


class GroupeEOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle Groupe-E options."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the options."""
        errors = {}
        if user_input is not None:
            data = dict(user_input)
            schedule_str = data.get(CONF_TARIFF_SCHEDULE, "").strip()
            if schedule_str:
                try:
                    data[CONF_TARIFF_SCHEDULE] = _parse_tariff_schedule(schedule_str)
                except (ValueError, IndexError):
                    errors["base"] = "invalid_tariff_schedule"
            else:
                data.pop(CONF_TARIFF_SCHEDULE, None)
                data[CONF_TARIFF_SCHEDULE] = DEFAULT_TARIFF_SCHEDULE

            if not errors:
                return self.async_create_entry(title="", data=data)

        current = self.config_entry.options.get(
            CONF_TARIFF_SCHEDULE, DEFAULT_TARIFF_SCHEDULE
        )
        current_str = (
            _format_tariff_schedule(current) if isinstance(current, list) else ""
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NT_PRICE,
                    default=self.config_entry.options.get(
                        CONF_NT_PRICE,
                        self.config_entry.data.get(CONF_NT_PRICE, ""),
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_HT_PRICE,
                    default=self.config_entry.options.get(
                        CONF_HT_PRICE,
                        self.config_entry.data.get(CONF_HT_PRICE, ""),
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional(
                    CONF_TARIFF_SCHEDULE,
                    description={"suggested_value": current_str},
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
