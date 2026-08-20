"""Tests for the Groupe-E coordinator calculation functions."""

from datetime import datetime, timedelta, timezone
from types import MethodType
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.groupe_e.coordinator import (
    GroupeEDataUpdateCoordinator,
    _is_high_tariff,
    _parse_timestamp_ms,
    _safe_float,
    measurements_to_statistics_by_tariff,
)

ZURICH = ZoneInfo("Europe/Zurich")


class TestSafeFloat:
    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_float(self):
        assert _safe_float(12.34) == 12.34

    def test_none(self):
        assert _safe_float(None) is None

    def test_string_numeric(self):
        assert _safe_float("56.78") == 56.78

    def test_string_non_numeric(self):
        assert _safe_float("abc") is None

    def test_empty_string(self):
        assert _safe_float("") is None

    def test_missing_key(self):
        assert _safe_float({}.get("nope")) is None

    def test_bool_true(self):
        assert _safe_float(True) is None

    def test_bool_false(self):
        assert _safe_float(False) is None

    def test_zero(self):
        assert _safe_float(0) == 0.0


class TestParseTimestampMs:
    def test_valid_milliseconds(self):
        # 2024-01-15T12:30:00Z in ms
        result = _parse_timestamp_ms(1705321800000)
        assert result == datetime(2024, 1, 15, 12, 30, tzinfo=timezone.utc)

    def test_epoch(self):
        result = _parse_timestamp_ms(0)
        assert result == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_none(self):
        assert _parse_timestamp_ms(None) is None

    def test_bool(self):
        assert _parse_timestamp_ms(True) is None

    def test_string(self):
        assert _parse_timestamp_ms("abc") is None

    def test_float_ms(self):
        result = _parse_timestamp_ms(1705321800000.5)
        assert isinstance(result, datetime)
        assert result.tzinfo is timezone.utc

    def test_negative(self):
        result = _parse_timestamp_ms(-1)
        assert result is not None
        assert result.tzinfo is timezone.utc

    def test_missing_key(self):
        assert _parse_timestamp_ms({}.get("ts")) is None


DEFAULT_HT_PERIODS = [{"start": 7, "end": 12}, {"start": 17, "end": 23}]


