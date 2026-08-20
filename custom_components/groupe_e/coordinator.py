"""DataUpdateCoordinator for Groupe-E."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import callback
from homeassistant.util.unit_conversion import EnergyConverter

from .const import (
    DOMAIN,
    CONF_STAT_ID_DISCRIMINATOR,
    CONF_TARIFF_SCHEDULE,
    DEFAULT_TARIFF_SCHEDULE,
    TARIFF_TIMEZONE,
)
from .api import GroupeEAuthError, GroupeEApiError

_LOGGER = logging.getLogger(__name__)

QUARTER_HOUR_HOURS = 0.25


def _safe_float(value: Any) -> float | None:
    """Convert value to float or return None if not safely convertible.

    Booleans are rejected to avoid True/False being interpreted as 1.0/0.0.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp_ms(ts: Any) -> datetime | None:
    """Parse a millisecond epoch value to a UTC-aware datetime.

    Returns None for missing, boolean, or non-numeric values.
    """
    if ts is None or isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return None


def _is_high_tariff(dt: datetime, ht_periods: list[dict]) -> bool:
    """Check if a datetime falls within a high-tariff period.

    Each period is a dict with 'start' and 'end' hours (exclusive end).
    """
    minutes = dt.hour * 60 + dt.minute
    for period in ht_periods:
        start_minutes = period["start"] * 60
        end_minutes = period["end"] * 60
        if start_minutes <= minutes < end_minutes:
            return True
    return False


