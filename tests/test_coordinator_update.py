"""Behavioral tests for GroupeEDataUpdateCoordinator._async_update_data.

These exercise the full update orchestration (resume-point selection, rebuild
modes, out-of-sync handling, error mapping) with a real DataUpdateCoordinator
on the HA test harness. Recorder access is patched at the module boundary.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupe_e.const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_PARTNER,
    CONF_PREMISE,
    DOMAIN,
)
from custom_components.groupe_e.api import GroupeEApiError
from custom_components.groupe_e.coordinator import (
    GroupeEDataUpdateCoordinator,
    _LOCAL_TZ,
)
from custom_components.groupe_e.models import SmartMeterResponse

UTC = timezone.utc

NT_ID = "groupe_e:energy_consumption_106180_normal_tariff"
HT_ID = "groupe_e:energy_consumption_106180_high_tariff"
TOTAL_ID = "groupe_e:energy_consumption_106180_total"
COST_ID = "groupe_e:energy_consumption_106180_cost"


def _entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="test",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_PREMISE: "106180",
            CONF_PARTNER: "6050184",
            CONF_NT_PRICE: 0.2,
            CONF_HT_PRICE: 0.3,
        },
    )


def _last_stat(start: datetime, total: float) -> dict:
    """Shape returned by get_last_statistics."""
    return {"start": start.timestamp(), "sum": total}


def _response(measurements: list[tuple[datetime, float]]) -> SmartMeterResponse:
    return SmartMeterResponse.from_dict(
        [
            {
                "id": "quarterHourly",
                "data": {
                    "measurementData": [
                        {"timestamp": int(ts.timestamp() * 1000), "value": v}
                        for ts, v in measurements
                    ]
                },
            }
        ]
    )


class RecorderMocks:
    """Bundle of patched recorder touchpoints."""

    def __init__(self):
        self.add_external = None
        self.clear = None
        self.during_period = None


@pytest.fixture
def coord(hass):
    """A real coordinator with recorder + API boundaries mocked."""
    entry = _entry()
    entry.add_to_hass(hass)
    api = MagicMock()
    api.get_smartmeter_data = AsyncMock(return_value=SmartMeterResponse())

    mocks = RecorderMocks()

    with (
        patch("custom_components.groupe_e.coordinator.get_instance") as mock_gi,
        patch(
            "custom_components.groupe_e.coordinator.get_last_statistics"
        ) as mock_gls,
        patch(
            "custom_components.groupe_e.coordinator.statistics_during_period"
        ) as mock_sdp,
        patch(
            "custom_components.groupe_e.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        instance = mock_gi.return_value
        # Run executor jobs inline.
        instance.async_add_executor_job = AsyncMock(
            side_effect=lambda target, *args, **kwargs: target(*args, **kwargs)
        )
        instance.async_clear_statistics = MagicMock()
        mocks.clear = instance.async_clear_statistics
        mocks.add_external = mock_add
        mocks.during_period = mock_sdp

        coordinator = GroupeEDataUpdateCoordinator(
            hass, api, "106180", "6050184", 12, entry
        )

        def set_last_stats(stats: dict[str, list[dict]] | None):
            """Configure what get_last_statistics returns per statistic_id."""

            async def fake_get_last_stat(statistic_id):
                if stats and statistic_id in stats:
                    return {statistic_id: stats[statistic_id]}
                return {}

            coordinator._async_get_last_stat = fake_get_last_stat

        coordinator.set_last_stats_for_test = set_last_stats
        coordinator.mocks = mocks
        coordinator.api_mock = api
        yield coordinator


def _expected_year_start() -> datetime:
    """Year start as the coordinator computes it: Zurich midnight -> UTC."""
    return (
        datetime.now(_LOCAL_TZ)
        .replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )


def _inserted(mocks: RecorderMocks) -> dict[str, list[dict]]:
    """Collect inserted statistics keyed by statistic_id."""
    out: dict[str, list[dict]] = {}
    for call in mocks.add_external.call_args_list:
        _hass, metadata, statistics = call.args
        out.setdefault(metadata["statistic_id"], []).extend(statistics)
    return out


async def test_incremental_resumes_from_last_stat(coord):
    """Normal path: fetch starts at the last stored timestamp, sums continue."""
    three_days_ago = (datetime.now(UTC) - timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )
    h1 = three_days_ago + timedelta(hours=1)
    h2 = three_days_ago + timedelta(hours=2)
    coord.set_last_stats_for_test(
        {
            NT_ID: [_last_stat(three_days_ago, 100.0)],
            HT_ID: [_last_stat(three_days_ago, 50.0)],
            TOTAL_ID: [_last_stat(three_days_ago, 150.0)],
            COST_ID: [_last_stat(three_days_ago, 30.0)],
        }
    )
    coord.api_mock.get_smartmeter_data.return_value = _response(
        [(h1, 4.0), (h2, 8.0)]  # 1 kWh and 2 kWh per hour
    )

    data = await coord._async_update_data()

    args = coord.api_mock.get_smartmeter_data.await_args
    assert args.args[2] == three_days_ago  # start
    assert args.kwargs["resolution"] == "quarter-hourly"

    inserted = _inserted(coord.mocks)
    assert set(inserted) == {NT_ID, HT_ID, TOTAL_ID, COST_ID}

    # Total series continues from 150.0 with 1 + 2 kWh.
    total_sums = [s["sum"] for s in inserted[TOTAL_ID]]
    assert total_sums == [151.0, 153.0]
    # NT + HT states per hour must partition the total state.
    for i in range(2):
        nt_state = inserted[NT_ID][i]["state"]
        ht_state = inserted[HT_ID][i]["state"]
        assert nt_state + ht_state == pytest.approx(inserted[TOTAL_ID][i]["state"])
    # In-memory sums exposed to sensors.
    assert data["total"] == 153.0


async def test_up_to_date_skips_api(coord):
    """When the last stat is newer than today's start, no API call is made."""
    far_future = datetime.now(UTC) + timedelta(days=365)
    coord.set_last_stats_for_test(
        {
            NT_ID: [_last_stat(far_future, 100.0)],
            HT_ID: [_last_stat(far_future, 50.0)],
        }
    )

    data = await coord._async_update_data()

    coord.api_mock.get_smartmeter_data.assert_not_called()
    coord.mocks.add_external.assert_not_called()
    # In-memory sums are only populated by inserts; after a restart with an
    # up-to-date recorder they stay None until new data arrives.
    assert data["nt"] is None


