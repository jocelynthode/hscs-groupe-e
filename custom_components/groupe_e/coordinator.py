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
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.unit_conversion import EnergyConverter

from .api import GroupeEAPI, GroupeEApiError, GroupeEAuthError
from .const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_STAT_ID_DISCRIMINATOR,
    CONF_TARIFF_SCHEDULE,
    DEFAULT_TARIFF_SCHEDULE,
    DOMAIN,
    TARIFF_TIMEZONE,
)
from .models import Measurement, SmartMeterResponse

_LOGGER = logging.getLogger(__name__)

QUARTER_HOUR_HOURS = 0.25
_LOCAL_TZ = ZoneInfo(TARIFF_TIMEZONE)


def _is_high_tariff(dt: datetime, ht_periods: list[dict]) -> bool:
    """Check if a datetime falls within a high-tariff period.

    Each period is a dict with 'start' and 'end' hours (exclusive end); hours
    may be fractional (e.g. 7.5 for 07:30).

    NOTE on granularity: callers classify a whole hour of quarter-hourly data
    by its top-of-hour local time only. Sub-hour period boundaries (e.g.
    07:30-12:00) are therefore not honored for statistics — the entire hour
    starting at 07:00 is classified as NT even though 07:30 onward should be
    HT. Keep tariff schedules aligned to full hours for correct statistics.
    """
    minutes = dt.hour * 60 + dt.minute
    for period in ht_periods:
        start_minutes = period["start"] * 60
        end_minutes = period["end"] * 60
        if start_minutes <= minutes < end_minutes:
            return True
    return False


def measurements_to_statistics_by_tariff(
    measurements: list[Measurement],
    last_stats_time: float | None,
    last_nt_sum: float,
    last_ht_sum: float,
    last_total_sum: float,
    last_cost_sum: float,
    ht_periods: list[dict],
    local_tz: ZoneInfo,
    nt_price: float,
    ht_price: float,
) -> tuple[
    list[StatisticData], list[StatisticData], list[StatisticData], list[StatisticData]
]:
    """Aggregate quarter-hourly API measurements into hourly NT/HT/total/cost StatisticData lists.

    HA requires timestamps at the top of the hour. Each hour's 4 quarter-hourly
    measurements are summed into a single kWh value, classified by tariff based
    on local time at the hour boundary (see _is_high_tariff for the sub-hour
    granularity limitation).

    Every hour produces an entry in ALL FOUR lists. The inactive tariff gets
    state=0 and sum=previous_sum, keeping both cumulative series gap-free
    so the Energy Dashboard never sees a flat line or missing data.
    """
    parsed = []
    for entry in measurements:
        start = entry.timestamp
        value = entry.value
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
    total_statistics: list[StatisticData] = []
    cost_statistics: list[StatisticData] = []
    for hour_start, values in sorted(hours.items()):
        hourly_kwh = sum(v * QUARTER_HOUR_HOURS for v in values)
        local_time = hour_start.astimezone(local_tz)
        is_ht = _is_high_tariff(local_time, ht_periods)

        if is_ht:
            price = ht_price
            last_ht_sum += hourly_kwh
            ht_statistics.append(
                StatisticData(start=hour_start, state=hourly_kwh, sum=last_ht_sum)
            )
            # Inactive tariff (NT) gets state=0 but sum stays at last_nt_sum
            # to keep the cumulative series gap-free for the Energy Dashboard.
            nt_statistics.append(
                StatisticData(start=hour_start, state=0.0, sum=last_nt_sum)
            )
        else:
            price = nt_price
            last_nt_sum += hourly_kwh
            nt_statistics.append(
                StatisticData(start=hour_start, state=hourly_kwh, sum=last_nt_sum)
            )
            # Inactive tariff (HT) gets state=0 but sum stays at last_ht_sum
            # to keep the cumulative series gap-free for the Energy Dashboard.
            ht_statistics.append(
                StatisticData(start=hour_start, state=0.0, sum=last_ht_sum)
            )

        last_total_sum += hourly_kwh
        total_statistics.append(
            StatisticData(start=hour_start, state=hourly_kwh, sum=last_total_sum)
        )

        hourly_cost = round(hourly_kwh * price, 4)
        last_cost_sum += hourly_cost
        cost_statistics.append(
            StatisticData(start=hour_start, state=hourly_cost, sum=last_cost_sum)
        )

    return nt_statistics, ht_statistics, total_statistics, cost_statistics


class GroupeEDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Groupe-E data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: GroupeEAPI,
        premise: str,
        partner: str,
        update_interval: int,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator with API client and premise details.

        Sets up statistic IDs, in-memory latest sums for sensors,
        and the rebuild_since trigger for partial/full data resets.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(hours=update_interval),
        )
        self.config_entry = config_entry
        self.api = api
        self.premise = premise
        self.partner = partner
        discriminator = (
            config_entry.data.get(CONF_STAT_ID_DISCRIMINATOR, premise) or premise
        )
        base_id = (
            f"{DOMAIN}:energy_consumption_{discriminator.replace('-', '_')}".lower()
        )
        self._label = discriminator
        self._normal_tariff_qh_id = f"{base_id}_normal_tariff"
        self._high_tariff_qh_id = f"{base_id}_high_tariff"
        self._total_energy_qh_id = f"{base_id}_total"
        self._cost_qh_id = f"{base_id}_cost"
        self._latest_nt_sum: float | None = None
        self._latest_ht_sum: float | None = None
        self._latest_total_sum: float | None = None
        self._latest_cost_sum: float | None = None
        self._rebuild_since: datetime | None = None
        # Cache for the parsed tariff schedule (invalidated on value change,
        # see _get_ht_periods). Options updates recreate the coordinator via
        # reload, but the identity check also covers direct option mutations.
        self._cached_schedule_raw: Any = None
        self._cached_schedule: list[dict] = []
        _LOGGER.debug(
            "Initialized coordinator: premise=%s, statistic_ids=%s, %s, %s, %s",
            premise,
            self._normal_tariff_qh_id,
            self._high_tariff_qh_id,
            self._total_energy_qh_id,
            self._cost_qh_id,
        )

    @property
    def statistic_ids(self) -> list[str]:
        """Return all Groupe-E external statistic IDs."""
        return [
            self._normal_tariff_qh_id,
            self._high_tariff_qh_id,
            self._total_energy_qh_id,
            self._cost_qh_id,
        ]

    def statistic_id_for(self, suffix: str) -> str:
        """Return the statistic ID for a sensor suffix (e.g. 'normal_tariff')."""
        return getattr(self, f"_{suffix}_qh_id")

    @property
    def label(self) -> str:
        """Return the human-readable discriminator for this entry."""
        return self._label

    @property
    def latest_sums(self) -> dict[str, float | None]:
        """Return the latest cumulative sums for the sensor platform."""
        return {
            "nt": self._latest_nt_sum,
            "ht": self._latest_ht_sum,
            "total": self._latest_total_sum,
            "cost": self._latest_cost_sum,
        }

    @property
    def current_tariff(self) -> str:
        """Return 'normal' or 'high' based on current local time."""
        now_local = datetime.now(_LOCAL_TZ)
        return (
            "high" if _is_high_tariff(now_local, self._get_ht_periods()) else "normal"
        )

    @property
    def current_price(self) -> float:
        """Return the current NT or HT price in CHF/kWh."""
        prices = self._get_prices()
        return prices["ht"] if self.current_tariff == "high" else prices["nt"]

    async def async_schedule_rebuild(self, rebuild_since: datetime) -> None:
        """Schedule a statistics rebuild from the given UTC instant.

        Pass ``datetime.min`` (UTC-aware) to wipe everything and rebuild from
        the start of the current year.
        """
        self._rebuild_since = rebuild_since

    async def _async_get_last_stat(self, statistic_id: str) -> Any:
        """Fetch the latest statistic from the recorder for the given statistic ID."""
        return await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            True,
            {"sum"},
        )

    def _get_ht_periods(self) -> list[dict]:
        """Get the high-tariff periods from config options.

        Parsed values are cached and only re-parsed when the underlying option
        value actually changes (options updates recreate the coordinator, but
        this also covers direct option mutations without a reload).
        """
        schedule = self.config_entry.options.get(
            CONF_TARIFF_SCHEDULE, DEFAULT_TARIFF_SCHEDULE
        )
        if schedule is self._cached_schedule_raw:
            return self._cached_schedule
        if isinstance(schedule, str):
            try:
                schedule = json.loads(schedule)
            except (json.JSONDecodeError, TypeError):
                schedule = DEFAULT_TARIFF_SCHEDULE
        self._cached_schedule_raw = schedule
        self._cached_schedule = schedule
        return schedule

    def _get_prices(self) -> dict[str, float]:
        """Get the NT and HT prices from config options or data."""
        nt = self.config_entry.options.get(
            CONF_NT_PRICE
        ) or self.config_entry.data.get(CONF_NT_PRICE, 0)
        ht = self.config_entry.options.get(
            CONF_HT_PRICE
        ) or self.config_entry.data.get(CONF_HT_PRICE, 0)
        return {
            "nt": float(nt),
            "ht": float(ht),
        }

    async def _async_read_stats_before(self, cutoff: datetime) -> dict[str, list[dict]]:
        """Read all stored statistics before cutoff for every statistic ID.

        Used during partial rebuild: we need the cumulative sums up to the cutoff
        so new data can continue from the correct base after clearing and re-inserting.
        """
        return await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            datetime.fromtimestamp(0, tz=timezone.utc),
            cutoff,
            set(self.statistic_ids),
            "hour",
            None,
            {"sum"},
        )

    async def _async_update_data(self):
        """Fetch smart meter data and insert statistics for quarter-hourly consumption and tariff split.

        Four code paths:
        1. rebuild_since=datetime.min — full clear: wipe all, fetch from year start.
        2. rebuild_since=<date> — partial rebuild: preserve pre-date stats, recalculate from date.
        3. NT/HT last timestamps diverge — clear all stats, rebuild from year start.
        4. No rebuild — normal incremental: fetch from the last stored statistic timestamp.
        """
        try:
            now_local = datetime.now(_LOCAL_TZ)
            today_start_local = now_local.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_start = today_start_local.astimezone(timezone.utc)

            year_start_local = now_local.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            year_start = year_start_local.astimezone(timezone.utc)

            rebuild_since = self._rebuild_since
            self._rebuild_since = None

            if rebuild_since is not None and rebuild_since == datetime.min.replace(
                tzinfo=timezone.utc
            ):
                # Full clear: wipe everything, skip preservation, rebuild from year start.
                _LOGGER.warning(
                    "Full statistics clear requested; rebuilding from %s", year_start
                )
                get_instance(self.hass).async_clear_statistics(self.statistic_ids)
                last_nt_stat = None
                last_ht_stat = None
                last_total_stat = None
                last_cost_stat = None
                start = year_start
            elif rebuild_since is not None:
                # Partial rebuild: preserve stats before the cutoff, clear everything,
                # re-insert preserved data, then fetch and recalculate from rebuild_since onward.
                _LOGGER.warning(
                    "Partial statistics rebuild requested from %s", rebuild_since
                )
                pre_stats = await self._async_read_stats_before(rebuild_since)
                get_instance(self.hass).async_clear_statistics(self.statistic_ids)
                if pre_stats:
                    self._reinsert_pre_stats(pre_stats)
                nt_pre = (
                    pre_stats.get(self._normal_tariff_qh_id, []) if pre_stats else []
                )
                if nt_pre:
                    ht_pre = (
                        pre_stats.get(self._high_tariff_qh_id, []) if pre_stats else []
                    )
                    total_pre = (
                        pre_stats.get(self._total_energy_qh_id, []) if pre_stats else []
                    )
                    cost_pre = pre_stats.get(self._cost_qh_id, []) if pre_stats else []
                    # Use the last entry of each preserved stat as the cumulative base
                    # so new data continues seamlessly from the old.
                    last_nt_stat = {self._normal_tariff_qh_id: [nt_pre[-1]]}
                    last_ht_stat = (
                        {self._high_tariff_qh_id: [ht_pre[-1]]} if ht_pre else None
                    )
                    last_total_stat = (
                        {self._total_energy_qh_id: [total_pre[-1]]}
                        if total_pre
                        else None
                    )
                    last_cost_stat = (
                        {self._cost_qh_id: [cost_pre[-1]]} if cost_pre else None
                    )
                else:
                    last_nt_stat = None
                    last_ht_stat = None
                    last_total_stat = None
                    last_cost_stat = None
                start = rebuild_since
            else:
                last_nt_stat = await self._async_get_last_stat(
                    self._normal_tariff_qh_id
                )
                last_ht_stat = await self._async_get_last_stat(self._high_tariff_qh_id)
                last_total_stat = await self._async_get_last_stat(
                    self._total_energy_qh_id
                )
                last_cost_stat = await self._async_get_last_stat(self._cost_qh_id)

                nt_has_data = last_nt_stat and self._normal_tariff_qh_id in last_nt_stat
                ht_has_data = last_ht_stat and self._high_tariff_qh_id in last_ht_stat

                if nt_has_data and ht_has_data:
                    nt_last_start = last_nt_stat[self._normal_tariff_qh_id][0]["start"]
                    ht_last_start = last_ht_stat[self._high_tariff_qh_id][0]["start"]
                    if nt_last_start != ht_last_start:
                        _LOGGER.warning(
                            "NT and HT statistics out of sync: NT=%s, HT=%s. Clearing and rebuilding from start of year.",
                            datetime.fromtimestamp(nt_last_start, tz=timezone.utc),
                            datetime.fromtimestamp(ht_last_start, tz=timezone.utc),
                        )
                        # Clear existing stats first so re-inserted hours don't
                        # conflict with stale entries already in the recorder.
                        get_instance(self.hass).async_clear_statistics(
                            self.statistic_ids
                        )
                        start = year_start
                        last_nt_stat = None
                        last_ht_stat = None
                        last_total_stat = None
                        last_cost_stat = None
                    else:
                        start = datetime.fromtimestamp(nt_last_start, tz=timezone.utc)
                        _LOGGER.debug("All stats present, requesting from %s", start)
                else:
                    start = year_start
                    _LOGGER.debug(
                        "Missing some tariff stats, rebuilding from %s",
                        start,
                    )
                    last_nt_stat = None
                    last_ht_stat = None
                    last_total_stat = None
                    last_cost_stat = None

            if start >= today_start:
                _LOGGER.debug("Statistics already up to date, skipping API request")
                return self.latest_sums

            detailed_data = await self.api.get_smartmeter_data(
                self.premise,
                self.partner,
                start,
                today_start,
                resolution="quarter-hourly",
            )

            if detailed_data.channels:
                await self._insert_quarter_hourly_statistics(
                    detailed_data,
                    last_nt_stat,
                    last_ht_stat,
                    last_total_stat,
                    last_cost_stat,
                )
            else:
                _LOGGER.debug(
                    "No quarter-hourly data returned for window %s to %s",
                    start,
                    today_start,
                )

            return self.latest_sums
        except (GroupeEAuthError, GroupeEApiError) as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            _LOGGER.exception("Unexpected error processing Groupe-E data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _insert_quarter_hourly_statistics(
        self,
        response: SmartMeterResponse,
        last_nt_stat,
        last_ht_stat,
        last_total_stat,
        last_cost_stat,
    ) -> None:
        """Split quarter-hourly measurements into NT/HT/total/cost statistics and insert them.

        Each 15-min measurement (kW) is converted to kWh, classified as normal or high tariff
        based on local time (Europe/Zurich) and the configured tariff periods, then inserted
        into the recorder as running-sum statistic series for energy (NT, HT, total) and cost.
        """
        # Aggregate measurements from ALL channels that carry data. The API may
        # return several channels (e.g. one per tariff); dropping any of them
        # would silently under-count consumption.
        channels = response.measurement_channels
        if not channels:
            _LOGGER.debug(
                "No measurementData in channel response (valid no-data response)"
            )
            return
        if len(channels) > 1:
            _LOGGER.debug(
                "Aggregating %d channels with measurements: %s",
                len(channels),
                [c.id for c in channels],
            )
        measurements = [
            m for c in channels for m in c.data.measurements
        ]

        ht_periods = self._get_ht_periods()
        prices = self._get_prices()

        last_stats_time = None
        nt_running_sum = 0.0
        ht_running_sum = 0.0
        total_running_sum = 0.0
        cost_running_sum = 0.0
        if last_nt_stat and self._normal_tariff_qh_id in last_nt_stat:
            last_stats_time = last_nt_stat[self._normal_tariff_qh_id][0]["start"]
            nt_running_sum = last_nt_stat[self._normal_tariff_qh_id][0]["sum"]
        if last_ht_stat and self._high_tariff_qh_id in last_ht_stat:
            ht_running_sum = last_ht_stat[self._high_tariff_qh_id][0]["sum"]
        if last_total_stat and self._total_energy_qh_id in last_total_stat:
            total_running_sum = last_total_stat[self._total_energy_qh_id][0]["sum"]
        if last_cost_stat and self._cost_qh_id in last_cost_stat:
            cost_running_sum = last_cost_stat[self._cost_qh_id][0]["sum"]

        nt_statistics, ht_statistics, total_statistics, cost_statistics = (
            measurements_to_statistics_by_tariff(
                measurements,
                last_stats_time,
                nt_running_sum,
                ht_running_sum,
                total_running_sum,
                cost_running_sum,
                ht_periods,
                _LOCAL_TZ,
                prices["nt"],
                prices["ht"],
            )
        )

        if measurements and not any(
            (nt_statistics, ht_statistics, total_statistics, cost_statistics)
        ):
            # Every received measurement fell at/before the resume point, so
            # nothing new was inserted. Log so this isn't mistaken for an
            # empty API response.
            _LOGGER.debug(
                "Received %d measurements but all are at/before the resume "
                "point; nothing new to insert",
                len(measurements),
            )

        self._insert_statistics(
            nt_statistics,
            self._normal_tariff_qh_id,
            "Normal Tariff",
            "kWh",
            EnergyConverter.UNIT_CLASS,
        )
        self._latest_nt_sum = (
            nt_statistics[-1]["sum"] if nt_statistics else nt_running_sum
        )
        self._insert_statistics(
            ht_statistics,
            self._high_tariff_qh_id,
            "High Tariff",
            "kWh",
            EnergyConverter.UNIT_CLASS,
        )
        self._latest_ht_sum = (
            ht_statistics[-1]["sum"] if ht_statistics else ht_running_sum
        )
        self._insert_statistics(
            total_statistics,
            self._total_energy_qh_id,
            "Grid Energy",
            "kWh",
            EnergyConverter.UNIT_CLASS,
        )
        self._latest_total_sum = (
            total_statistics[-1]["sum"] if total_statistics else total_running_sum
        )
        self._insert_statistics(
            cost_statistics, self._cost_qh_id, "Energy Cost", "CHF", None
        )
        self._latest_cost_sum = (
            cost_statistics[-1]["sum"] if cost_statistics else cost_running_sum
        )

    def _reinsert_pre_stats(self, pre_stats: dict[str, list[dict]]) -> None:
        """Re-insert pre-rebuild statistics after clearing.

        The recorder's async_clear_statistics removes ALL data for the given IDs,
        including data before the rebuild cutoff. We need to put that data back
        so the Energy Dashboard retains its history up to the cutoff point.

        When entries lack a 'state' field (common with statistics_during_period),
        we derive it from consecutive sum differences.
        """
        labels = {
            self._normal_tariff_qh_id: (
                "Normal Tariff",
                "kWh",
                EnergyConverter.UNIT_CLASS,
            ),
            self._high_tariff_qh_id: ("High Tariff", "kWh", EnergyConverter.UNIT_CLASS),
            self._total_energy_qh_id: (
                "Grid Energy",
                "kWh",
                EnergyConverter.UNIT_CLASS,
            ),
            self._cost_qh_id: ("Energy Cost", "CHF", None),
        }
        for stat_id, entries in pre_stats.items():
            if stat_id not in labels or not entries:
                continue
            label, unit, unit_class = labels[stat_id]
            entries.sort(
                key=lambda e: (
                    e["start"]
                    if isinstance(e["start"], datetime)
                    else datetime.fromtimestamp(e["start"], tz=timezone.utc)
                )
            )
            prev_sum = 0.0
            statistics: list[StatisticData] = []
            for e in entries:
                start = e["start"]
                if isinstance(start, (int, float)):
                    start = datetime.fromtimestamp(start, tz=timezone.utc)
                s = e["sum"]
                state = e.get("state", s - prev_sum)
                statistics.append(StatisticData(start=start, state=state, sum=s))
                prev_sum = s
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"Groupe-E {label} {self.premise}",
                source=DOMAIN,
                statistic_id=stat_id,
                unit_class=unit_class,
                unit_of_measurement=unit,
            )
            _LOGGER.debug(
                "Re-inserting %d pre-rebuild entries for %s (last sum=%.4f)",
                len(statistics),
                stat_id,
                statistics[-1]["sum"],
            )
            async_add_external_statistics(self.hass, metadata, statistics)

    def _insert_statistics(
        self,
        statistics: list[StatisticData],
        statistic_id: str,
        label: str,
        unit: str,
        unit_class: str | None,
    ) -> None:
        """Insert a list of StatisticData into the recorder."""
        if not statistics:
            return
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Groupe-E {label} {self.premise}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        )
        _LOGGER.debug(
            "Adding %d entries for %s (sum=%.4f)",
            len(statistics),
            statistic_id,
            statistics[-1]["sum"],
        )
        async_add_external_statistics(self.hass, metadata, statistics)