def measurements_to_statistics_by_tariff(
    measurements: list[dict[str, Any]],
    last_stats_time: float | None,
    last_nt_sum: float,
    last_ht_sum: float,
    ht_periods: list[dict],
    local_tz: ZoneInfo,
) -> tuple[list[StatisticData], list[StatisticData]]:
    """Aggregate quarter-hourly API measurements into hourly NT/HT StatisticData lists.

    HA requires timestamps at the top of the hour. Each hour's 4 quarter-hourly
    measurements are summed into a single kWh value, classified by tariff based
    on local time at the hour boundary.

    Every hour produces an entry in BOTH lists. The inactive tariff gets
    state=0 and sum=previous_sum, keeping both cumulative series gap-free.
    """
    parsed = []
    for entry in measurements:
        start = _parse_timestamp_ms(entry.get("timestamp"))
        if start is None:
            _LOGGER.debug("Skipping measurement with invalid timestamp")
            continue
        value = _safe_float(entry.get("value"))
        if value is None:
            _LOGGER.debug("Skipping measurement with invalid value at %s", start)
            continue
        parsed.append((start, value))

    parsed.sort(key=lambda x: x[0])

    hours: dict[datetime, list[float]] = {}
    for start, value in parsed:
        if last_stats_time is not None and start.timestamp() <= last_stats_time:
            continue
        hour_start = start.replace(minute=0, second=0, microsecond=0)
        hours.setdefault(hour_start, []).append(value)

    nt_statistics: list[StatisticData] = []
    ht_statistics: list[StatisticData] = []
    for hour_start, values in sorted(hours.items()):
        hourly_kwh = sum(v * QUARTER_HOUR_HOURS for v in values)
        local_time = hour_start.astimezone(local_tz)
        is_ht = _is_high_tariff(local_time, ht_periods)

        if is_ht:
            last_ht_sum += hourly_kwh
            ht_statistics.append(
                StatisticData(start=hour_start, state=hourly_kwh, sum=last_ht_sum)
            )
            nt_statistics.append(
                StatisticData(start=hour_start, state=0.0, sum=last_nt_sum)
            )
        else:
            last_nt_sum += hourly_kwh
            nt_statistics.append(
                StatisticData(start=hour_start, state=hourly_kwh, sum=last_nt_sum)
            )
            ht_statistics.append(
                StatisticData(start=hour_start, state=0.0, sum=last_ht_sum)
            )
    return nt_statistics, ht_statistics


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
        """Initialize the coordinator with API client and premise details."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval),
        )
        self._config_entry = config_entry
        self.api = api
        self.premise = premise
        self.partner = partner
        discriminator = (
            config_entry.data.get(CONF_STAT_ID_DISCRIMINATOR, premise) or premise
        )
        base_id = (
            f"{DOMAIN}:energy_consumption_{discriminator.replace('-', '_')}".lower()
        )
        self._normal_tariff_qh_id = f"{base_id}_normal_tariff"
        self._high_tariff_qh_id = f"{base_id}_high_tariff"
        _LOGGER.debug(
            "Initialized coordinator: premise=%s, statistic_ids=%s, %s",
            premise,
            self._normal_tariff_qh_id,
            self._high_tariff_qh_id,
        )

        @callback
        def _dummy_listener() -> None:
            pass

        self.async_add_listener(_dummy_listener)

    async def _async_get_last_stat(self, statistic_id: str) -> Any:
        """Fetch the latest statistic from the recorder for the given statistic ID."""
        return await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            True,
            set(),
        )

    def _get_ht_periods(self) -> list[dict]:
        """Get the high-tariff periods from config options."""
        schedule = self._config_entry.options.get(
            CONF_TARIFF_SCHEDULE, DEFAULT_TARIFF_SCHEDULE
        )
        if isinstance(schedule, str):
            try:
                schedule = json.loads(schedule)
            except (json.JSONDecodeError, TypeError):
                schedule = DEFAULT_TARIFF_SCHEDULE
        return schedule

    async def _async_update_data(self):
        """Fetch smart meter data and insert statistics for quarter-hourly consumption and tariff split."""
        try:
            last_nt_stat = await self._async_get_last_stat(self._normal_tariff_qh_id)
            last_ht_stat = await self._async_get_last_stat(self._high_tariff_qh_id)

            local_tz = ZoneInfo(TARIFF_TIMEZONE)
            now_local = datetime.now(local_tz)
            today_start_local = now_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_start = today_start_local.astimezone(timezone.utc)

            nt_has_data = last_nt_stat and self._normal_tariff_qh_id in last_nt_stat
            ht_has_data = last_ht_stat and self._high_tariff_qh_id in last_ht_stat

            if nt_has_data and ht_has_data:
                nt_last_start = last_nt_stat[self._normal_tariff_qh_id][0]["start"]
                ht_last_start = last_ht_stat[self._high_tariff_qh_id][0]["start"]
                if nt_last_start != ht_last_start:
                    _LOGGER.warning(
                        "NT and HT statistics out of sync: NT=%s, HT=%s. Rebuilding from 365 days.",
                        datetime.fromtimestamp(nt_last_start, tz=timezone.utc),
                        datetime.fromtimestamp(ht_last_start, tz=timezone.utc),
                    )
                    start = today_start - timedelta(days=365)
                    last_nt_stat = None
                    last_ht_stat = None
                else:
                    start = datetime.fromtimestamp(nt_last_start, tz=timezone.utc)
                    _LOGGER.debug("All stats present, requesting from %s", start)
            else:
                start = today_start - timedelta(days=365)
                _LOGGER.debug(
                    "Missing some tariff stats, rebuilding both from %s",
                    start,
                )
                last_nt_stat = None
                last_ht_stat = None

            detailed_data = await self.api.get_smartmeter_data(
                self.premise,
                self.partner,
                start,
                today_start,
                resolution="quarter-hourly",
            )

            if detailed_data and isinstance(detailed_data, list):
                await self._insert_quarter_hourly_statistics(
                    detailed_data, last_nt_stat, last_ht_stat
                )
            else:
                _LOGGER.debug(
                    "No quarter-hourly data returned for window %s to %s",
                    start,
                    today_start,
                )

            return {}
        except (GroupeEAuthError, GroupeEApiError) as err:
            _LOGGER.error("Groupe-E API error: %s", err)
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error processing Groupe-E data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _insert_quarter_hourly_statistics(
        self, data: list[dict[str, Any]], last_nt_stat, last_ht_stat
    ) -> None:
        """Split quarter-hourly measurements into NT/HT statistics by tariff schedule and insert them.

        Each 15-min measurement (kW) is converted to kWh, classified as normal or high tariff
        based on local time (Europe/Zurich) and the configured tariff periods, then inserted
        into the recorder as two separate running-sum statistic series.
        """
        channel = data[0] if data else None
        if not channel:
            _LOGGER.debug("No channel data in API response")
            return
        measurements = channel.get("data", {}).get("measurementData", [])
        if not measurements:
            _LOGGER.debug("No measurementData in channel response")
            return

        ht_periods = self._get_ht_periods()

        last_stats_time = None
        nt_running_sum = 0.0
        ht_running_sum = 0.0
        if last_nt_stat and self._normal_tariff_qh_id in last_nt_stat:
            # NT is the canonical timestamp; HT always has the same timestamp
            last_stats_time = last_nt_stat[self._normal_tariff_qh_id][0]["start"]
            nt_running_sum = last_nt_stat[self._normal_tariff_qh_id][0]["sum"]
        if last_ht_stat and self._high_tariff_qh_id in last_ht_stat:
            ht_running_sum = last_ht_stat[self._high_tariff_qh_id][0]["sum"]

        nt_statistics, ht_statistics = measurements_to_statistics_by_tariff(
            measurements,
            last_stats_time,
            nt_running_sum,
            ht_running_sum,
            ht_periods,
            ZoneInfo(TARIFF_TIMEZONE),
        )

        if nt_statistics:
            nt_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"Groupe-E Normal Tariff {self.premise}",
                source=DOMAIN,
                statistic_id=self._normal_tariff_qh_id,
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement="kWh",
            )
            _LOGGER.debug(
                "Adding %d quarter-hourly NT entries for %s (sum=%.4f)",
                len(nt_statistics),
                self._normal_tariff_qh_id,
                nt_statistics[-1]["sum"],
            )
            async_add_external_statistics(self.hass, nt_metadata, nt_statistics)

        if ht_statistics:
            ht_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"Groupe-E High Tariff {self.premise}",
                source=DOMAIN,
                statistic_id=self._high_tariff_qh_id,
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement="kWh",
            )
            _LOGGER.debug(
                "Adding %d quarter-hourly HT entries for %s (sum=%.4f)",
                len(ht_statistics),
                self._high_tariff_qh_id,
                ht_statistics[-1]["sum"],
            )
            async_add_external_statistics(self.hass, ht_metadata, ht_statistics)