async def test_missing_stats_rebuild_from_year_start(coord):
    """With no stored stats, the fetch starts at Jan 1 of the current year."""
    coord.api_mock.get_smartmeter_data.return_value = SmartMeterResponse()

    await coord._async_update_data()

    args = coord.api_mock.get_smartmeter_data.await_args.args
    assert args[2] == _expected_year_start()
    # Nothing inserted for an empty response.
    coord.mocks.add_external.assert_not_called()


async def test_out_of_sync_clears_and_rebuilds(coord):
    """Diverging NT/HT timestamps must wipe stats before rebuilding."""
    nt_start = datetime.now(UTC) - timedelta(days=5)
    ht_start = datetime.now(UTC) - timedelta(days=2)
    coord.set_last_stats_for_test(
        {
            NT_ID: [_last_stat(nt_start, 100.0)],
            HT_ID: [_last_stat(ht_start, 50.0)],
            TOTAL_ID: [_last_stat(nt_start, 150.0)],
            COST_ID: [_last_stat(nt_start, 30.0)],
        }
    )
    coord.api_mock.get_smartmeter_data.return_value = SmartMeterResponse()

    await coord._async_update_data()

    # Stats cleared BEFORE any new insertion.
    coord.mocks.clear.assert_called_once_with([NT_ID, HT_ID, TOTAL_ID, COST_ID])
    coord.mocks.add_external.assert_not_called()
    # Rebuild starts at year start.
    args = coord.api_mock.get_smartmeter_data.await_args.args
    assert args[2] == _expected_year_start()


