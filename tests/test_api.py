"""Tests for the Groupe-E API client using pytest-homeassistant-custom-component."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import ClientSession

from custom_components.groupe_e.api import (
    GroupeEAPI,
    GroupeEAuthError,
    GroupeEApiError,
)
from datetime import datetime, timezone


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
        assert result == expected

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
        assert result == [{"id": "NT"}]
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
        assert result == [{"id": "NT"}]
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
        assert result == [{"id": "NT"}]
        assert api._token == "tok_fresh"
