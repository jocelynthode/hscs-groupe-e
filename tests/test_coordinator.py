"""Tests for the Groupe-E coordinator calculation functions."""

from datetime import datetime, timezone, timedelta
from custom_components.groupe_e.coordinator import (
    _safe_float,
    _sum_measurements,
    _sum_kw_to_kwh,
    _get_latest_measurement,
    _calculate_yesterday_consumption,
    _calculate_daily_consumption,
    _calculate_monthly_consumption,
    _calculate_yearly_consumption,
)


def _make_channel(channel_id, measurements):
    return {
        "id": channel_id,
        "data": {
            "measurementData": measurements,
        },
    }


def _m(ts, value, status="W"):
    return {"timestamp": ts, "value": value, "status": status}


# --- _safe_float ---


class TestSafeFloat:
    def test_int(self):
        assert _safe_float(42) == 42.0

    def test_float(self):
        assert _safe_float(12.34) == 12.34

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_string_numeric(self):
        assert _safe_float("56.78") == 56.78

    def test_string_non_numeric(self):
        assert _safe_float("abc") == 0.0

    def test_missing_key(self):
        assert _safe_float({}.get("nope")) == 0.0


# --- _sum_measurements ---


class TestSumMeasurements:
    def test_normal(self):
        ch = _make_channel(
            "NT",
            [
                _m(1000000, 10.0),
                _m(2000000, 20.0),
            ],
        )
        assert _sum_measurements([ch]) == 30.0

    def test_two_channels(self):
        nt = _make_channel("NT", [_m(1000000, 10.0)])
        ht = _make_channel("HT", [_m(1000000, 20.0)])
        assert _sum_measurements([nt, ht]) == 30.0

    def test_before_ts_excludes_later(self):
        ch = _make_channel(
            "NT",
            [
                _m(1000000, 10.0),
                _m(2000000, 20.0),
            ],
        )
        assert _sum_measurements([ch], before_ts=1500000) == 10.0

    def test_empty_list(self):
        assert _sum_measurements([]) == 0.0

    def test_none_data(self):
        assert _sum_measurements(None) == 0.0

    def test_missing_value_skipped(self):
        ch = _make_channel(
            "NT",
            [
                {"timestamp": 1000000},
                _m(2000000, 5.0),
            ],
        )
        assert _sum_measurements([ch]) == 5.0


# --- _sum_kw_to_kwh ---


class TestSumKwToKwh:
    def test_conversion(self):
        ch = _make_channel(
            "quarterHourly",
            [
                _m(1000000, 4.0),
                _m(1000000, 8.0),
            ],
        )
        # 4.0/4 + 8.0/4 = 1.0 + 2.0 = 3.0
        assert _sum_kw_to_kwh([ch]) == 3.0

    def test_empty(self):
        assert _sum_kw_to_kwh([]) == 0.0

    def test_none(self):
        assert _sum_kw_to_kwh(None) == 0.0


# --- _get_latest_measurement ---


class TestGetLatestMeasurement:
    def test_ordered(self):
        ms = [_m(1000, 1), _m(2000, 2), _m(3000, 3)]
        assert _get_latest_measurement(ms)["value"] == 3.0

    def test_unordered(self):
        ms = [_m(3000, 3), _m(1000, 1), _m(2000, 2)]
        assert _get_latest_measurement(ms)["value"] == 3.0

    def test_empty_list(self):
        assert _get_latest_measurement([]) is None

    def test_none(self):
        assert _get_latest_measurement(None) is None


# --- _calculate_yesterday_consumption ---


class TestCalculateYesterdayConsumption:
    def test_normal(self):
        today_ts = 2000000
        ch = _make_channel(
            "dailyNT",
            [
                _m(1000000, 10.0),  # yesterday
                _m(2000000, 5.0),  # today boundary -> excluded
                _m(3000000, 3.0),  # today -> excluded
            ],
        )
        assert _calculate_yesterday_consumption([ch], today_ts) == 10.0


# --- _calculate_daily_consumption ---


class TestCalculateDailyConsumption:
    def test_from_quarter_hourly(self):
        ch = _make_channel(
            "quarterHourly",
            [
                _m(1000000, 4.0),
                _m(2000000, 8.0),
            ],
        )
        # 4/4 + 8/4 = 3 kWh
        assert _calculate_daily_consumption([ch], None, 10.0) == 3.0

    def test_fallback_to_daily(self):
        ch = _make_channel(
            "dailyNT",
            [
                _m(1000000, 10.0),
                _m(2000000, 5.0),
            ],
        )
        assert _calculate_daily_consumption(None, [ch], 10.0) == 5.0