async def test_full_clear_rebuild(coord):
    """rebuild_since=datetime.min wipes everything and refetches from year start."""
    coord.set_last_stats_for_test(
        {
            NT_ID: [_last_stat(datetime.now(UTC) - timedelta(days=5), 100.0)],
            HT_ID: [_last_stat(datetime.now(UTC) - timedelta(days=5), 50.0)],
        }
    )
    coord.api_mock.get_smartmeter_data.return_value = SmartMeterResponse()

    await coord.async_schedule_rebuild(datetime.min.replace(tzinfo=UTC))
    await coord._async_update_data()

    coord.mocks.clear.assert_called_once()
    args = coord.api_mock.get_smartmeter_data.await_args.args
    assert args[2] == _expected_year_start()


async def test_partial_rebuild_preserves_pre_cutoff_stats(coord):
    """Partial rebuild re-inserts preserved history and resumes from cutoff."""
    cutoff = (datetime.now(UTC) - timedelta(days=10)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    preserved = [_last_stat(cutoff - timedelta(hours=1), 42.0)]
    coord.mocks.during_period.return_value = {
        NT_ID: [dict(preserved[0])],
        HT_ID: [],
        TOTAL_ID: [{"start": preserved[0]["start"], "sum": 42.0}],
        COST_ID: [],
    }
    coord.api_mock.get_smartmeter_data.return_value = SmartMeterResponse()

    await coord.async_schedule_rebuild(cutoff)
    await coord._async_update_data()

    # Pre-cutoff data was read, everything cleared, preserved data re-inserted.
    assert coord.mocks.during_period.called
    coord.mocks.clear.assert_called_once()
    inserted = _inserted(coord.mocks)
    assert inserted[NT_ID][-1]["sum"] == 42.0
    # Fetch resumes exactly at the cutoff.
    args = coord.api_mock.get_smartmeter_data.await_args.args
    assert args[2] == cutoff


async def test_api_error_maps_to_update_failed(coord):
    """GroupeEApiError surfaces as UpdateFailed."""
    coord.set_last_stats_for_test(None)
    coord.api_mock.get_smartmeter_data.side_effect = GroupeEApiError("boom")

    with pytest.raises(UpdateFailed, match="boom"):
        await coord._async_update_data()


async def test_empty_channels_is_valid_no_data(coord):
    """A channels-but-no-measurements response inserts nothing and succeeds."""
    coord.set_last_stats_for_test(None)
    coord.api_mock.get_smartmeter_data.return_value = SmartMeterResponse()

    data = await coord._async_update_data()

    coord.mocks.add_external.assert_not_called()
    assert data["nt"] is None and data["cost"] is None


async def test_all_measurements_at_resume_point_logged(coord, caplog):
    """Data arrives but every measurement is at/before the resume point.

    Must be visibly different from an empty API response in debug logs.
    """
    import logging

    three_days_ago = (datetime.now(UTC) - timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )
    coord.set_last_stats_for_test(
        {
            NT_ID: [_last_stat(three_days_ago, 100.0)],
            HT_ID: [_last_stat(three_days_ago, 50.0)],
            TOTAL_ID: [_last_stat(three_days_ago, 150.0)],
            COST_ID: [_last_stat(three_days_ago, 30.0)],
        }
    )
    # API returns exactly the resume point (filtered out by <= comparison).
    coord.api_mock.get_smartmeter_data.return_value = _response(
        [(three_days_ago, 4.0)]
    )

    with caplog.at_level(logging.DEBUG):
        await coord._async_update_data()

    assert any(
        "nothing new to insert" in r.message for r in caplog.records
    ), [r.message for r in caplog.records]
    coord.mocks.add_external.assert_not_called()
