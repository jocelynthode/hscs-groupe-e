"""DataUpdateCoordinator for Groupe-E."""
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

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
            # Fetch historical data (daily resolution) for the current year
            # This is more efficient and less likely to be truncated by the API
            start_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

            # Fetch historical daily data
            historical_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, start_year, now, resolution="daily"
            )

            # Fetch today's detailed data (quarter-hourly) for better accuracy for the daily sensor
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            today_detailed_data = await self.api.get_smartmeter_data(
                self.premise, self.partner, today_start, now, resolution="quarter-hourly"
            )

            # Fetch this month's data specifically (optional, but good for clarity)
            # Alternatively, we can extract this from historical_data if it's there
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            total_consumption = 0
            daily_consumption = 0
            yesterday_consumption = 0
            monthly_consumption = 0
            found_historical = False
            found_detailed = False

            # Sum up historical daily values (excluding today to avoid double counting if today is in historical)
            today_ts = int(today_start.timestamp() * 1000)
            yesterday_ts = int(yesterday_start.timestamp() * 1000)
            month_ts = int(month_start.timestamp() * 1000)

            # Keep track of timestamps we've already processed to avoid double counting
            # if the API returns duplicates in the list
            seen_historical_ts = set()
            seen_detailed_ts = set()

            # We need to distinguish between having a response and having data
            has_detailed_data = False
            if today_detailed_data and isinstance(today_detailed_data, list):
                for item in today_detailed_data:
                    if item.get("data", {}).get("measurementData", []):
                        has_detailed_data = True
                        break

            if historical_data and isinstance(historical_data, list):
                for item in historical_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    if measurements:
                        found_historical = True
                        for entry in measurements:
                            ts = entry.get("timestamp", 0)
                            if ts in seen_historical_ts:
                                continue
                            seen_historical_ts.add(ts)

                            value = entry.get("value", 0)

                            # Log values for debugging
                            _LOGGER.debug("Historical entry: ts=%s, value=%s", ts, value)

                            if ts < today_ts:
                                total_consumption += value
                            else:
                                # If today is in historical data, we can use it as fallback if detailed fails
                                if not has_detailed_data:
                                    daily_consumption += value
                                    total_consumption += value
                                    found_detailed = True # Mark as found to avoid warning
                                    _LOGGER.debug("Using historical daily value for today: %s", value)

                            # Calculate yesterday's consumption
                            if yesterday_ts <= ts < today_ts:
                                yesterday_consumption += value

                            # Calculate monthly consumption
                            if month_ts <= ts:
                                if ts < today_ts:
                                    monthly_consumption += value
                                elif not has_detailed_data:
                                    monthly_consumption += value

            # Sum up today's detailed values
            if has_detailed_data:
                detailed_sum = 0
                for item in today_detailed_data:
                    measurements = item.get("data", {}).get("measurementData", [])
                    if measurements:
                        found_detailed = True
                        for entry in measurements:
                            ts = entry.get("timestamp", 0)
                            if ts in seen_detailed_ts:
                                continue
                            seen_detailed_ts.add(ts)

                            value = entry.get("value", 0)
                            # The API returns values in kW (power) for 15-minute intervals.
                            # We need to divide by 4 to get kWh (energy).
                            # If it was already energy, we wouldn't see the 4x increase.
                            energy_value = value / 4
                            detailed_sum += energy_value

                if detailed_sum >= 0:
                    total_consumption += detailed_sum
                    daily_consumption = detailed_sum
                    monthly_consumption += detailed_sum
                    _LOGGER.debug("Today's detailed sum: %s", detailed_sum)

            if not found_historical and not found_detailed:
                _LOGGER.warning("No measurementData found in Groupe-E API response")
                return self.data if self.data else {
                    "total_consumption": 0,
                    "daily_consumption": 0,
                    "yesterday_consumption": 0,
                    "monthly_consumption": 0,
                }

            _LOGGER.debug(
                "Total: %s, Daily: %s, Yesterday: %s, Monthly: %s (historical: %s, detailed: %s)",
                total_consumption, daily_consumption, yesterday_consumption, monthly_consumption, found_historical, found_detailed
            )

            return {
                "total_consumption": round(total_consumption, 2),
                "daily_consumption": round(daily_consumption, 2),
                "yesterday_consumption": round(yesterday_consumption, 2),
                "monthly_consumption": round(monthly_consumption, 2),
            }
        except Exception as err:
            _LOGGER.error("Error communicating with Groupe-E API: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}")
