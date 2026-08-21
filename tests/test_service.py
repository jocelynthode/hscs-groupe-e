"""Tests for the groupe_e.reset_statistics service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupe_e.const import DOMAIN, TARIFF_TIMEZONE

ENTRY_ID = "test-entry-id"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture
def coordinator_mock(hass):
    """A registered config entry whose coordinator is fully mocked."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="u:p:q")
    # Force a deterministic entry_id so tests can reference it.
    object.__setattr__(entry, "entry_id", ENTRY_ID)
    entry.add_to_hass(hass)

    coord = MagicMock()
    coord.async_schedule_rebuild = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    return coord


async def _call(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "reset_statistics", data, blocking=True
    )


async def test_default_rebuilds_from_year_start(hass, coordinator_mock):
    """No fields: rebuild from Jan 1 of the current year (Zurich midnight)."""
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    await _call(hass, entry_id=ENTRY_ID)

    expected = (
        datetime.now(ZoneInfo(TARIFF_TIMEZONE))
        .replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
    )
    coordinator_mock.async_schedule_rebuild.assert_awaited_once_with(expected)
    coordinator_mock.async_request_refresh.assert_awaited_once()


async def test_clear_all_wipes_everything(hass, coordinator_mock):
    """clear_all=True schedules a rebuild from datetime.min (full wipe)."""
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    await _call(hass, entry_id=ENTRY_ID, clear_all=True)

    coordinator_mock.async_schedule_rebuild.assert_awaited_once_with(
        datetime.min.replace(tzinfo=timezone.utc)
    )


async def test_rebuild_since_normalizes_to_local_midnight(hass, coordinator_mock):
    """rebuild_since is normalized to Zurich midnight of that date, in UTC."""
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    await _call(hass, entry_id=ENTRY_ID, rebuild_since="2026-03-15")

    expected = (
        datetime(2026, 3, 15, tzinfo=ZoneInfo(TARIFF_TIMEZONE))
        .astimezone(timezone.utc)
    )
    coordinator_mock.async_schedule_rebuild.assert_awaited_once_with(expected)


async def test_unknown_entry_is_rejected(hass, coordinator_mock, caplog):
    """An unknown entry_id logs an error and touches no coordinator."""
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    await _call(hass, entry_id="does-not-exist")

    coordinator_mock.async_schedule_rebuild.assert_not_called()
    assert any("not found" in r.message for r in caplog.records)
