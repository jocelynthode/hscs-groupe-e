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

            # Fetch monthly data (pre-aggregated) for yearly and monthly totals
            monthly_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, start_year, now, resolution="monthly"
            )

            # Fetch daily data for yesterday and today (just 2 days, compact)
            daily_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, yesterday_start, now, resolution="daily"
            )

            # Fetch quarter-hourly data for today's accurate reading
            today_detailed_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, today_start, now, resolution="quarter-hourly"
            )

            yearly_consumption = 0
            daily_consumption = 0
            yesterday_consumption = 0
            monthly_consumption = 0

            # Check if quarter-hourly data is available
            has_detailed_data = False
            if today_detailed_data and isinstance(today_detailed_data, list):
                for item in today_detailed_data:
                    if item.get("data", {}).get("measurementData", []):
                        has_detailed_data = True
                        break

            # Yearly: sum all monthly NT + HT values (Jan through current partial month)
            yearly_consumption = _sum_channel_values(monthly_data)

            # Monthly: current month-to-date from the last monthly entry per channel
            monthly_consumption = 0
            if monthly_data and isinstance(monthly_data, list):
                for item in monthly_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    if measurements:
                        # API returns months chronologically; last = current (partial) month
                        last_entry = measurements[-1]
                        monthly_consumption += last_entry.get("value", 0)

            # Yesterday: sum daily values with timestamps before local midnight
            yesterday_consumption = _sum_channel_values(daily_data, today_ts)

            # Today's consumption from quarter-hourly data, or fallback to daily
            daily_consumption = 0
            if has_detailed_data:
                for item in today_detailed_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    for entry in measurements:
                        value = entry.get("value", 0)
                        # The API returns values in kW for 15-minute intervals.
                        # Divide by 4 to convert to kWh.
                        daily_consumption += value / 4
                # Monthly API is updated once per day; add today's partial data
                yearly_consumption += daily_consumption
                monthly_consumption += daily_consumption
            else:
                # Fallback: total daily values (yesterday + today) minus yesterday
                daily_consumption = _sum_channel_values(daily_data, None) - yesterday_consumption

            found_monthly = (
                monthly_data
                and isinstance(monthly_data, list)
                and any(
                    item.get("data", {}).get("measurementData", [])
                    for item in monthly_data
                )
            )
            found_daily = (
                daily_data
                and isinstance(daily_data, list)
                and any(
                    item.get("data", {}).get("measurementData", [])
                    for item in daily_data
                )
            )

            if not found_monthly and not has_detailed_data and not found_daily:
                _LOGGER.warning("No measurementData found in Groupe-E API response")
                return self.data if self.data else {
                    "yearly_consumption": 0,
                    "daily_consumption": 0,
                    "yesterday_consumption": 0,
                    "monthly_consumption": 0,
                }

            _LOGGER.debug(
                "Yearly: %s, Daily: %s, Yesterday: %s, Monthly: %s",
                yearly_consumption, daily_consumption, yesterday_consumption, monthly_consumption
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
