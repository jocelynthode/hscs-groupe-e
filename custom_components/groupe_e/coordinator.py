"""DataUpdateCoordinator for Groupe-E."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .api import GroupeEAuthError, GroupeEApiError

_LOGGER = logging.getLogger(__name__)


def _safe_float(value: Any) -> float:
    """Convert a value to float, returning 0.0 for non-numeric values."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        _LOGGER.debug(
            "Could not convert value to float: %s (type=%s)",
            value,
            type(value).__name__,
        )
        return 0.0


def _sum_measurements(
    data: list[dict[str, Any]] | None, before_ts: int | None = None
) -> float:
    """Sum measurement values across all channels.

    The API returns separate tariff channels (NT, HT) that both need to be summed
    for total consumption. Each channel contains measurements in the resolved unit
    (kWh for monthly/daily, kW for quarter-hourly).

    If before_ts is set, only entries with timestamp < before_ts are counted
    (used to exclude today's data when splitting at midnight).
    """
    total = 0.0
    if not data or not isinstance(data, list):
        return total
    for item in data:
        for entry in item.get("data", {}).get("measurementData", []):
            ts = entry.get("timestamp", 0)
            if before_ts is not None and ts >= before_ts:
                continue
            total += _safe_float(entry.get("value"))
    return total


def _sum_kw_to_kwh(data: list[dict[str, Any]] | None) -> float:
    """Convert quarter-hourly kW measurements to kWh.

    The Groupe-E API returns quarter-hourly measurements in kW (instantaneous power).
    Each 15-minute interval represents kW * 0.25h = kWh of energy.
    """
    total = 0.0
    if not data or not isinstance(data, list):
        return total
    for item in data:
        for entry in item.get("data", {}).get("measurementData", []):
            total += _safe_float(entry.get("value")) / 4
    return total


def _get_latest_measurement(
    measurements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the measurement with the highest timestamp."""
    if not measurements:
        return None
    return max(measurements, key=lambda e: e.get("timestamp", 0))


def _has_measurements(data: list[dict[str, Any]] | None) -> bool:
    """Check if any channel in the response contains measurement entries."""
    if not data:
        return False
    return any(
        item.get("data", {}).get("measurementData", [])
        for item in data
    )


def _calculate_yesterday_consumption(
    daily_data: list[dict[str, Any]] | None,
    today_ts: int,
) -> float:
    """Sum daily measurements with timestamps before local midnight."""
    return _sum_measurements(daily_data, before_ts=today_ts)


def _calculate_daily_consumption(
    detailed_data: list[dict[str, Any]] | None,
    daily_data: list[dict[str, Any]] | None,
    yesterday_consumption: float,
) -> float:
    """Calculate today's consumption from quarter-hourly data, or fallback to daily."""
    if _has_measurements(detailed_data):
        return _sum_kw_to_kwh(detailed_data)
    fallback = _sum_measurements(daily_data) - yesterday_consumption
    return max(0.0, fallback)


def _calculate_monthly_consumption(
    monthly_data: list[dict[str, Any]] | None,
    daily_consumption: float,
) -> float:
    """Calculate current month consumption.

    The monthly API excludes today, so today's detailed data is added.
    """
    monthly = 0.0
    if not monthly_data or not isinstance(monthly_data, list):
        return monthly + daily_consumption
    for item in monthly_data:
        latest = _get_latest_measurement(
            item.get("data", {}).get("measurementData", [])
        )
        if latest is not None:
            monthly += _safe_float(latest.get("value"))
    return monthly + daily_consumption


def _calculate_yearly_consumption(
    monthly_data: list[dict[str, Any]] | None,
    daily_consumption: float,
) -> float:
    """Calculate yearly consumption from summed monthly channels plus today."""
    yearly = _sum_measurements(monthly_data)
    return yearly + daily_consumption


class GroupeEDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Groupe-E data."""

    def __init__(
        self,
        hass,
        api,
        premise: str,
        partner: str,
        update_interval: int,
        config_entry,
    ):
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval),
        )
        self.api = api
        self.premise = premise
        self.partner = partner

    async def _async_update_data(self):
        try:
            now = dt_util.now()
            start_year = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            today_ts = int(today_start.timestamp() * 1000)

            monthly_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, start_year, now, resolution="monthly"
            )

            daily_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, yesterday_start, now, resolution="daily"
            )

            detailed_data = await self.api.get_smartmeter_data(
                self.premise,
                self.partner,
                today_start,
                now,
                resolution="quarter-hourly",
            )

            if not monthly_data and not daily_data and not detailed_data:
                if self.data:
                    _LOGGER.warning(
                        "Groupe-E returned no data; keeping previous values"
                    )
                    return self.data
                raise UpdateFailed("Groupe-E returned no data")

            yesterday_consumption = _calculate_yesterday_consumption(
                daily_data, today_ts
            )
            daily_consumption = _calculate_daily_consumption(
                detailed_data, daily_data, yesterday_consumption
            )
            monthly_consumption = _calculate_monthly_consumption(
                monthly_data, daily_consumption
            )
            yearly_consumption = _calculate_yearly_consumption(
                monthly_data, daily_consumption
            )

            _LOGGER.debug(
                "Yearly: %s, Daily: %s, Yesterday: %s, Monthly: %s",
                yearly_consumption,
                daily_consumption,
                yesterday_consumption,
                monthly_consumption,
            )

            return {
                "yearly_consumption": round(yearly_consumption, 2),
                "daily_consumption": round(daily_consumption, 2),
                "yesterday_consumption": round(yesterday_consumption, 2),
                "monthly_consumption": round(monthly_consumption, 2),
            }
        except (GroupeEAuthError, GroupeEApiError) as err:
            _LOGGER.error("Groupe-E API error: %s", err)
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error processing Groupe-E data")
            raise UpdateFailed(f"Unexpected error: {err}") from err
