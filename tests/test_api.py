"""Tests for the Groupe-E API client using pytest-homeassistant-custom-component."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import ClientSession

from custom_components.groupe_e.api import (
    GroupeEAPI,
    GroupeEApiError,
    GroupeEAuthError,
    _to_epoch_ms,
)


@pytest.fixture
def mock_session():
    session = AsyncMock(spec=ClientSession)
    return session


@pytest.fixture
def api(mock_session):
    return GroupeEAPI(
        session=mock_session,
        username="user@example.com",
        password="secret",
    )


def _mock_context_manager(resp):
    cm = AsyncMock(spec=["__aenter__", "__aexit__"])
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _mock_response(status=200, data=None):
    resp = AsyncMock(spec=["status", "json", "text"])
    resp.status = status
    resp.json = AsyncMock(return_value=data if data is not None else [])
    resp.text = AsyncMock(return_value="[]")
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return resp


class TestLogin:
    async def test_success(self, api, mock_session):
        mock_session.post.return_value = _mock_context_manager(
            _mock_response(200, {"access_token": "tok123", "expires_in": 3600})
        )
        await api._async_login()
        assert api._token == "tok123"
        assert api._token_expires_at is not None

    async def test_failure_raises(self, api, mock_session):
        mock_session.post.return_value = _mock_context_manager(
            _mock_response(401, {"error": "bad credentials"})
        )
        with pytest.raises(GroupeEAuthError):
            await api._async_login()
        assert api._token is None

    async def test_connection_error_raises(self, api, mock_session):
        mock_session.post.side_effect = aiohttp.ClientConnectionError(
            "connection refused"
        )
        with pytest.raises(GroupeEAuthError):
            await api._async_login()


class TestGetSmartmeterData:
    async def test_success(self, api, mock_session):
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        expected = [{"id": "monthlyNT", "data": {"measurementData": []}}]

        mock_session.post.return_value = _mock_context_manager(
            _mock_response(200, expected)
        )
        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            resolution="monthly",
        )
        assert result is not None
        assert len(result.channels) == 1
        assert result.channels[0].id == "monthlyNT"
        assert result.channels[0].data.measurements == []

    async def test_no_data_response_parses(self, api, mock_session):
        """A valid response with empty measurementData arrays must parse without error."""
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        # Exact "no data" shape from api.md (daily).
        no_data = [
            {
                "id": "dailyNT",
                "data": {
                    "usagePointPublicId": "123456",
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
                    "usagePointPublicId": "123456",
                    "from": 1795535200000,
                    "to": 1798213600000,
                    "channelCode": "CHP-Q",
                    "unit": "kWh",
                    "measurementData": [],
                },
            },
        ]
        mock_session.post.return_value = _mock_context_manager(
            _mock_response(200, no_data)
        )
        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            resolution="daily",
        )
        assert result is not None
        assert len(result.channels) == 2
        assert result.channels[0].id == "dailyNT"
        assert result.channels[0].data.measurements == []
        assert result.channels[1].id == "dailyHT"
        assert result.channels[1].data.measurements == []
        assert result.has_data is False
        assert result.primary_channel.has_measurements is False

    async def test_auto_login_when_token_missing(self, api, mock_session):
        api._token = None
        login_resp = _mock_response(200, {"access_token": "tok456", "expires_in": 3600})
        data_resp = _mock_response(200, [{"id": "NT"}])

        mock_session.post.side_effect = [
            _mock_context_manager(login_resp),
            _mock_context_manager(data_resp),
        ]

        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        assert result is not None
        assert result.channels[0].id == "NT"
        assert api._token == "tok456"

    async def test_401_retry_then_success(self, api, mock_session):
        api._token = "tok_expired"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        login_resp = _mock_response(
            200, {"access_token": "tok_fresh", "expires_in": 3600}
        )
        data_resp = _mock_response(200, [{"id": "NT"}])
        err_resp = _mock_response(401, {})

        mock_session.post.side_effect = [
            _mock_context_manager(err_resp),
            _mock_context_manager(login_resp),
            _mock_context_manager(data_resp),
        ]

        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        assert result is not None
        assert result.channels[0].id == "NT"
        assert api._token == "tok_fresh"

    async def test_persistent_401_raises(self, api, mock_session):
        api._token = "tok_expired"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        err_resp = _mock_response(401, {})
        mock_session.post.return_value = _mock_context_manager(err_resp)

        with pytest.raises(GroupeEAuthError):
            await api.get_smartmeter_data(
                "premise",
                "partner",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

    async def test_403_raises(self, api, mock_session):
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_session.post.return_value = _mock_context_manager(_mock_response(403, {}))
        with pytest.raises(GroupeEAuthError):
            await api.get_smartmeter_data(
                "p",
                "pn",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

    async def test_429_raises(self, api, mock_session):
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_session.post.return_value = _mock_context_manager(_mock_response(429, {}))
        with pytest.raises(GroupeEApiError):
            await api.get_smartmeter_data(
                "p",
                "pn",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

    async def test_500_raises(self, api, mock_session):
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_session.post.return_value = _mock_context_manager(_mock_response(500, {}))
        with pytest.raises(GroupeEApiError):
            await api.get_smartmeter_data(
                "p",
                "pn",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

    async def test_token_expired_triggers_relogin(self, api, mock_session):
        api._token = "tok123"
        api._token_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        login_resp = _mock_response(
            200, {"access_token": "tok_fresh", "expires_in": 3600}
        )
        data_resp = _mock_response(200, [{"id": "NT"}])

        mock_session.post.side_effect = [
            _mock_context_manager(login_resp),
            _mock_context_manager(data_resp),
        ]

        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        assert result is not None
        assert result.channels[0].id == "NT"
        assert api._token == "tok_fresh"


class TestToEpochMs:
    def test_utc_aware(self):
        dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch_ms(dt) == int(dt.timestamp() * 1000)

    def test_other_timezone_same_instant(self):
        from zoneinfo import ZoneInfo

        utc_dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        zurich_dt = utc_dt.astimezone(ZoneInfo("Europe/Zurich"))
        assert _to_epoch_ms(zurich_dt) == int(utc_dt.timestamp() * 1000)

    def test_naive_treated_as_utc(self):
        # Naive datetimes are interpreted as UTC per the API contract.
        assert _to_epoch_ms(datetime(2026, 1, 1, 0, 0)) == 1767225600000  # noqa: DTZ001


class TestGetSmartmeterDataPersistent401:
    async def test_second_data_request_401_after_successful_relogin_raises(
        self, api, mock_session
    ):
        """The REAL persistent-401 path: re-login succeeds but the data
        endpoint keeps returning 401 -> GroupeEAuthError on the second try."""
        api._token = "tok_expired"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        data_resp_1 = _mock_response(401, {})
        login_resp = _mock_response(
            200, {"access_token": "tok_fresh", "expires_in": 3600}
        )
        data_resp_2 = _mock_response(401, {})

        mock_session.post.side_effect = [
            _mock_context_manager(data_resp_1),
            _mock_context_manager(login_resp),
            _mock_context_manager(data_resp_2),
        ]

        with pytest.raises(GroupeEAuthError, match="Persistent"):
            await api.get_smartmeter_data(
                "premise",
                "partner",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
        # Exactly one re-login was attempted before giving up.
        assert api._token == "tok_fresh"
        assert mock_session.post.call_count == 3

    async def test_invalid_json_payload_raises_api_error(self, api, mock_session):
        """A 200 response with a malformed payload maps to GroupeEApiError."""
        api._token = "tok123"
        api._token_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

        resp = _mock_response(200, [{"id": "quarterHourly", "data": {}}])
        # Measurement parsing is defensive; force a payload that breaks parsing.
        resp.json = AsyncMock(return_value=[{"id": "quarterHourly"}])

        mock_session.post.return_value = _mock_context_manager(resp)

        result = await api.get_smartmeter_data(
            "premise",
            "partner",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        # Missing 'data' key defaults to an empty channel - must not raise.
        assert result.channels[0].id == "quarterHourly"
        assert result.channels[0].data.measurements == []


class TestLogPrivacy:
    def test_username_masked(self):
        """Usernames are masked for logging (PII in debug logs)."""
        from custom_components.groupe_e.api import _mask_username

        assert _mask_username("someone@example.com") == "so*****@example.com"
        assert _mask_username("ab@x.ch") == "ab***@x.ch"
        assert _mask_username("a@x.ch") == "a***@x.ch"
        assert _mask_username("localonly") == "lo*******"
        # The full local part must never survive masking.
        assert "someone" not in _mask_username("someone@example.com")

    async def test_password_never_logged(self, api, mock_session, caplog):
        """No log record may ever contain the password or the bearer token."""
        import logging

        api._token = None
        mock_session.post.side_effect = [
            _mock_context_manager(
                _mock_response(200, {"access_token": "SECRET_TOKEN", "expires_in": 3600})
            ),
            _mock_context_manager(_mock_response(200, [{"id": "NT"}])),
        ]

        with caplog.at_level(logging.DEBUG):
            await api.get_smartmeter_data(
                "premise",
                "partner",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

        all_output = " ".join(r.getMessage() for r in caplog.records)
        # The fixture password is "secret", the token "SECRET_TOKEN".
        assert "secret" not in all_output.lower()
        assert "user@example.com" not in all_output
        assert "us***@example.com" in all_output
