"""Config flow for Groupe-E Energy integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import (
    DOMAIN,
    CONF_PREMISE,
    CONF_PARTNER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)

class GroupeEFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Groupe-E Energy."""

    VERSION = 1

    @callback
    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "GroupeEOptionsFlowHandler":
        """Get the options flow for this handler."""
        return GroupeEOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            # Check if already configured
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            # Simple title
            return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_PREMISE): str,
                    vol.Required(CONF_PARTNER): str,
                }
            ),
            errors=errors,
        )


class ConfigFlow(GroupeEFlowHandler):
    """HA entrypoint wrapper for the flow handler."""
    pass

class GroupeEOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Groupe-E options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15)),
                }
            ),
        )
