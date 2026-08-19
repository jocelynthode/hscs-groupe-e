"""DataUpdateCoordinator for Groupe-E."""

import logging
from datetime import datetime, timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _sum_channel_values(data, today_ts=None):
    """Sum all measurement values from API response channels.

    The API returns separate channels (NT, HT) that both need to be summed.
    If today_ts is set, only entries before that timestamp are counted.
    """
    total = 0
    if not data or not isinstance(data, list):
        return total
    for item in data:
        measurements = item.get("data", {}).get("measurementData", [])
        for entry in measurements:
            ts = entry.get("timestamp", 0)
            if today_ts is not None and ts >= today_ts:
                continue
            total += entry.get("value", 0)
    return total


class GroupeEDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Groupe-E data."""

    def __init__(self, hass, api, premise, partner, update_interval, config_entry):
        """Initialize."""
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
        """Fetch data from API."""
        try:
            now = datetime.now()
            start_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            today_ts = int(today_start.timestamp() * 1000)
            yesterday_ts = int(yesterday_start.timestamp() * 1000)

            # Fetch historical daily data
            historical_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, start_year, now, resolution="daily"
            )

            # Fetch today's quarter-hourly data
            today_detailed_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, today_start, now, resolution="quarter-hourly"
            )

            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            yearly_consumption = 0
            daily_consumption = 0
            yesterday_consumption = 0
            monthly_consumption = 0
            found_historical = False
            found_detailed = False

            today_ts = int(today_start.timestamp() * 1000)
            yesterday_ts = int(yesterday_start.timestamp() * 1000)
            month_ts = int(month_start.timestamp() * 1000)

            has_detailed_data = False
            if today_detailed_data and isinstance(today_detailed_data, list):
                for item in today_detailed_data:
                    if item.get("data", {}).get("measurementData", []):
                        has_detailed_data = True
                        break

            if historical_data and isinstance(historical_data, list):
                found_historical = True
                for item in historical_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    for entry in measurements:
                        ts = entry.get("timestamp", 0)
                        value = entry.get("value", 0)

                        _LOGGER.debug("Historical entry: ts=%s, value=%s", ts, value)

                        if ts < today_ts:
                            yearly_consumption += value
                        else:
                            if not has_detailed_data:
                                daily_consumption += value
                                yearly_consumption += value
                                found_detailed = True
                                _LOGGER.debug("Using historical daily value for today: %s", value)

                        if yesterday_ts <= ts < today_ts:
                            yesterday_consumption += value

                        if month_ts <= ts:
                            if ts < today_ts:
                                monthly_consumption += value
                            elif not has_detailed_data:
                                monthly_consumption += value

            if has_detailed_data:
                detailed_sum = 0
                for item in today_detailed_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    if measurements:
                        found_detailed = True
                        for entry in measurements:
                            ts = entry.get("timestamp", 0)
                            value = entry.get("value", 0)
                            # The API returns values in kW for 15-minute intervals.
                            # Divide by 4 to convert to kWh.
                            energy_value = value / 4
                            detailed_sum += energy_value

                if detailed_sum >= 0:
                    yearly_consumption += detailed_sum
                    daily_consumption = detailed_sum
                    monthly_consumption += detailed_sum
                    _LOGGER.debug("Today's detailed sum: %s", detailed_sum)

            if not found_historical and not found_detailed:
                _LOGGER.warning("No measurementData found in Groupe-E API response")
                return self.data if self.data else {
                    "yearly_consumption": 0,
                    "daily_consumption": 0,
                    "yesterday_consumption": 0,
                    "monthly_consumption": 0,
                }

            _LOGGER.debug(
                "Total: %s, Daily: %s, Yesterday: %s, Monthly: %s (historical: %s, detailed: %s)",
                yearly_consumption, daily_consumption, yesterday_consumption, monthly_consumption, found_historical, found_detailed
            )

            return {
                "yearly_consumption": round(yearly_consumption, 2),
                "daily_consumption": round(daily_consumption, 2),
                "yesterday_consumption": round(yesterday_consumption, 2),
                "monthly_consumption": round(monthly_consumption, 2),
            }
        except Exception as err:
            _LOGGER.error("Error communicating with Groupe-E API: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}")
