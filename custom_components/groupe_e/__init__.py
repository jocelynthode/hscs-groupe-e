"""The Groupe-E Energy integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api import GroupeEAPI
from .coordinator import GroupeEDataUpdateCoordinator
from .const import (
    DOMAIN,
    CONF_PREMISE,
    CONF_PARTNER,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
