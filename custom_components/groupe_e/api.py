"""Groupe-E API client with token caching and automatic re-authentication."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from .const import LOGIN_URL
from .models import SmartMeterResponse

_LOGGER = logging.getLogger(__name__)


class GroupeEAuthError(Exception):
    """Authentication or authorization failed."""


class GroupeEApiError(Exception):
    """Groupe-E API request failed."""


# Re-login this many seconds before the token actually expires.
_TOKEN_GRACE = 60


def _to_epoch_ms(dt: datetime) -> int:
    """Convert a datetime to epoch milliseconds for the API payload.

    The Groupe-E API always works in UTC. Aware datetimes keep their absolute
    instant; naive datetimes are interpreted as UTC per the API contract.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _mask_username(username: str) -> str:
    """Mask a username for logging, keeping enough to identify the account.

    'someone@example.com' -> 'so*****@example.com'
    """
    if "@" in username:
        local, _, domain = username.partition("@")
        return f"{local[:2]}{'*' * max(len(local) - 2, 3)}@{domain}"
    return f"{username[:2]}{'*' * max(len(username) - 2, 3)}"


class GroupeEAPI:
    """Class to interact with Groupe-E API."""

    LOGIN_URL = LOGIN_URL
    DATA_URL = "https://my.groupe-e.ch/api/smartmeter-data"
    REQUEST_TIMEOUT = 30

    def __init__(self, session: ClientSession, username: str, password: str):
        """Initialize the API client with an aiohttp session and credentials."""
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def _token_expired(self) -> bool:
        """Return True if the current token has expired or no token exists."""
        if self._token_expires_at is None:
            return True
        return datetime.now(timezone.utc) >= self._token_expires_at

    def _clear_token(self) -> None:
        """Forget the current token."""
        _LOGGER.debug("Clearing stored token")
        self._token = None
        self._token_expires_at = None

    async def async_validate_credentials(
        self, premise: str, partner: str
    ) -> None:
        """Validate all settings against the live API.

        Authenticates (raising GroupeEAuthError for bad credentials) and then
        fetches a minimal data window so invalid premise/partner IDs surface
        as GroupeEApiError. Used by the config flow.
        """
        await self._async_login()
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=1)
        _LOGGER.debug(
            "Validating premise=%s partner=%s with minimal data fetch",
            premise,
            partner,
        )
        await self.get_smartmeter_data(premise, partner, start, end)

    async def _async_login(self) -> None:
        """Authenticate with Groupe-E and store the access token."""
        _LOGGER.debug("Logging in as %s", _mask_username(self._username))
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
                if response.status != 200:
                    self._clear_token()
                    raise GroupeEAuthError(
                        f"Login failed with status {response.status}"
                    )
                data = await response.json()
                self._token = data.get("access_token")
                expires_in = max(int(data.get("expires_in", 300)), _TOKEN_GRACE)
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in - _TOKEN_GRACE
                )
                _LOGGER.debug(
                    "Login successful, token valid for %ds (grace applied)",
                    expires_in - _TOKEN_GRACE,
                )
        except asyncio.TimeoutError as err:
            self._clear_token()
            raise GroupeEAuthError("Login timed out") from err
        except aiohttp.ClientError as err:
            self._clear_token()
            raise GroupeEAuthError(f"Login connection failed: {err}") from err

    async def get_smartmeter_data(
        self,
        premise: str,
        partner: str,
        start: datetime,
        end: datetime,
        resolution: str = "quarter-hourly",
    ) -> SmartMeterResponse:
        """Fetch smart meter data from the Groupe-E API.

        ``start``/``end`` may be any tz-aware datetime; the instant is converted
        to a UTC epoch-millisecond payload (naive datetimes are treated as UTC).
        Automatically re-authenticates if the token is expired or on 401
        (one re-login retry), then raises GroupeEAuthError if it still fails.

        Returns a parsed SmartMeterResponse or raises GroupeEApiError /
        GroupeEAuthError. Never returns None.
        """
        if not self._token or self._token_expired:
            _LOGGER.debug(
                "Token %s, re-authenticating before data request",
                "missing" if not self._token else "expired",
            )
            await self._async_login()

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

        payload = {
            "premise": premise,
            "partner": partner,
            "start": _to_epoch_ms(start),
            "end": _to_epoch_ms(end),
            "resolution": resolution,
        }

        _LOGGER.debug(
            "Requesting Groupe-E data: resolution=%s, start=%s, end=%s",
            resolution,
            start,
            end,
        )

        timeout = ClientTimeout(total=self.REQUEST_TIMEOUT)
        request_started = datetime.now(timezone.utc)

        for attempt in range(2):
            try:
                async with self._session.post(
                    self.DATA_URL,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if response.status == 401:
                        if attempt == 0:
                            # Token may have been revoked server-side: re-login once.
                            _LOGGER.debug("Got 401, re-authenticating")
                            self._clear_token()
                            await self._async_login()
                            headers["Authorization"] = f"Bearer {self._token}"
                            continue
                        raise GroupeEAuthError(
                            "Persistent authentication failure (401)"
                        )
                    if response.status == 403:
                        raise GroupeEAuthError("Access forbidden (403)")
                    if response.status == 429:
                        raise GroupeEApiError("Rate limited (429)")
                    if response.status >= 500:
                        raise GroupeEApiError(
                            f"Server error (HTTP {response.status})"
                        )
                    if response.status >= 400:
                        raise GroupeEApiError(
                            f"Unexpected HTTP {response.status}"
                        )

                    raw = await response.json()
                    _LOGGER.debug(
                        "Data request succeeded in %.2fs (HTTP %s)",
                        (datetime.now(timezone.utc) - request_started).total_seconds(),
                        response.status,
                    )
                    parsed = SmartMeterResponse.from_dict(raw)
                    _LOGGER.debug(
                        "Received %d Groupe-E channels for resolution=%s",
                        len(parsed.channels),
                        resolution,
                    )
                    return parsed

            except (GroupeEAuthError, GroupeEApiError):
                raise
            except asyncio.TimeoutError as err:
                raise GroupeEApiError("Request timed out") from err
            except aiohttp.ClientError as err:
                raise GroupeEApiError(f"Request failed: {err}") from err
            except (KeyError, TypeError, ValueError) as err:
                raise GroupeEApiError(f"Invalid response payload: {err}") from err

        raise GroupeEApiError("Unreachable")  # pragma: no cover
