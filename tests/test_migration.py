"""Tests for config entry migration (v1 -> v2 unique_id scheme)."""

import logging
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupe_e.const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_PARTNER,
    CONF_PREMISE,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def mock_coordinator_update():
    """Avoid API/recorder access: migration tests only exercise entry logic."""
    with patch(
        "custom_components.groupe_e.coordinator."
        "GroupeEDataUpdateCoordinator._async_update_data",
        return_value={},
    ):
        yield


def _v1_entry(**overrides):
    data = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
        CONF_PREMISE: "106180",
        CONF_PARTNER: "6050184",
        CONF_NT_PRICE: 0.2,
        CONF_HT_PRICE: 0.3,
    }
    data.update(overrides)
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        version=1,
        unique_id="user@example.com",
        title="user@example.com",
    )


async def test_v1_entry_migrates_unique_id_and_version(hass):
    """A v1 entry gets the username:premise:partner unique_id and version 2."""
    entry = _v1_entry()
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.unique_id == "user@example.com:106180:6050184"
    assert entry.state.value == "loaded"


async def test_v2_entry_not_rewritten(hass):
    """An already-migrated v2 entry passes through untouched."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_v1_entry().data,
        version=2,
        unique_id="user@example.com:106180:6050184",
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.state.value == "loaded"


async def test_future_version_aborts(hass):
    """Entries from a newer future version refuse to load."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_v1_entry().data,
        version=99,
        unique_id="whatever",
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.state.value == "migration_error"


async def test_collision_keeps_old_unique_id(hass, caplog):
    """If another entry already owns the new unique_id, keep the old one."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        data=_v1_entry().data,
        version=2,
        unique_id="user@example.com:106180:6050184",
    )
    existing.add_to_hass(hass)
    legacy = _v1_entry()
    legacy.add_to_hass(hass)

    with caplog.at_level(logging.WARNING):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()

    assert legacy.version == 2
    assert legacy.unique_id == "user@example.com"  # unchanged
    assert any("already in use" in r.message for r in caplog.records)


async def test_missing_prices_logs_warning(hass, caplog):
    """Entries whose prices were lost by the old reconfigure bug warn loudly."""
    data = {
        key: value
        for key, value in _v1_entry().data.items()
        if key not in (CONF_NT_PRICE, CONF_HT_PRICE)
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, version=1, unique_id="user@example.com"
    )
    entry.add_to_hass(hass)

    with caplog.at_level(logging.WARNING):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()

    assert any("missing NT/HT tariff prices" in r.message for r in caplog.records)
