"""Data models for the Groupe-E smart meter API responses.

The Groupe-E endpoint ``/api/smartmeter-data`` returns a list of channel objects,
one per tariff. Each channel carries an ``id`` plus a nested ``data`` object that
holds the measurement series. Depending on the requested resolution, the channel
ids differ:

- ``quarterHourly`` — power in kW
- ``dailyNT`` / ``dailyHT`` — energy in kWh (normal/high tariff)
- ``monthlyNT`` / ``monthlyHT`` — energy in kWh (normal/high tariff)

See ``api.md`` for concrete example payloads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar


@dataclass(slots=True)
class Measurement:
    """A single reading within a channel's measurementData array.

    The API returns timestamps as UTC epoch milliseconds. ``from_dict``
    converts them to UTC-aware datetimes and ``value`` to a float at parse
    time. Malformed API payloads therefore raise during :meth:`from_dict`
    instead of being silently skipped downstream.
    """

    timestamp: datetime
    value: float
    status: str = "W"

    def __post_init__(self) -> None:
        # Reject bools: they would silently coerce to 0.0/1.0.
        if isinstance(self.timestamp, bool) or isinstance(self.value, bool):
            raise TypeError(f"Invalid measurement type: {self!r}")
        if not isinstance(self.timestamp, datetime):
            raise TypeError(
                f"Invalid measurement timestamp type: {type(self.timestamp).__name__}"
            )
        if self.timestamp.tzinfo is None:
            raise ValueError("measurement timestamp must be timezone-aware")
        if isinstance(self.value, int):
            self.value = float(self.value)
        elif not isinstance(self.value, float):
            raise TypeError(
                f"Invalid measurement value type: {type(self.value).__name__}"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Measurement:
        """Build a Measurement from the raw API payload.

        Raises TypeError/KeyError/ValueError when timestamp or value is missing,
        non-numeric, or boolean.
        """
        raw_ts = data["timestamp"]
        raw_value = data["value"]
        if isinstance(raw_ts, bool) or isinstance(raw_value, bool):
            raise TypeError(
                f"Invalid measurement payload (bool): timestamp={raw_ts!r} value={raw_value!r}"
            )
        return cls(
            timestamp=datetime.fromtimestamp(
                float(raw_ts) / 1000, tz=timezone.utc
            ),
            value=float(raw_value),
            status=str(data.get("status", "W")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": int(self.timestamp.timestamp() * 1000),
            "value": self.value,
        }


@dataclass(slots=True)
class ChannelData:
    """Metadata and measurement series for a single channel.

    ``measurementData`` may legitimately be empty (``[]``) when the requested
    window contains no data; see the "no data" examples in ``api.md``.
    """

    usage_point_public_id: str
    from_time: int  # UTC epoch milliseconds
    to_time: int  # UTC epoch milliseconds
    channel_code: str
    unit: str
    measurements: list[Measurement] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChannelData:
        raw_measurements = data.get("measurementData") or []
        return cls(
            usage_point_public_id=str(data.get("usagePointPublicId", "")),
            from_time=int(data.get("from", 0)),
            to_time=int(data.get("to", 0)),
            channel_code=str(data.get("channelCode", "")),
            unit=str(data.get("unit", "")),
            measurements=[
                Measurement.from_dict(m)
                for m in raw_measurements
                if isinstance(m, dict)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "usagePointPublicId": self.usage_point_public_id,
            "from": self.from_time,
            "to": self.to_time,
            "channelCode": self.channel_code,
            "unit": self.unit,
            "measurementData": [m.to_dict() for m in self.measurements],
        }


@dataclass(slots=True)
class SmartMeterChannel:
    """One entry of the top-level API response list."""

    id: str
    data: ChannelData

    # Known channel ids that are high-tariff (HT) series. Normal (NT) are the rest.
    HIGH_TARIFF_IDS: ClassVar[set[str]] = {"dailyHT", "monthlyHT"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmartMeterChannel:
        return cls(
            id=str(data.get("id", "")),
            data=ChannelData.from_dict(data.get("data") or {}),
        )

    @property
    def is_high_tariff(self) -> bool:
        """Return True when the channel id marks a high-tariff series."""
        return self.id in self.HIGH_TARIFF_IDS

    @property
    def has_measurements(self) -> bool:
        """Return True when the channel carries at least one reading."""
        return bool(self.data.measurements)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "data": self.data.to_dict()}


@dataclass(slots=True)
class SmartMeterResponse:
    """Full parsed response from the ``/api/smartmeter-data`` endpoint."""

    channels: list[SmartMeterChannel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> SmartMeterResponse:
        if not isinstance(data, list):
            return cls(channels=[])
        return cls(
            channels=[
                SmartMeterChannel.from_dict(c) for c in data if isinstance(c, dict)
            ]
        )

    @classmethod
    def from_json(cls, json_text: str) -> SmartMeterResponse:
        return cls.from_dict(json.loads(json_text))

    @property
    def primary_channel(self) -> SmartMeterChannel | None:
        """Return the first channel, or None when the response is empty."""
        return self.channels[0] if self.channels else None

    @property
    def measurement_channels(self) -> list[SmartMeterChannel]:
        """Return all channels that actually carry measurements."""
        return [c for c in self.channels if c.has_measurements]

    @property
    def measurements(self) -> list[Measurement]:
        """Flatten all measurements across channels (in channel order)."""
        return [m for c in self.channels for m in c.data.measurements]

    @property
    def has_data(self) -> bool:
        """Return True when at least one channel carries a reading.

        An API response with channels but empty ``measurementData`` arrays is a
        valid "no data" response (see ``api.md``), not an error.
        """
        return any(c.has_measurements for c in self.channels)

    def to_dict(self) -> Any:
        return [c.to_dict() for c in self.channels]