class TestIsHighTariff:
    def test_nt_at_midnight(self):
        dt = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is False

    def test_ht_at_0700(self):
        dt = datetime(2026, 8, 19, 7, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is True

    def test_ht_at_1159(self):
        dt = datetime(2026, 8, 19, 11, 59, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is True

    def test_nt_at_1200(self):
        dt = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is False

    def test_nt_at_1659(self):
        dt = datetime(2026, 8, 19, 16, 59, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is False

    def test_ht_at_1700(self):
        dt = datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is True

    def test_ht_at_2259(self):
        dt = datetime(2026, 8, 19, 22, 59, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is True

    def test_nt_at_2300(self):
        dt = datetime(2026, 8, 19, 23, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is False

    def test_nt_at_0630(self):
        dt = datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, DEFAULT_HT_PERIODS) is False

    def test_empty_periods(self):
        dt = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
        assert _is_high_tariff(dt, []) is False


class TestMeasurementsToStatisticsByTariff:
    def test_empty_measurements(self):
        nt, ht, total, cost = measurements_to_statistics_by_tariff(
            [], None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert nt == []
        assert ht == []
        assert total == []
        assert cost == []

    def test_single_hour_nt(self):
        ts = datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc)
        measurements = [{"timestamp": int(ts.timestamp() * 1000), "value": 4.0}]
        nt, ht, total, cost = measurements_to_statistics_by_tariff(
            measurements, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert len(total) == 1
        assert len(cost) == 1
        expected_hour = ts.replace(minute=0, second=0, microsecond=0)
        assert nt[0]["start"] == expected_hour
        assert nt[0]["state"] == 1.0
        assert nt[0]["sum"] == 1.0
        assert ht[0]["start"] == expected_hour
        assert ht[0]["state"] == 0.0
        assert ht[0]["sum"] == 0.0
        assert total[0]["state"] == 1.0
        assert total[0]["sum"] == 1.0
        assert cost[0]["state"] == 0.2
        assert cost[0]["sum"] == 0.2

    def test_single_hour_ht(self):
        ts = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        measurements = [{"timestamp": int(ts.timestamp() * 1000), "value": 4.0}]
        nt, ht, total, cost = measurements_to_statistics_by_tariff(
            measurements, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 1
        assert len(ht) == 1
        expected_hour = ts.replace(minute=0, second=0, microsecond=0)
        assert ht[0]["start"] == expected_hour
        assert ht[0]["state"] == 1.0
        assert ht[0]["sum"] == 1.0
        assert nt[0]["start"] == expected_hour
        assert nt[0]["state"] == 0.0
        assert nt[0]["sum"] == 0.0
        assert total[0]["state"] == 1.0
        assert cost[0]["state"] == 0.3
        assert cost[0]["sum"] == 0.3

    def test_four_qh_sum_to_hour(self):
        ts = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        hour_start_ts = int(ts.timestamp() * 1000)
        measurements = [
            {"timestamp": hour_start_ts, "value": 2.0},
            {"timestamp": hour_start_ts + 900000, "value": 3.0},
            {"timestamp": hour_start_ts + 1800000, "value": 1.0},
            {"timestamp": hour_start_ts + 2700000, "value": 4.0},
        ]
        nt, ht, total, _ = measurements_to_statistics_by_tariff(
            measurements, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 1
        assert len(ht) == 1
        total_kwh = (2.0 + 3.0 + 1.0 + 4.0) * 0.25
        assert ht[0]["state"] == total_kwh
        assert nt[0]["state"] == 0.0
        assert total[0]["state"] == total_kwh

    def test_mixed_hours_independent_tariffs(self):
        measures = [
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 3, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht, total, cost = measurements_to_statistics_by_tariff(
            measures, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 4
        assert len(ht) == 4
        assert len(total) == 4
        assert len(cost) == 4
        assert nt[0]["state"] == 1.0
        assert nt[0]["sum"] == 1.0
        assert ht[0]["state"] == 0.0
        assert ht[0]["sum"] == 0.0
        assert total[0]["state"] == 1.0
        assert total[0]["sum"] == 1.0
        assert cost[0]["state"] == 0.2
        assert cost[0]["sum"] == 0.2
        assert nt[1]["state"] == 0.0
        assert nt[1]["sum"] == 1.0
        assert ht[1]["state"] == 1.0
        assert ht[1]["sum"] == 1.0
        assert total[1]["state"] == 1.0
        assert total[1]["sum"] == 2.0
        assert cost[1]["state"] == 0.3
        assert cost[1]["sum"] == 0.5
        assert nt[2]["state"] == 1.0
        assert nt[2]["sum"] == 2.0
        assert ht[2]["state"] == 0.0
        assert ht[2]["sum"] == 1.0
        assert total[2]["state"] == 1.0
        assert total[2]["sum"] == 3.0
        assert cost[2]["state"] == 0.2
        assert cost[2]["sum"] == 0.7
        assert nt[3]["state"] == 0.0
        assert nt[3]["sum"] == 2.0
        assert ht[3]["state"] == 1.0
        assert ht[3]["sum"] == 2.0

    def test_cumulative_from_existing_sums(self):
        ts = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        measurements = [{"timestamp": int(ts.timestamp() * 1000), "value": 4.0}]
        nt, ht, total, cost = measurements_to_statistics_by_tariff(
            measurements,
            None,
            10.0,
            20.0,
            30.0,
            40.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 0.0
        assert nt[0]["sum"] == 10.0
        assert ht[0]["state"] == 1.0
        assert ht[0]["sum"] == 21.0
        assert total[0]["state"] == 1.0
        assert total[0]["sum"] == 31.0
        assert cost[0]["state"] == 0.3
        assert cost[0]["sum"] == 40.3

    def test_single_cutoff_skips_before(self):
        cutoff = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc).timestamp()
        measures = [
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht, total, _cost = measurements_to_statistics_by_tariff(
            measures, cutoff, 5.0, 5.0, 10.0, 1.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 1.0
        assert nt[0]["sum"] == 6.0
        assert ht[0]["state"] == 0.0
        assert total[0]["state"] == 1.0
        assert total[0]["sum"] == 11.0

    def test_unsorted_aggregated_by_hour(self):
        measures = [
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 16, 45, tzinfo=timezone.utc).timestamp()
                    * 1000
                ),
                "value": 4.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 17, 15, tzinfo=timezone.utc).timestamp()
                    * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht, total, _cost = measurements_to_statistics_by_tariff(
            measures, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert len(nt) == 2
        assert len(ht) == 2
        assert len(total) == 2
        assert ht[0]["state"] == 1.0
        assert nt[0]["state"] == 0.0
        assert total[0]["state"] == 1.0
        assert ht[1]["state"] == 2.0
        assert ht[1]["sum"] == 3.0
        assert nt[1]["state"] == 0.0
        assert total[1]["state"] == 2.0

    def test_tariff_uses_local_timezone(self):
        ts = int(datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        nt, ht, _total, _cost = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 0.0
        assert ht[0]["state"] == 1.0

    def test_summer_time_tariff(self):
        ts = int(datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        _, ht, _, _ = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert ht[0]["state"] == 1.0

    def test_winter_time_tariff(self):
        ts = int(datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
        _, ht, _, _ = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert ht[0]["state"] == 1.0

    def test_timestamps_at_top_of_hour(self):
        ts = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        measurements = [{"timestamp": int(ts.timestamp() * 1000), "value": 4.0}]
        nt, ht, _total, _cost = measurements_to_statistics_by_tariff(
            measurements, None, 0.0, 0.0, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH, 0.2, 0.3
        )
        assert nt[0]["start"].minute == 0
        assert nt[0]["start"].second == 0
        assert ht[0]["start"].minute == 0
        assert ht[0]["start"].second == 0

    def test_cutoff_skips_equal_timestamp(self):
        cutoff = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc).timestamp()
        measures = [
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 2.0,
            },
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 12, 15, tzinfo=timezone.utc).timestamp()
                    * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht, total, _cost = measurements_to_statistics_by_tariff(
            measures,
            cutoff,
            5.0,
            5.0,
            10.0,
            2.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["sum"] == 6.0
        assert total[0]["sum"] == 11.0

    def test_invalid_measurements_are_skipped(self):
        measures = [
            {"timestamp": "invalid", "value": 4.0},
            {"timestamp": 1234567890000, "value": "abc"},
            {"timestamp": 1234567890000, "value": True},
            {
                "timestamp": int(
                    datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc).timestamp() * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht, total, _cost = measurements_to_statistics_by_tariff(
            measures,
            None,
            0.0,
            0.0,
            0.0,
            0.0,
            DEFAULT_HT_PERIODS,
            ZURICH,
            0.2,
            0.3,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 1.0
        assert total[0]["state"] == 1.0


class TestReinsertPreStats:
    """Tests for _reinsert_pre_stats method."""

    @pytest.fixture
    def coordinator(self):
        """Create a mock coordinator with the real _reinsert_pre_stats bound."""
        coord = MagicMock(spec=GroupeEDataUpdateCoordinator)
        coord.premise = "283122"
        coord._normal_tariff_qh_id = "groupe_e:energy_consumption_283122_normal_tariff"
        coord._high_tariff_qh_id = "groupe_e:energy_consumption_283122_high_tariff"
        coord._total_energy_qh_id = "groupe_e:energy_consumption_283122_total"
        coord._cost_qh_id = "groupe_e:energy_consumption_283122_cost"
        coord.hass = MagicMock()
        coord._reinsert_pre_stats = MethodType(
            GroupeEDataUpdateCoordinator._reinsert_pre_stats, coord
        )
        return coord

    def test_empty_pre_stats(self, coordinator):
        pre_stats = {}
        with patch(
            "custom_components.groupe_e.coordinator.async_add_external_statistics"
        ) as mock_insert:
            coordinator._reinsert_pre_stats(pre_stats)
            mock_insert.assert_not_called()

    def test_single_entry_per_stat(self, coordinator):
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        pre_stats = {
            coordinator._normal_tariff_qh_id: [
                {"start": start, "sum": 100.0, "state": 100.0},
            ],
            coordinator._high_tariff_qh_id: [
                {"start": start, "sum": 200.0, "state": 200.0},
            ],
            coordinator._total_energy_qh_id: [
                {"start": start, "sum": 300.0, "state": 300.0},
            ],
            coordinator._cost_qh_id: [
                {"start": start, "sum": 50.0, "state": 50.0},
            ],
        }
        with patch(
            "custom_components.groupe_e.coordinator.async_add_external_statistics"
        ) as mock_insert:
            coordinator._reinsert_pre_stats(pre_stats)
            assert mock_insert.call_count == 4

    def test_multiple_entries_cumulative(self, coordinator):
        hour = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        entries = [
            {"start": hour + timedelta(hours=i), "sum": 100.0 + i * 10.0, "state": 10.0}
            for i in range(5)
        ]
        pre_stats = {coordinator._normal_tariff_qh_id: entries}
        with patch(
            "custom_components.groupe_e.coordinator.async_add_external_statistics"
        ) as mock_insert:
            coordinator._reinsert_pre_stats(pre_stats)
            mock_insert.assert_called_once()
            _hass, _metadata, statistics = mock_insert.call_args.args
            assert len(statistics) == 5
            for i, s in enumerate(statistics):
                assert s["start"] == hour + timedelta(hours=i)
                assert s["sum"] == 100.0 + i * 10.0


class TestInsertQuarterHourlyStatistics:
    """Tests for _insert_quarter_hourly_statistics method."""

    @pytest.fixture
    def coordinator(self):
        """Create a coordinator mock with the real method bound."""
        coord = MagicMock(spec=GroupeEDataUpdateCoordinator)
        coord.premise = "283122"
        coord._normal_tariff_qh_id = "groupe_e:energy_consumption_283122_normal_tariff"
        coord._high_tariff_qh_id = "groupe_e:energy_consumption_283122_high_tariff"
        coord._total_energy_qh_id = "groupe_e:energy_consumption_283122_total"
        coord._cost_qh_id = "groupe_e:energy_consumption_283122_cost"
        coord._get_ht_periods = MagicMock(return_value=DEFAULT_HT_PERIODS)
        coord._get_prices = MagicMock(return_value={"nt": 0.2, "ht": 0.3})
        coord._insert_statistics = MagicMock()
        coord._latest_nt_sum = None
        coord._latest_ht_sum = None
        coord._latest_total_sum = None
        coord._latest_cost_sum = None
        coord._insert_quarter_hourly_statistics = MethodType(
            GroupeEDataUpdateCoordinator._insert_quarter_hourly_statistics, coord
        )
        return coord

    async def test_sets_latest_sums_with_data(self, coordinator):
        ts = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        data = [
            {
                "data": {
                    "measurementData": [
                        {"timestamp": int(ts.timestamp() * 1000), "value": 4.0}
                    ]
                }
            }
        ]
        await coordinator._insert_quarter_hourly_statistics(
            data, None, None, None, None
        )
        assert coordinator._latest_nt_sum == 0.0
        assert coordinator._latest_ht_sum == 1.0
        assert coordinator._latest_total_sum == 1.0
        assert coordinator._latest_cost_sum == 0.3

    async def test_sets_latest_sums_from_existing(self, coordinator):
        existing_hour = datetime(2026, 8, 19, 7, 0, tzinfo=timezone.utc)
        new_hour = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
        nt_stat = {
            coordinator._normal_tariff_qh_id: [
                {"start": existing_hour.timestamp(), "sum": 50.0}
            ]
        }
        ht_stat = {
            coordinator._high_tariff_qh_id: [
                {"start": existing_hour.timestamp(), "sum": 60.0}
            ]
        }
        total_stat = {
            coordinator._total_energy_qh_id: [
                {"start": existing_hour.timestamp(), "sum": 110.0}
            ]
        }
        cost_stat = {
            coordinator._cost_qh_id: [{"start": existing_hour.timestamp(), "sum": 12.0}]
        }
        data = [
            {
                "data": {
                    "measurementData": [
                        {"timestamp": int(new_hour.timestamp() * 1000), "value": 4.0}
                    ]
                }
            }
        ]
        await coordinator._insert_quarter_hourly_statistics(
            data, nt_stat, ht_stat, total_stat, cost_stat
        )
        assert coordinator._latest_nt_sum == 50.0
        assert coordinator._latest_ht_sum == 61.0
        assert coordinator._latest_total_sum == 111.0

    async def test_no_channel_data(self, coordinator):
        await coordinator._insert_quarter_hourly_statistics([], None, None, None, None)
        coordinator._insert_statistics.assert_not_called()
        assert coordinator._latest_nt_sum is None
        assert coordinator._latest_ht_sum is None
        assert coordinator._latest_total_sum is None
        assert coordinator._latest_cost_sum is None

    async def test_no_measurements(self, coordinator):
        data = [{"data": {"measurementData": []}}]
        await coordinator._insert_quarter_hourly_statistics(
            data, None, None, None, None
        )
        coordinator._insert_statistics.assert_not_called()
        assert coordinator._latest_nt_sum is None
        assert coordinator._latest_ht_sum is None
        assert coordinator._latest_total_sum is None
        assert coordinator._latest_cost_sum is None
