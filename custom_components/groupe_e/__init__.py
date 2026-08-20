"""The Groupe-E Energy integration."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupeEAPI
from .const import (
    CONF_PARTNER,
    CONF_PREMISE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    TARIFF_TIMEZONE,
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
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        _LOGGER.warning(
            "Groupe-E first refresh failed, continuing setup: %s",
            premise,
        )

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

        rebuild_since = call.data.get("rebuild_since")
        local_tz = ZoneInfo(TARIFF_TIMEZONE)
        now_local = datetime.now(local_tz)
        year_start_local = now_local.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if rebuild_since is not None:
            if rebuild_since.tzinfo is None:
                rebuild_since = rebuild_since.replace(tzinfo=ZoneInfo(TARIFF_TIMEZONE))
            rebuild_dt = rebuild_since.astimezone(local_tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            coordinator._rebuild_since = rebuild_dt.astimezone(timezone.utc)
        else:
            coordinator._rebuild_since = year_start_local.astimezone(timezone.utc)

        _LOGGER.warning(
            "Resetting Groupe-E statistics for entry %s (rebuild_since=%s)",
            entry_id,
            coordinator._rebuild_since,
        )

        hass.create_task(coordinator.async_request_refresh())

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_STATISTICS,
        _handle_reset_statistics,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): vol.Coerce(str),
                vol.Optional("rebuild_since"): vol.Coerce(datetime.fromisoformat),
            }
        ),
    )

    return True
