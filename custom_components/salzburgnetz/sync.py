"""Daily sync of Salzburg Netz load profiles into long-term statistics."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    LOCAL_TZ,
    SalzburgNetzApi,
    SalzburgNetzAuthError,
    SalzburgNetzError,
    SalzburgNetzRateLimited,
    parse_profile,
)
from .const import (
    BACKFILL_CHUNKS_PER_DAY,
    CHUNK_DAYS,
    CONF_API_KEY,
    CONF_GPNR,
    CONF_ZP,
    DOMAIN,
    HISTORY_DAYS,
    RECENT_DAYS,
    SIGNAL_UPDATED,
    SYNC_HOUR,
    SYNC_MINUTE,
)

try:  # Home Assistant 2025.4+
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # pragma: no cover
    StatisticMeanType = None

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
KINDS = {"consumption": "Consumption", "feed_in": "Feed-in"}


def statistic_id(zp: str, kind: str) -> str:
    """e.g. salzburgnetz:consumption_2197186."""
    return f"{DOMAIN}:{kind}_{zp[-7:].lower()}"


def _metadata(stat_id: str, name: str) -> StatisticMetaData:
    meta: dict[str, Any] = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": stat_id,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    fields = getattr(StatisticMetaData, "__annotations__", {})
    if StatisticMeanType is not None and "mean_type" in fields:
        meta["mean_type"] = StatisticMeanType.NONE
    else:
        meta["has_mean"] = False
    if "unit_class" in fields:
        meta["unit_class"] = "energy"
    return meta  # type: ignore[return-value]


class SalzburgNetzSync:
    """Fetches the profile once a day and writes hourly statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.zp: str = entry.data[CONF_ZP]
        self.api = SalzburgNetzApi(
            async_get_clientsession(hass),
            entry.data[CONF_API_KEY],
            entry.data[CONF_GPNR],
            self.zp,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.hours: dict[str, dict[int, float]] = {k: {} for k in KINDS}
        self.state: dict[str, Any] = {}
        self.status = "waiting for first sync"
        self._running = False
        self._pending: dict[str, int] = {}
        self._unsubs: list = []

    # --- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        for kind in KINDS:
            self.hours[kind] = {
                int(k): v for k, v in stored.get("hours", {}).get(kind, {}).items()
            }
        self.state = stored.get("state", {})
        if self.state.get("last_error"):
            self.status = self.state["last_error"]
        elif self.state.get("last_sync"):
            self.status = "ok"

        self._unsubs.append(
            async_track_time_change(
                self.hass, self._scheduled, hour=SYNC_HOUR, minute=SYNC_MINUTE, second=0
            )
        )
        if self._due_now():
            # Catch up shortly after start-up (first install, or HA was off at sync time).
            self._unsubs.append(async_call_later(self.hass, 30, self._scheduled))

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_remove(self) -> None:
        await self._store.async_remove()
        get_instance(self.hass).async_clear_statistics(
            [statistic_id(self.zp, kind) for kind in KINDS]
        )

    def _due_now(self) -> bool:
        now = dt_util.now(LOCAL_TZ)
        if not self.state.get("last_sync") or self.state.get("auth_failed"):
            # First install, or a new key was just pasted after the old one was rejected.
            return True
        if self.state["last_sync"] == now.date().isoformat():
            return False
        return (now.hour, now.minute) >= (SYNC_HOUR, SYNC_MINUTE)

    async def _scheduled(self, _now: datetime | None = None) -> None:
        await self.async_sync()

    # --- sync ------------------------------------------------------------

    async def async_sync(self) -> None:
        """Run the daily requests: recent days, plus older history while backfilling."""
        if self._running:
            return
        blocked = self.state.get("blocked_until")
        if blocked and dt_util.utcnow() < datetime.fromisoformat(blocked):
            _LOGGER.info("Salzburg Netz daily limit reached, waiting until %s", blocked)
            return
        self._running = True
        try:
            await self._sync()
        finally:
            # One write per run, from the oldest hour that changed.
            for kind, from_hour in self._pending.items():
                self._push(kind, from_hour)
            self._pending.clear()
            self._running = False
            await self._save()
            async_dispatcher_send(self.hass, SIGNAL_UPDATED.format(self.entry.entry_id))

    async def _sync(self) -> None:
        today = dt_util.now(LOCAL_TZ).date()
        first_run = not self.state.get("last_sync")
        oldest_allowed = today - timedelta(days=HISTORY_DAYS - 1)

        # Recent window. On the very first run take a whole chunk, so history starts right away.
        start = today - timedelta(days=(CHUNK_DAYS if first_run else RECENT_DAYS) - 1)
        if not await self._fetch(start, today):
            return
        if first_run:
            self.state["backfill_before"] = start.isoformat()
        self.state["last_sync"] = today.isoformat()

        for _ in range(0 if first_run else BACKFILL_CHUNKS_PER_DAY):
            if self.state.get("backfill_done"):
                break
            before = date.fromisoformat(self.state.get("backfill_before", today.isoformat()))
            end = before - timedelta(days=1)
            if end < oldest_allowed:
                self.state["backfill_done"] = True
                break
            chunk_start = max(end - timedelta(days=CHUNK_DAYS - 1), oldest_allowed)
            new_rows = await self._fetch(chunk_start, end)
            if new_rows is None:
                break
            self.state["backfill_before"] = chunk_start.isoformat()
            if new_rows == 0:
                # Nothing older than this: the meter (or its smart readout) starts here.
                self.state["backfill_done"] = True

    async def _fetch(self, start: date, end: date) -> int | None:
        """Fetch one range and store it. Returns hours received, or None on error."""
        _LOGGER.debug("Fetching Salzburg Netz profile %s..%s", start, end)
        try:
            payload = await self.api.async_get_profile(start, end)
        except SalzburgNetzRateLimited as err:
            until = dt_util.utcnow() + err.retry_after
            self.state["blocked_until"] = until.isoformat()
            self._set_error(f"daily request limit reached, next try after {dt_util.as_local(until):%d.%m. %H:%M}")
            return None
        except SalzburgNetzAuthError:
            self._set_error("API key rejected (expired or deleted?)")
            self.state["auth_failed"] = True
            persistent_notification.async_create(
                self.hass,
                "Salzburg Netz rejected the API key. Create a new key in the "
                "Salzburg Netz service portal (Kundenkonto → Mein Benutzerkonto → "
                "API Schlüssel), then in Home Assistant open Settings → Devices & "
                "services → Salzburg Netz → ⋮ → Reconfigure and paste it.",
                title="Salzburg Netz: API key",
                notification_id=f"{DOMAIN}_auth_{self.entry.entry_id}",
            )
            return None
        except SalzburgNetzError as err:
            self._set_error(f"request failed: {err}")
            return None

        parsed = parse_profile(payload)
        count = 0
        for kind, hours in parsed.items():
            if not hours:
                continue
            count += len(hours)
            changed = [h for h, v in hours.items() if self.hours[kind].get(h) != v]
            if changed:
                self.hours[kind].update(hours)
                self._pending[kind] = min(changed + [self._pending.get(kind, changed[0])])
        self.state.pop("blocked_until", None)
        self.state.pop("last_error", None)
        self.state.pop("auth_failed", None)
        self.status = "ok"
        return count

    @callback
    def _push(self, kind: str, from_hour: int) -> None:
        """Write hourly rows from from_hour on, with the running total from the start."""
        stat_id = statistic_id(self.zp, kind)
        name = f"{self.entry.title} {KINDS[kind].lower()}"
        total = 0.0
        rows: list[StatisticData] = []
        for hour in sorted(self.hours[kind]):
            value = self.hours[kind][hour]
            total += value
            if hour >= from_hour:
                rows.append(
                    StatisticData(
                        start=datetime.fromtimestamp(hour, timezone.utc),
                        state=value,
                        sum=round(total, 6),
                    )
                )
        if rows:
            async_add_external_statistics(self.hass, _metadata(stat_id, name), rows)

    def _set_error(self, message: str) -> None:
        _LOGGER.warning("Salzburg Netz: %s", message)
        self.status = message
        self.state["last_error"] = message

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "hours": {
                    kind: {str(h): v for h, v in hours.items()}
                    for kind, hours in self.hours.items()
                },
                "state": self.state,
            }
        )

    # --- values for the sensors ------------------------------------------

    def last_full_day(self) -> tuple[date, float] | None:
        """Most recent local day with all its hours present."""
        days: dict[date, list[float]] = {}
        for hour, value in self.hours["consumption"].items():
            day = datetime.fromtimestamp(hour, LOCAL_TZ).date()
            days.setdefault(day, []).append(value)
        for day in sorted(days, reverse=True):
            start = datetime.combine(day, datetime.min.time(), LOCAL_TZ)
            # 23 or 25 hours on clock-change days
            midnight_next = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL_TZ)
            expected = round((midnight_next.timestamp() - start.timestamp()) / 3600)
            if len(days[day]) >= expected:
                return day, round(sum(days[day]), 3)
        return None

    def data_until(self) -> datetime | None:
        if not self.hours["consumption"]:
            return None
        return datetime.fromtimestamp(max(self.hours["consumption"]) + 3600, timezone.utc)

    def history_from(self) -> date | None:
        if not self.hours["consumption"]:
            return None
        return datetime.fromtimestamp(min(self.hours["consumption"]), LOCAL_TZ).date()
