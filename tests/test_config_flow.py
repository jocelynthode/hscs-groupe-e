"""Tests for the Groupe-E config and options flows."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.groupe_e.api import GroupeEApiError, GroupeEAuthError
from custom_components.groupe_e.config_flow import (
    _format_tariff_schedule,
    _parse_tariff_schedule,
)
from custom_components.groupe_e.const import (
    CONF_HT_PRICE,
    CONF_NT_PRICE,
    CONF_PARTNER,
    CONF_PREMISE,
    CONF_TARIFF_SCHEDULE,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture
def valid_api():
    """Patch GroupeEAPI so credential validation succeeds."""
    with patch("custom_components.groupe_e.config_flow.GroupeEAPI") as mock_api:
        mock_api.return_value.async_validate_credentials = AsyncMock()
        yield mock_api


def _user_input(**overrides):
    data = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
        CONF_PREMISE: "106180",
        CONF_PARTNER: "6050184",
        CONF_NT_PRICE: 0.2,
        CONF_HT_PRICE: 0.3,
    }
    data.update(overrides)
    return data


# --- pure schedule helpers ---


class TestTariffScheduleHelpers:
    def test_round_trip_whole_hours(self):
        periods = _parse_tariff_schedule("07:00-12:00,17:00-23:00")
        assert periods == [
            {"start": 7.0, "end": 12.0},
            {"start": 17.0, "end": 23.0},
        ]
        assert _format_tariff_schedule(periods) == "07:00-12:00,17:00-23:00"

    def test_fractional_hours_round_trip(self):
        periods = _parse_tariff_schedule("07:30-12:00,17:30-23:15")
        assert periods == [
            {"start": 7.5, "end": 12.0},
            {"start": 17.5, "end": 23.25},
        ]
        assert _format_tariff_schedule(periods) == "07:30-12:00,17:30-23:15"

    def test_legacy_int_format_formats(self):
        assert _format_tariff_schedule([{"start": 7, "end": 12}]) == "07:00-12:00"

    @pytest.mark.parametrize(
        "bad",
        [
            "abc",
            "07:00",
            "12:00-07:00",  # end before start
            "25:00-26:00",  # out of range
            "07:00-24:30",  # end beyond 24:00
            "07:00-07:00",  # empty period
        ],
    )
    def test_invalid_inputs_raise(self, bad):
        with pytest.raises(ValueError):
            _parse_tariff_schedule(bad)

    def test_empty_segments_ignored(self):
        assert _parse_tariff_schedule(" 07:00-12:00 , ,17:00-23:00") == [
            {"start": 7.0, "end": 12.0},
            {"start": 17.0, "end": 23.0},
        ]


# --- user step ---


async def test_user_step_creates_entry_with_composite_unique_id(hass, valid_api):
    """Valid input creates an entry keyed username:premise:partner."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "user@example.com:106180:6050184"
    assert entry.data == _user_input()
    # Credentials AND premise/partner were validated before creating the entry.
    valid_api.return_value.async_validate_credentials.assert_awaited_once_with(
        "106180", "6050184"
    )


async def test_user_step_invalid_auth_shows_error(hass, valid_api):
    """Bad credentials re-show the form with invalid_auth, no entry created."""
    valid_api.return_value.async_validate_credentials.side_effect = GroupeEAuthError(
        "nope"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_user_step_connection_error_shows_error(hass, valid_api):
    """API connectivity problems re-show the form with cannot_connect."""
    valid_api.return_value.async_validate_credentials.side_effect = GroupeEApiError(
        "down"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_entry_aborts(hass, valid_api):
    """The same username:premise:partner cannot be added twice."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=_user_input(), unique_id="user@example.com:106180:6050184"
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_premise_same_account_allowed(hass, valid_api):
    """A different premise under the same account is a new entry, not a duplicate."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=_user_input(), unique_id="user@example.com:106180:6050184"
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(**{CONF_PREMISE: "999999"})
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "user@example.com:999999:6050184"


# --- reconfigure step ---


async def test_reconfigure_preserves_prices(hass, valid_api):
    """REGRESSION: reconfigure merges data and must not drop the price keys.

    The v2.0.0 flow replaced entry data wholesale, silently resetting prices
    to 0 and corrupting cost statistics.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_user_input(),
        unique_id="user@example.com:106180:6050184",
        version=2,
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, unique_id=entry.unique_id)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "newemail@example.com",
            CONF_PASSWORD: "newsecret",
            CONF_PREMISE: "106180",
            CONF_PARTNER: "6050184",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # Prices survive the update.
    assert entry.data[CONF_NT_PRICE] == 0.2
    assert entry.data[CONF_HT_PRICE] == 0.3
    # Other fields were updated.
    assert entry.data[CONF_USERNAME] == "newemail@example.com"
    assert entry.data[CONF_PASSWORD] == "newsecret"
    # unique_id followed the new username.
    assert entry.unique_id == "newemail@example.com:106180:6050184"


async def test_reconfigure_unique_id_collision_shows_error(hass, valid_api):
    """Reconfigure to an identity owned by another entry shows an error."""
    other = MockConfigEntry(
        domain=DOMAIN,
        data=_user_input(CONF_PREMISE="999999"),
        unique_id="user@example.com:999999:6050184",
        version=2,
    )
    other.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_user_input(),
        unique_id="user@example.com:106180:6050184",
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_PREMISE: "999999",  # collides with `other`
            CONF_PARTNER: "6050184",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}
    # Nothing was changed.
    assert entry.data[CONF_PREMISE] == "106180"


# --- options step ---


async def test_options_invalid_schedule_shows_error(hass):
    """A malformed schedule re-shows the form with an error, nothing saved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_user_input(),
        unique_id="user@example.com:106180:6050184",
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NT_PRICE: 0.2,
            CONF_HT_PRICE: 0.3,
            "update_interval": 12,
            CONF_TARIFF_SCHEDULE: "not-a-schedule",
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_tariff_schedule"}
    assert entry.options == {}


async def test_options_valid_schedule_stored_parsed(hass):
    """A valid schedule is parsed into period dicts and saved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=_user_input(),
        unique_id="user@example.com:106180:6050184",
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NT_PRICE: 0.25,
            CONF_HT_PRICE: 0.35,
            "update_interval": 6,
            CONF_TARIFF_SCHEDULE: "06:00-09:00,18:00-22:30",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TARIFF_SCHEDULE] == [
        {"start": 6.0, "end": 9.0},
        {"start": 18.0, "end": 22.5},
    ]
    assert entry.options["update_interval"] == 6
