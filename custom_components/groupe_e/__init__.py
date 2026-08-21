"""The Groupe-E Energy integration."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GroupeEAPI
from .const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
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


def _entry_unique_id(entry: ConfigEntry) -> str:
    """Build the canonical unique_id for a Groupe-E config entry."""
    return (
        f"{entry.data[CONF_USERNAME]}:{entry.data[CONF_PREMISE]}:"
        f"{entry.data[CONF_PARTNER]}"
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version.

    Version 1 entries used the username as unique_id; version 2 uses
    'username:premise:partner' so multiple premises per account work.
    """
    if entry.version > 2:
        # Downgrade from a newer future version is not supported.
        return False

    if entry.version == 1:
        new_unique_id = _entry_unique_id(entry)

        # Guard against a collision: another entry may already use the new
        # scheme (e.g. re-added under v2 before this entry was migrated).
        collision = any(
            other.entry_id != entry.entry_id and other.unique_id == new_unique_id
            for other in hass.config_entries.async_entries(DOMAIN)
        )
        if collision:
            _LOGGER.warning(
                "Cannot migrate unique_id for entry %s: '%s' already in use; "
                "keeping existing unique_id",
                entry.entry_id,
                new_unique_id,
            )
            hass.config_entries.async_update_entry(entry, version=2)
        else:
            hass.config_entries.async_update_entry(
                entry, unique_id=new_unique_id, version=2
            )
            _LOGGER.debug(
                "Migrated entry %s to version 2 (unique_id=%s)",
                entry.entry_id,
                new_unique_id,
            )

        # Repair hint: the v2.0.0 reconfigure flow could drop price keys from
        # entry data. We cannot recover them, but warn loudly so users can fix
        # the prices in the options flow instead of silently tracking 0 CHF.
        prices = entry.options.get(CONF_NT_PRICE) or entry.data.get(CONF_NT_PRICE)
        ht_price = entry.options.get(CONF_HT_PRICE) or entry.data.get(CONF_HT_PRICE)
        if not prices or not ht_price:
            _LOGGER.warning(
                "Entry %s is missing NT/HT tariff prices (likely lost by an "
                "older reconfigure bug). Set them in the integration options, "
                "otherwise cost statistics will be computed at 0 CHF/kWh.",
                entry.entry_id,
            )

    _LOGGER.info("Migrating configuration entry to version %s", entry.version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Groupe-E Energy from a config entry.

    Lets ConfigEntryNotReady propagate so Home Assistant retries setup with
    exponential backoff when the API is unreachable.
    """
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    premise = entry.data[CONF_PREMISE]
    partner = entry.data[CONF_PARTNER]

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
        """Handle the reset_statistics service call.

        Supports three modes:
        - No args: preserve nothing before Jan 1 of current year, rebuild from there.
        - rebuild_since=<date>: preserve data before that date, recalculate from there.
        - clear_all=True: wipe everything, rebuild from Jan 1 of current year.
        """
        entry_id = call.data["entry_id"]

        coordinator: GroupeEDataUpdateCoordinator | None = hass.data.get(
            DOMAIN, {}
        ).get(entry_id)

        if coordinator is None:
            _LOGGER.error("Config entry %s not found", entry_id)
            return

        rebuild_since = call.data.get("rebuild_since")
        clear_all = call.data.get("clear_all", False)
        local_tz = ZoneInfo(TARIFF_TIMEZONE)
        now_local = datetime.now(local_tz)

        if clear_all:
            rebuild_dt = datetime.min.replace(tzinfo=timezone.utc)
        elif rebuild_since is not None:
            if rebuild_since.tzinfo is None:
                rebuild_since = rebuild_since.replace(tzinfo=local_tz)
            rebuild_dt = (
                rebuild_since.astimezone(local_tz)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(timezone.utc)
            )
        else:
            rebuild_dt = now_local.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            ).astimezone(timezone.utc)

        await coordinator.async_schedule_rebuild(rebuild_dt)

        _LOGGER.warning(
            "Resetting Groupe-E statistics for entry %s (rebuild_since=%s)",
            entry_id,
            rebuild_dt,
        )

        hass.async_create_background_task(
            coordinator.async_request_refresh(),
            f"groupe_e_reset_statistics_{entry_id}",
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_STATISTICS,
        _handle_reset_statistics,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): vol.Coerce(str),
                vol.Optional("rebuild_since"): vol.Coerce(datetime.fromisoformat),
                vol.Optional("clear_all", default=False): bool,
            }
        ),
    )

    return True
