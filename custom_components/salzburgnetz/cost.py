"""Electricity cost from the hourly consumption and a price that changes over time.

Kept free of Home Assistant imports so the arithmetic can be tested on its own.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, tzinfo

# A price timeline is a list of [valid_from_timestamp, price_per_kwh], sorted by time.
Timeline = list[list[float]]


def valid_from_timestamp(valid_from: object, fallback: float, tz: tzinfo) -> float:
    """Start of a price: its `valid_from` date (local midnight), else the fallback time."""
    if isinstance(valid_from, str) and valid_from:
        try:
            if len(valid_from) == 10:
                day = date.fromisoformat(valid_from)
                return datetime(day.year, day.month, day.day, tzinfo=tz).timestamp()
            parsed = datetime.fromisoformat(valid_from)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=tz)
            return parsed.timestamp()
        except ValueError:
            pass
    return fallback


def add_price(timeline: Timeline, start: float, price: float) -> tuple[Timeline, float | None]:
    """Insert or replace a price. Returns the new timeline and the first changed time.

    A price that starts earlier than prices already known replaces those later ones
    (the supplier corrected or back-dated it). Returns None as changed time when the
    timeline already says exactly this.
    """
    kept = [p for p in timeline if p[0] < start]
    if len(kept) == len(timeline) and kept and kept[-1][1] == price:
        return timeline, None  # same price simply continues
    new = kept + [[start, price]]
    if new == timeline:
        return timeline, None
    return new, start


def price_at(timeline: Timeline, hour: float) -> float | None:
    """Price valid at a given hour start, or None before the first known price."""
    starts = [p[0] for p in timeline]
    i = bisect_right(starts, hour) - 1
    return timeline[i][1] if i >= 0 else None


def cost_rows(
    hours: dict[int, float], timeline: Timeline, from_hour: float
) -> list[tuple[int, float, float]]:
    """(hour, cost, running sum) for every hour from from_hour on that has a price.

    The running sum starts at the first priced hour, so it is the same whichever
    hour the write starts from.
    """
    total = 0.0
    rows: list[tuple[int, float, float]] = []
    for hour in sorted(hours):
        price = price_at(timeline, hour)
        if price is None:
            continue
        cost = hours[hour] * price
        total += cost
        if hour >= from_hour:
            rows.append((hour, round(cost, 6), round(total, 6)))
    return rows
