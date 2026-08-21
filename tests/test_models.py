"""Tests for the Groupe-E data models.

Payloads below mirror the examples documented in ``api.md`` (trimmed for
readability), including the \"no data\" responses.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.groupe_e.models import (
    ChannelData,
    Measurement,
    SmartMeterChannel,
    SmartMeterResponse,
)

QUARTER_HOURLY = [
    {
        "id": "quarterHourly",
        "data": {
            "usagePointPublicId": "283122",
            "from": 1787176800000,
            "to": 1787263200000,
            "channelCode": "CCH-S",
            "unit": "kW",
            "measurementData": [
                {"status": "W", "timestamp": 1787177700000, "value": 0.572},
                {"status": "W", "timestamp": 1787178600000, "value": 0.368},
            ],
        },
    }
]

DAILY_NO_DATA = [
    {
        "id": "dailyNT",
        "data": {
            "usagePointPublicId": "283122",
            "from": 1795535200000,
            "to": 1798213600000,
            "channelCode": "CHC-Q",
            "unit": "kWh",
            "measurementData": [],
        },
    },
    {
        "id": "dailyHT",
        "data": {
            "usagePointPublicId": "283122",
            "from": 1795535200000,
            "to": 1798213600000,
            "channelCode": "CHP-Q",
            "unit": "kWh",
            "measurementData": [],
        },
    },
]

MONTHLY_NO_DATA = [
    {
        "id": "monthlyNT",
        "data": {
            "usagePointPublicId": "283122",
            "from": 1797222000000,
            "to": 1808758000000,
            "channelCode": "CHC-M",
            "unit": "kWh",
            "measurementData": [],
        },
    },
    {
        "id": "monthlyHT",
        "data": {
            "usagePointPublicId": "283122",
            "from": 1797222000000,
            "to": 1808758000000,
            "channelCode": "CHP-M",
            "unit": "kWh",
            "measurementData": [],
        },
    },
]


class TestSmartMeterResponse:
    def test_parses_quarter_hourly(self):
        response = SmartMeterResponse.from_dict(QUARTER_HOURLY)
        assert len(response.channels) == 1
        channel = response.channels[0]
        assert channel.id == "quarterHourly"
        assert channel.data.usage_point_public_id == "283122"
        assert channel.data.from_time == 1787176800000
        assert channel.data.to_time == 1787263200000
        assert channel.data.channel_code == "CCH-S"
        assert channel.data.unit == "kW"
        assert len(channel.data.measurements) == 2
        m = channel.data.measurements[0]
        assert isinstance(m, Measurement)
        assert m.status == "W"
        assert m.timestamp == datetime.fromtimestamp(
            1787177700000 / 1000, tz=timezone.utc
        )
        assert m.value == 0.572

    def test_has_data_true_with_measurements(self):
        response = SmartMeterResponse.from_dict(QUARTER_HOURLY)
        assert response.has_data is True
        assert response.primary_channel.has_measurements is True

    def test_quarter_hourly_no_data(self):
        no_data = [
            {
                "id": "quarterHourly",
                "data": {
                    "usagePointPublicId": "283122",
                    "from": 1797176800000,
                    "to": 1797263200000,
                    "channelCode": "CCH-S",
                    "unit": "kW",
                    "measurementData": [],
                },
            }
        ]
        response = SmartMeterResponse.from_dict(no_data)
        assert len(response.channels) == 1
        assert response.channels[0].data.measurements == []
        assert response.has_data is False

    def test_daily_no_data(self):
        response = SmartMeterResponse.from_dict(DAILY_NO_DATA)
        assert len(response.channels) == 2
        assert [c.id for c in response.channels] == ["dailyNT", "dailyHT"]
        assert all(c.data.measurements == [] for c in response.channels)
        assert response.has_data is False
        assert response.measurements == []

    def test_monthly_no_data(self):
        response = SmartMeterResponse.from_dict(MONTHLY_NO_DATA)
        assert len(response.channels) == 2
        assert [c.id for c in response.channels] == ["monthlyNT", "monthlyHT"]
        assert response.has_data is False

    def test_non_list_payload_yields_empty_response(self):
        for bad in (None, {}, "text", 42):
            response = SmartMeterResponse.from_dict(bad)
            assert response.channels == []
            assert response.has_data is False
            assert response.primary_channel is None

    def test_flattened_measurements(self):
        response = SmartMeterResponse.from_dict(QUARTER_HOURLY)
        flattened = response.measurements
        assert len(flattened) == 2
        assert [m.value for m in flattened] == [0.572, 0.368]

    def test_to_dict_round_trip(self):
        original = SmartMeterResponse.from_dict(QUARTER_HOURLY)
        assert original.to_dict() == QUARTER_HOURLY

    def test_from_json(self):
        import json

        response = SmartMeterResponse.from_json(json.dumps(QUARTER_HOURLY))
        assert response.channels[0].id == "quarterHourly"


class TestSmartMeterChannel:
    def test_is_high_tariff(self):
        assert SmartMeterChannel.from_dict(DAILY_NO_DATA[0]).is_high_tariff is False
        assert SmartMeterChannel.from_dict(DAILY_NO_DATA[1]).is_high_tariff is True
        assert SmartMeterChannel.from_dict(MONTHLY_NO_DATA[0]).is_high_tariff is False
        assert SmartMeterChannel.from_dict(MONTHLY_NO_DATA[1]).is_high_tariff is True
        # quarter-hourly is a single blended channel, not tariff-split
        assert SmartMeterChannel.from_dict(QUARTER_HOURLY[0]).is_high_tariff is False


class TestMeasurement:
    def test_from_dict_defaults(self):
        m = Measurement.from_dict({"timestamp": 1, "value": 2.5})
        assert m.status == "W"
        assert m.timestamp == datetime.fromtimestamp(0.001, tz=timezone.utc)
        assert m.value == 2.5

    def test_to_dict(self):
        m = Measurement(timestamp=datetime.fromtimestamp(0.001, tz=timezone.utc), value=2.5)
        assert m.to_dict() == {"status": "W", "timestamp": 1, "value": 2.5}

    def test_utc_epoch_round_trip(self):
        """The API's UTC epoch-millisecond timestamps round-trip losslessly."""
        epoch_ms = 1787177700000
        m = Measurement.from_dict({"timestamp": epoch_ms, "value": 0.572})
        # Parsed as a UTC-aware datetime.
        assert m.timestamp == datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        assert m.timestamp.tzinfo is timezone.utc
        # Serializing back preserves the exact API value.
        assert m.to_dict()["timestamp"] == epoch_ms

    def test_instant_is_timezone_independent(self):
        """The instant must not shift when constructed from another tz."""
        utc_dt = datetime.fromtimestamp(1787177700000 / 1000, tz=timezone.utc)
        zurich_dt = utc_dt.astimezone(ZoneInfo("Europe/Zurich"))
        assert Measurement(timestamp=zurich_dt, value=1.0).to_dict()["timestamp"] == 1787177700000

    def test_validation_raises_on_bad_payloads(self):
        """Malformed payloads raise at construction, never silently skipped."""
        import pytest

        with pytest.raises((TypeError, ValueError)):
            Measurement.from_dict({"timestamp": "not-a-number", "value": 1.0})
        with pytest.raises((TypeError, ValueError)):
            Measurement.from_dict({"timestamp": 123, "value": "abc"})
        with pytest.raises((TypeError, ValueError)):
            Measurement.from_dict({"timestamp": 123, "value": True})
        with pytest.raises((TypeError, ValueError)):
            Measurement.from_dict({"timestamp": True, "value": 1.0})
        with pytest.raises(KeyError):
            Measurement.from_dict({"value": 1.0})
        with pytest.raises(KeyError):
            Measurement.from_dict({"timestamp": 123})
        with pytest.raises((TypeError, ValueError)):
            Measurement(timestamp="bad", value=1.0)
        with pytest.raises((TypeError, ValueError)):
            Measurement(timestamp=datetime.now(timezone.utc), value="bad")
        with pytest.raises(ValueError):
            # Naive datetime must be rejected by the tz-awareness check.
            Measurement(timestamp=datetime(2026, 1, 1), value=1.0)  # noqa: DTZ001


class TestChannelData:
    def test_from_dict_empty_measurement_data(self):
        data = ChannelData.from_dict({"measurementData": []})
        assert data.measurements == []
        assert data.usage_point_public_id == ""
