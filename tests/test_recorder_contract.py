"""Contract tests against the REAL recorder implementation.

These tests exercise the actual homeassistant.components.recorder code path
(in-memory SQLite) instead of mocking it, so they catch mismatches between
what we request from the recorder API and what it actually returns — e.g.
get_last_statistics(types=set()) returning rows without a "sum" key.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupe_e.api import GroupeEApiError
from custom_components.groupe_e.const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_PARTNER,
    CONF_PREMISE,
    DOMAIN,
)
from custom_components.groupe_e.coordinator import GroupeEDataUpdateCoordinator
from custom_components.groupe_e.models import SmartMeterResponse

STATISTIC_ID = "groupe_e:test_energy"


@pytest.fixture
async def coord(hass):
    """Minimal coordinator without touching the network."""
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)
    return GroupeEDataUpdateCoordinator(hass, None, "106180", "6050184", 12, entry)


async def _insert_one_stat(hass, start: datetime, total: float) -> None:
    """Insert one external energy statistic through the real recorder."""
    metadata = {
        "has_sum": True,
        "mean_type": 0,
        "statistic_id": STATISTIC_ID,
        "source": "groupe_e",
        "name": "Test Energy",
        "unit_class": "energy",
        "unit_of_measurement": "kWh",
    }
    end = datetime.fromtimestamp(start.timestamp() + 900, tz=timezone.utc)
    async_add_external_statistics(
        hass,
        metadata,
        [
            {
                "start": start,
                "end": end,
                "state": total,
                "sum": total,
            }
        ],
    )
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()


async def test_get_last_stat_returns_sum(
    recorder_mock, hass, coord
):
    """_async_get_last_stat must return rows containing 'start' AND 'sum'."""
    start = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    await _insert_one_stat(hass, start, 1234.5)

    result = await coord._async_get_last_stat(STATISTIC_ID)

    assert STATISTIC_ID in result, f"no stats returned: {result!r}"
    rows = result[STATISTIC_ID]
    assert len(rows) == 1
    row = rows[0]
    # The exact contract broken by types=set(): both keys must be present.
    assert "start" in row, f"'start' missing from row: {row!r}"
    assert "sum" in row, f"'sum' missing from row: {row!r}"
    assert row["sum"] == pytest.approx(1234.5)


async def test_get_last_stat_empty_when_no_data(recorder_mock, hass, coord):
    """With no stored statistics, an empty dict is returned."""
    result = await coord._async_get_last_stat("groupe_e:never_inserted")
    assert result == {}


# --- Full round-trip: seed real stats -> update -> read back real stats ---

NT_ID = "groupe_e:energy_consumption_106180_normal_tariff"
HT_ID = "groupe_e:energy_consumption_106180_high_tariff"
TOTAL_ID = "groupe_e:energy_consumption_106180_total"
COST_ID = "groupe_e:energy_consumption_106180_cost"


def _seed_metadata(statistic_id: str, unit: str, unit_class: str | None) -> dict:
    return {
        "has_sum": True,
        "mean_type": 0,
        "statistic_id": statistic_id,
        "source": "groupe_e",
        "name": statistic_id.split(":")[1],
        "unit_class": unit_class,
        "unit_of_measurement": unit,
    }


async def _seed_all_stats(hass, start: datetime) -> None:
    """Seed one row for each of the four coordinator statistics."""
    seeds = [
        (NT_ID, "kWh", "energy", 100.0),
        (HT_ID, "kWh", "energy", 50.0),
        (TOTAL_ID, "kWh", "energy", 150.0),
        (COST_ID, "CHF", None, 30.0),
    ]
    end = datetime.fromtimestamp(start.timestamp() + 900, tz=timezone.utc)
    for stat_id, unit, unit_class, total in seeds:
        async_add_external_statistics(
            hass,
            _seed_metadata(stat_id, unit, unit_class),
            [{"start": start, "end": end, "state": total, "sum": total}],
        )
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()


def _api_response(measurements: list[tuple[datetime, float]]):
    response = SmartMeterResponse.from_dict(
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
    api = MagicMock()
    api.get_smartmeter_data = AsyncMock(return_value=response)
    return api


async def test_full_round_trip_continues_sums(recorder_mock, hass):
    """End-to-end through the REAL recorder: seeded stats are resumed correctly.

    Seeds NT=100/HT=50/TOTAL=150/COST=30, feeds two measurements worth
    1 kWh + 2 kWh, then reads back from the recorder and verifies every
    series continued from its seeded sum. This is the scenario that broke
    when get_last_statistics stopped returning 'sum'.
    """
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)

    last_start = (datetime.now(timezone.utc) - timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0
    )
    await _seed_all_stats(hass, last_start)

    coord = GroupeEDataUpdateCoordinator(
        hass,
        _api_response(
            [
                (last_start + timedelta(hours=1), 4.0),  # 1 kWh
                (last_start + timedelta(hours=2), 8.0),  # 2 kWh
            ]
        ),
        "106180",
        "6050184",
        12,
        entry,
    )

    data = await coord._async_update_data()

    # In-memory sums exposed to sensors continued from the seeded values.
    assert data["total"] == pytest.approx(153.0)

    # Read back what actually landed in the recorder.
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()

    def read_last():
        return {
            sid: get_last_statistics(hass, 10, sid, True, {"sum"}).get(sid, [])
            for sid in (NT_ID, HT_ID, TOTAL_ID, COST_ID)
        }

    stored = await get_instance(hass).async_add_executor_job(read_last)
    # Rows come back newest-first; sort by start so [-1] is the latest.
    for rows in stored.values():
        rows.sort(key=lambda r: r["start"])

    nt_final = stored[NT_ID][-1]["sum"]
    ht_final = stored[HT_ID][-1]["sum"]
    assert stored[TOTAL_ID][-1]["sum"] == pytest.approx(153.0)
    # Tariff split partitions the total regardless of classification.
    assert nt_final + ht_final == pytest.approx(153.0)
    assert nt_final >= 100.0 and ht_final >= 50.0
    # Cost continued from 30.0 with 1+2 kWh at 0.2 or 0.3 CHF/kWh.
    assert 30.5 < stored[COST_ID][-1]["sum"] < 31.0


async def test_full_round_trip_api_error(recorder_mock, hass):
    """API errors still surface as UpdateFailed with a real recorder behind."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="u:p:q")
    entry.add_to_hass(hass)
    api = MagicMock()
    api.get_smartmeter_data = AsyncMock(side_effect=GroupeEApiError("boom"))
    coord = GroupeEDataUpdateCoordinator(hass, api, "106180", "6050184", 12, entry)

    with pytest.raises(UpdateFailed, match="boom"):
        await coord._async_update_data()
