"""Config flow for Groupe-E Energy integration."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

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


class GroupeEFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Groupe-E Energy."""

    VERSION = 1

    @callback
    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "GroupeEOptionsFlowHandler":
        """Get the options flow for this handler."""
        return GroupeEOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

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

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of the integration."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data=user_input,
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
                        default=entry.data.get(CONF_STAT_ID_DISCRIMINATOR, ""),
                    ): str,
                }
            ),
            errors=errors,
        )


class ConfigFlow(GroupeEFlowHandler):
    """HA entrypoint wrapper for the flow handler."""


class GroupeEOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle Groupe-E options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            data = dict(user_input)
            schedule_str = data.get(CONF_TARIFF_SCHEDULE, "").strip()
            if schedule_str:
                periods = []
                for part in schedule_str.split(","):
                    part = part.strip()
                    if "-" in part:
                        start_str, end_str = part.split("-", 1)
                        try:
                            start_h = int(start_str.split(":")[0])
                            end_h = int(end_str.split(":")[0])
                            if (
                                0 <= start_h < 24
                                and 0 < end_h <= 24
                                and start_h < end_h
                            ):
                                periods.append({"start": start_h, "end": end_h})
                        except (ValueError, IndexError):
                            pass
                data[CONF_TARIFF_SCHEDULE] = periods
            else:
                data.pop(CONF_TARIFF_SCHEDULE, None)
            return self.async_create_entry(title="", data=data)

        current = self.config_entry.options.get(
            CONF_TARIFF_SCHEDULE, DEFAULT_TARIFF_SCHEDULE
        )
        if isinstance(current, list):
            current = ",".join(
                f"{p['start']:02d}:00-{p['end']:02d}:00" for p in current
            )
        else:
            current = ""

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
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
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                    vol.Optional(
                        CONF_TARIFF_SCHEDULE,
                        default=current,
                    ): str,
                }
            ),
        )
