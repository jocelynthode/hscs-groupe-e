"""Tests for the Groupe-E coordinator calculation functions."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.groupe_e.coordinator import (
    _parse_timestamp_ms,
    _safe_float,
    _is_high_tariff,
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
        nt, ht = measurements_to_statistics_by_tariff([], None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH)
        assert nt == []
        assert ht == []

    def test_nt_measurement(self):
        # 12:30 UTC = 13:30 Europe/Zurich in January → NT (between HT periods)
        ts = int(
            datetime(2024, 1, 15, 12, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        measurements = [{"timestamp": ts, "value": 4.0}]
        nt, ht = measurements_to_statistics_by_tariff(measurements, None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 1
        assert len(ht) == 1
        assert [x["start"] for x in nt] == [x["start"] for x in ht]
        assert nt[0]["state"] == 1.0
        assert nt[0]["sum"] == 1.0
        assert ht[0]["state"] == 0.0
        assert ht[0]["sum"] == 0.0

    def test_ht_measurement(self):
        ts = datetime(2026, 8, 19, 7, 30, tzinfo=timezone.utc).timestamp() * 1000
        measurements = [{"timestamp": int(ts), "value": 4.0}]
        nt, ht = measurements_to_statistics_by_tariff(measurements, None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 1
        assert len(ht) == 1
        assert ht[0]["state"] == 1.0
        assert ht[0]["sum"] == 1.0
        assert nt[0]["state"] == 0.0
        assert nt[0]["sum"] == 0.0

    def test_mixed_periods(self):
        measures = [
            {"timestamp": int(datetime(2026, 8, 19, 3, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 1.0},
            {"timestamp": int(datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 2.0},
            {"timestamp": int(datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 3.0},
            {"timestamp": int(datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 4.0},
            {"timestamp": int(datetime(2026, 8, 19, 23, 30, tzinfo=timezone.utc).timestamp() * 1000), "value": 5.0},
        ]
        nt, ht = measurements_to_statistics_by_tariff(measures, None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 5
        assert len(ht) == 5
        assert [x["start"] for x in nt] == [x["start"] for x in ht]
        assert nt[0]["state"] == 0.25
        assert nt[0]["sum"] == 0.25
        assert ht[0]["state"] == 0.0
        assert ht[0]["sum"] == 0.0
        assert nt[1]["state"] == 0.0
        assert nt[1]["sum"] == 0.25
        assert ht[1]["state"] == 0.50
        assert ht[1]["sum"] == 0.50
        assert nt[2]["state"] == 0.75
        assert nt[2]["sum"] == 1.0
        assert ht[2]["state"] == 0.0
        assert ht[2]["sum"] == 0.50
        assert nt[3]["state"] == 0.0
        assert nt[3]["sum"] == 1.0
        assert ht[3]["state"] == 1.0
        assert ht[3]["sum"] == 1.50
        assert nt[4]["state"] == 1.25
        assert nt[4]["sum"] == 2.25
        assert ht[4]["state"] == 0.0
        assert ht[4]["sum"] == 1.50

    def test_cumulative_from_existing_sums(self):
        ts = int(datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc).timestamp() * 1000)
        measurements = [{"timestamp": ts, "value": 2.0}]
        nt, ht = measurements_to_statistics_by_tariff(measurements, None, 10.0, 20.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 0.0
        assert nt[0]["sum"] == 10.0
        assert ht[0]["state"] == 0.50
        assert ht[0]["sum"] == 20.50

    def test_single_cutoff_skips_before(self):
        cutoff = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc).timestamp()
        measures = [
            {"timestamp": int(datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 1.0},
            {"timestamp": int(datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 2.0},
        ]
        nt, ht = measurements_to_statistics_by_tariff(measures, cutoff, 5.0, 5.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["sum"] == 5.50
        assert ht[0]["state"] == 0.0

    def test_unsorted_measurements_are_sorted(self):
        measures = [
            {"timestamp": int(datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc).timestamp() * 1000), "value": 4.0},  # 19:00 CEST → HT
            {"timestamp": int(datetime(2026, 8, 19, 16, 45, tzinfo=timezone.utc).timestamp() * 1000), "value": 2.0},  # 18:45 CEST → HT
            {"timestamp": int(datetime(2026, 8, 19, 17, 15, tzinfo=timezone.utc).timestamp() * 1000), "value": 3.0},  # 19:15 CEST → HT
        ]
        nt, ht = measurements_to_statistics_by_tariff(measures, None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH)
        assert len(nt) == 3
        assert len(ht) == 3
        # All HT, so NT always 0. Sorted order: 16:45, 17:00, 17:15
        assert nt[0]["sum"] == 0.0
        assert ht[0]["state"] == 0.50
        assert ht[0]["sum"] == 0.50
        assert ht[1]["state"] == 1.0
        assert ht[1]["sum"] == 1.50
        assert ht[2]["state"] == 0.75
        assert ht[2]["sum"] == 2.25

    def test_tariff_uses_local_timezone(self):
        # 15:00 UTC = 17:00 Europe/Zurich in summer → HT
        ts = int(
            datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        nt, ht = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 0.0
        assert ht[0]["state"] == 1.0

    def test_summer_time_tariff(self):
        # 15:00 UTC = 17:00 CEST (summer) → HT
        ts = int(
            datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        _, ht = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH,
        )
        assert ht[0]["state"] == 1.0

    def test_winter_time_tariff(self):
        # 16:00 UTC = 17:00 CET (winter) → HT
        ts = int(
            datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        _, ht = measurements_to_statistics_by_tariff(
            [{"timestamp": ts, "value": 4.0}],
            None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH,
        )
        assert ht[0]["state"] == 1.0

    def test_cutoff_skips_equal_timestamp(self):
        cutoff = datetime(
            2026, 8, 19, 12, 0, tzinfo=timezone.utc
        ).timestamp()
        measures = [
            {
                "timestamp": int(
                    datetime(
                        2026, 8, 19, 12, 0, tzinfo=timezone.utc
                    ).timestamp() * 1000
                ),
                "value": 2.0,
            },
            {
                "timestamp": int(
                    datetime(
                        2026, 8, 19, 12, 15, tzinfo=timezone.utc
                    ).timestamp() * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht = measurements_to_statistics_by_tariff(
            measures, cutoff, 5.0, 5.0, DEFAULT_HT_PERIODS, ZURICH,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["sum"] == 6.0

    def test_invalid_measurements_are_skipped(self):
        measures = [
            {"timestamp": "invalid", "value": 4.0},
            {"timestamp": 1234567890000, "value": "abc"},
            {"timestamp": 1234567890000, "value": True},
            {
                "timestamp": int(
                    datetime(
                        2026, 8, 19, 10, 0, tzinfo=timezone.utc
                    ).timestamp() * 1000
                ),
                "value": 4.0,
            },
        ]
        nt, ht = measurements_to_statistics_by_tariff(
            measures, None, 0.0, 0.0, DEFAULT_HT_PERIODS, ZURICH,
        )
        assert len(nt) == 1
        assert len(ht) == 1
        assert nt[0]["state"] == 1.0
