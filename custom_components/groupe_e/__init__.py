"""The Groupe-E Energy integration."""

import logging

import voluptuous as vol
from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupeEAPI
from .const import (
    CONF_PARTNER,
    CONF_PREMISE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .coordinator import GroupeEDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

SERVICE_RESET_STATISTICS = "reset_statistics"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Groupe-E Energy from a config entry."""
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    premise = entry.data.get(CONF_PREMISE)
    partner = entry.data.get(CONF_PARTNER)

    api = GroupeEAPI(async_get_clientsession(hass), username, password)

    update_interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    coordinator = GroupeEDataUpdateCoordinator(
        hass, api, premise, partner, update_interval, entry
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Groupe-E integration."""

    async def _handle_reset_statistics(call: ServiceCall) -> None:
        """Handle the reset_statistics service call."""
        entry_id = call.data["entry_id"]

        coordinator: GroupeEDataUpdateCoordinator | None = hass.data[DOMAIN].get(
            entry_id
        )

        if coordinator is None:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        statistic_ids = coordinator.statistic_ids

        _LOGGER.warning(
            "Resetting Groupe-E statistics for entry %s: %s",
            entry_id,
            statistic_ids,
        )

        @callback
        def _statistics_cleared() -> None:
            """Refresh coordinator after statistics have been cleared."""
            hass.async_create_task(coordinator.async_request_refresh())

        get_instance(hass).async_clear_statistics(
            statistic_ids,
            on_done=_statistics_cleared,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_STATISTICS,
        _handle_reset_statistics,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): vol.Coerce(str),
            }
        ),
    )

    return True
