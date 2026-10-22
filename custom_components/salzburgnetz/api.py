"""Client and parser for the Salzburg Netz service portal API."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import API_BASE, OBIS_CONSUMPTION, OBIS_FEED_IN

_LOGGER = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Vienna")


class SalzburgNetzError(Exception):
    """Generic API error."""


class SalzburgNetzAuthError(SalzburgNetzError):
    """API key rejected."""


class SalzburgNetzRateLimited(SalzburgNetzError):
    """Daily request limit reached."""

    def __init__(self, retry_after: timedelta) -> None:
        super().__init__(f"rate limited, retry after {retry_after}")
        self.retry_after = retry_after


class SalzburgNetzApi:
    """Minimal client for the load profile endpoint."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, gpnr: str, zp: str
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._gpnr = gpnr
        self._zp = zp

    async def async_get_profile(self, start: date, end: date) -> Any:
        """Fetch 15-minute load profile rows for start..end (dates inclusive)."""
        body = {
            "GPNR": self._gpnr,
            "ZP": self._zp,
            "AB": start.isoformat(),
            "BIS": end.isoformat(),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        try:
            async with self._session.post(
                f"{API_BASE}/profile",
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status in (401, 403):
                    raise SalzburgNetzAuthError(f"HTTP {resp.status}")
                if resp.status == 429:
                    raise SalzburgNetzRateLimited(_retry_after(resp.headers))
                if resp.status >= 400:
                    text = (await resp.text())[:200]
                    raise SalzburgNetzError(f"HTTP {resp.status}: {text}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SalzburgNetzError(str(err)) from err


def _retry_after(headers: Any) -> timedelta:
    """Read the retry delay; the API sends it in hours, sometimes as 'Retry--After'."""
    for name in ("Retry-After", "Retry--After"):
        value = headers.get(name)
        if value:
            match = re.search(r"\d+(?:[.,]\d+)?", str(value))
            if match:
                return timedelta(hours=float(match.group().replace(",", ".")))
    return timedelta(hours=24)


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Find the list of row dicts, whether top level or wrapped in an object."""
    if isinstance(payload, list):
        if payload and all(isinstance(r, dict) for r in payload):
            return payload
        for item in payload:
            if found := _rows(item):
                return found
        return []
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, (list, dict)) and (found := _rows(value)):
                return found
    return []


def _get(row: dict[str, Any], *names: str) -> Any:
    lowered = {k.lower(): v for k, v in row.items()}
    for name in names:
        if (value := lowered.get(name.lower())) not in (None, ""):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_number(value: Any) -> float | None:
    """'0,013' -> 0.013; '1.234,5' -> 1234.5; plain numbers pass through."""
    if isinstance(value, str) and "," not in value:
        try:
            return float(value.strip())
        except ValueError:
            return None
    return _to_float(value)


def _parse_offset(value: Any) -> timezone | None:
    """'+1', '+01:00', '2' -> fixed UTC offset."""
    if value is None:
        return None
    match = re.fullmatch(r"\s*([+-]?)(\d{1,2})(?::?(\d{2}))?\s*", str(value))
    if not match:
        return None
    sign = -1 if match.group(1) == "-" else 1
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3) or 0))
    return timezone(sign * delta)


def _parse_start(row: dict[str, Any], seen: set[tuple[str, str]]) -> datetime | None:
    """Start of the quarter hour as an aware UTC datetime."""
    day = _get(row, "Datum", "Date")
    time = _get(row, "Uhrzeit", "Zeit", "Time")
    if not day or not time:
        return None
    day, time = str(day).strip(), str(time).strip()
    try:
        if "-" in day:
            naive_day = datetime.strptime(day[:10], "%Y-%m-%d")
        else:
            naive_day = datetime.strptime(day, "%d.%m.%Y")
        parts = [int(p) for p in time.split(":")]
    except ValueError:
        return None
    naive = naive_day + timedelta(hours=parts[0], minutes=parts[1] if len(parts) > 1 else 0)
    if (offset := _parse_offset(_get(row, "UTC"))) is not None:
        local = naive.replace(tzinfo=offset)
    else:
        # No offset given: the repeated hour when summer time ends comes twice.
        key = (day, time)
        local = naive.replace(tzinfo=LOCAL_TZ, fold=1 if key in seen else 0)
        seen.add(key)
    return local.astimezone(timezone.utc)


def parse_profile(payload: Any) -> dict[str, dict[int, float]]:
    """Sum the 15-minute kWh values into hours.

    Returns {"consumption": {hour_start_epoch: kWh}, "feed_in": {...}}.
    """
    result: dict[str, dict[int, float]] = {
        "consumption": defaultdict(float),
        "feed_in": defaultdict(float),
    }
    seen: set[tuple[str, str]] = set()
    for row in _rows(payload):
        obis = str(_get(row, "OBIS") or OBIS_CONSUMPTION)
        if obis.startswith(OBIS_CONSUMPTION):
            kind = "consumption"
        elif obis.startswith(OBIS_FEED_IN):
            kind = "feed_in"
        else:
            continue
        value = _parse_number(_get(row, "Wert", "Value"))
        start = _parse_start(row, seen)
        if value is None or start is None:
            continue
        unit = str(_get(row, "Einheit", "Unit") or "kWh").strip().lower()
        if unit == "wh":
            value /= 1000
        hour = start.replace(minute=0, second=0, microsecond=0)
        result[kind][int(hour.timestamp())] += value
    return {kind: {h: round(v, 6) for h, v in hours.items()} for kind, hours in result.items()}