# --- _calculate_monthly_consumption ---


class TestCalculateMonthlyConsumption:
    def _make(self, now):
        """Build monthly data: 8 measurements (Jan–Aug), last is Aug."""
        measurements = [
            _m(1735689600000, 100),  # Jan 1
            _m(1738368000000, 90),  # Feb 1
            _m(1740787200000, 110),  # Mar 1
            _m(1743465600000, 95),  # Apr 1
            _m(1746057600000, 105),  # May 1
            _m(1748736000000, 85),  # Jun 1
            _m(1751328000000, 115),  # Jul 1
            _m(1754006400000, 70),  # Aug 1 (latest)
        ]
        nt = _make_channel("monthlyNT", measurements)
        ht = _make_channel("monthlyHT", measurements)
        return [nt, ht]

    def test_with_monthly_api_ok_and_no_daily(self):
        now = datetime(2025, 8, 15, tzinfo=timezone.utc)
        data = self._make(now)
        result = _calculate_monthly_consumption(data, 0)
        # last NT entry 70 + last HT entry 70 = 140
        assert result == 140.0

    def test_with_monthly_api_ok_and_daily_added(self):
        now = datetime(2025, 8, 15, tzinfo=timezone.utc)
        data = self._make(now)
        result = _calculate_monthly_consumption(data, 5.0)
        # 140 + 5 = 145
        assert result == 145.0

    def test_with_daily_fallback(self):
        now = datetime(2025, 8, 15, tzinfo=timezone.utc)
        current_month_ts = int(now.replace(day=1).timestamp() * 1000)
        daily_ch = _make_channel(
            "dailyNT",
            [
                _m(current_month_ts, 30),
                _m(current_month_ts + 86400000, 25),
            ],
        )
        result = _calculate_monthly_consumption([daily_ch], 0)
        # latest entry 25
        assert result == 25.0


# --- _calculate_yearly_consumption ---


class TestCalculateYearlyConsumption:
    def test_sum_all_channels_today_added(self):
        nt = _make_channel(
            "monthlyNT",
            [
                _m(1735689600000, 100),
                _m(1738368000000, 90),
            ],
        )
        ht = _make_channel(
            "monthlyHT",
            [
                _m(1735689600000, 150),
                _m(1738368000000, 110),
            ],
        )
        # 100+90+150+110 = 450, + 5 daily = 455
        assert _calculate_yearly_consumption([nt, ht], 5.0) == 455.0


# --- Integration: full flow ---


class TestFullCalculationFlow:
    """Test that the calculation pipeline produces correct expected values.

    Scenario:
      Yesterday = 20 kWh
      Today = 5 kWh (from quarter-hourly)
      Month = 100 kWh (from monthly API last entries)
      Year = 1000 kWh (sum of monthly channels)
    """

    def test_normal_day(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        today_ts = int(
            now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
        )
        yesterday_start = int(
            (now.replace(hour=0) - timedelta(days=1)).timestamp() * 1000
        )

        jan_ts = 1735689600000
        aug_ts = 1754006400000  # Aug 1

        nt = _make_channel("monthlyNT", [_m(jan_ts, 500), _m(aug_ts, 50)])
        ht = _make_channel("monthlyHT", [_m(jan_ts, 500), _m(aug_ts, 50)])
        monthly_data = [nt, ht]
        # _sum_measurements = 500+50+500+50 = 1100

        daily_ch = _make_channel(
            "dailyNT",
            [
                _m(yesterday_start, 20),
                _m(today_ts, 5),
            ],
        )

        qh_ch = _make_channel("quarterHourly", [_m(today_ts, 20)])  # 20/4 = 5 kWh

        yesterday = _calculate_yesterday_consumption([daily_ch], today_ts)
        daily = _calculate_daily_consumption([qh_ch], [daily_ch], yesterday)
        monthly = _calculate_monthly_consumption(monthly_data, daily)
        yearly = _calculate_yearly_consumption(monthly_data, daily)

        assert yesterday == 20.0
        assert daily == 5.0
        # 50+50 = 100 from monthly, + 5 daily = 105
        assert monthly == 105.0
        # 1100 from sum + 5 daily = 1105
        assert yearly == 1105.0
