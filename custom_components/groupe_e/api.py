import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from aiohttp import ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)


class GroupeEAuthError(Exception):
    """Authentication or authorization failed."""


class GroupeEApiError(Exception):
    """Groupe-E API request failed."""


_TOKEN_GRACE = 60


class GroupeEAPI:
    """Class to interact with Groupe-E API."""

    LOGIN_URL = (
        "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/token"
    )
    DATA_URL = "https://my.groupe-e.ch/api/smartmeter-data"
    REQUEST_TIMEOUT = 30

    def __init__(self, session: ClientSession, username: str, password: str):
        """Initialize the API client with an aiohttp session and credentials."""
        self._session = session
        self._username = username
        self._password = password
        self._token = None
        self._token_expires_at: datetime | None = None

    @property
    def _token_expired(self) -> bool:
        """Return True if the current token has expired or no token exists."""
        if self._token_expires_at is None:
            return True
        return datetime.now(timezone.utc) >= self._token_expires_at

    async def _async_login(self) -> None:
        """Authenticate with Groupe-E and store the access token."""
        payload = {
            "grant_type": "password",
            "client_id": "portal",
            "username": self._username,
            "password": self._password,
        }
        try:
            async with self._session.post(
                self.LOGIN_URL,
                data=payload,
                timeout=ClientTimeout(total=self.REQUEST_TIMEOUT),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    self._token = data.get("access_token")
                    expires_in = max(int(data.get("expires_in", 300)), _TOKEN_GRACE)
                    self._token_expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=expires_in - _TOKEN_GRACE
                    )
                    return
                _LOGGER.error("Login failed with status %s", response.status)
                self._token = None
                self._token_expires_at = None
                raise GroupeEAuthError(f"Login failed with status {response.status}")
        except GroupeEAuthError:
            raise
        except asyncio.TimeoutError as err:
            _LOGGER.error("Login timed out")
            self._token = None
            self._token_expires_at = None
            raise GroupeEAuthError("Login timed out") from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Login connection error: %s", err)
            self._token = None
            self._token_expires_at = None
            raise GroupeEAuthError(f"Login connection failed: {err}") from err

    async def get_smartmeter_data(
        self,
        premise: str,
        partner: str,
        start: datetime,
        end: datetime,
        resolution: str = "quarter-hourly",
    ) -> list[dict[str, Any]] | None:
        """Fetch smart meter data from the Groupe-E API.

        Automatically re-authenticates if the token is expired or on 401.
        Returns a list of channel dicts or None.
        """
        if not self._token or self._token_expired:
            await self._async_login()

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

        start_ts = int(start.timestamp() * 1000)
        end_ts = int(end.timestamp() * 1000)

        payload = {
            "premise": premise,
            "partner": partner,
            "start": start_ts,
            "end": end_ts,
            "resolution": resolution,
        }

        _LOGGER.debug(
            "Requesting Groupe-E data: resolution=%s, start=%s, end=%s",
            resolution,
            start,
            end,
        )

        timeout = ClientTimeout(total=self.REQUEST_TIMEOUT)

        for attempt in range(3):
            try:
                async with self._session.post(
                    self.DATA_URL,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if response.status == 401:
                        if attempt == 0:
                            self._token = None
                            self._token_expires_at = None
                            await self._async_login()
                            headers["Authorization"] = f"Bearer {self._token}"
                            continue
                        _LOGGER.error("Persistent 401 after re-login")
                        raise GroupeEAuthError("Persistent authentication failure")

                    if response.status == 403:
                        raise GroupeEAuthError("Access forbidden (403)")

                    if response.status == 429:
                        raise GroupeEApiError("Rate limited (429)")

                    if response.status >= 500:
                        raise GroupeEApiError(f"Server error (HTTP {response.status})")

                    response.raise_for_status()
                    data = await response.json()
                    _LOGGER.debug(
                        "Received %d Groupe-E channels for resolution=%s",
                        len(data) if isinstance(data, list) else 0,
                        resolution,
                    )
                    return data

            except GroupeEAuthError:
                raise
            except GroupeEApiError:
                raise
            except asyncio.TimeoutError as err:
                raise GroupeEApiError("Request timed out") from err
            except aiohttp.ClientError as err:
                raise GroupeEApiError(f"Request failed: {err}") from err

        return None
