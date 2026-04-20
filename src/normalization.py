from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
)

DATE_FORMATS_NO_YEAR = (
    "%b %d",
    "%B %d",
    "%m/%d",
)

TIME_FORMATS = (
    "%I:%M %p",
    "%I:%M%p",
    "%I %p",
    "%H:%M",
)

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

def normalize_request(
    request: dict[str, Any], reference_date: date | None = None
) -> tuple[dict[str, Any], list[str]]:
    normalized = deepcopy(request)
    errors: list[str] = []
    current_date = reference_date or date.today()

    if "date" in normalized and normalized.get("date") not in (None, ""):
        normalized_date = _normalize_date(normalized["date"], current_date)
        if normalized_date is None:
            errors.append("unrecognized_date_format")
        else:
            normalized["date"] = normalized_date

    if normalized.get("time") not in (None, ""):
        normalized_time = _normalize_time(normalized["time"])
        if normalized_time is None:
            errors.append("unrecognized_time_format")
        else:
            normalized["time"] = normalized_time

    time_range = normalized.get("time_range")
    if time_range not in (None, ""):
        normalized_range = _normalize_time_range(time_range)
        if normalized_range is None:
            errors.append("unrecognized_time_range_format")
        else:
            normalized["time_range"] = normalized_range

    return normalized, errors


def _normalize_date(value: Any, reference_date: date) -> str | None:
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None
    lowered = candidate.lower()

    if lowered in {"today", "tonight"}:
        return reference_date.strftime("%Y-%m-%d")

    if lowered in WEEKDAYS:
        target_weekday = WEEKDAYS[lowered]
        days_ahead = (target_weekday - reference_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target_date = reference_date + timedelta(days=days_ahead)
        return target_date.strftime("%Y-%m-%d")

    for date_format in DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, date_format)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    for date_format in DATE_FORMATS_NO_YEAR:
        try:
            parsed = datetime.strptime(candidate, date_format)
            parsed_with_year = parsed.replace(year=reference_date.year)
            return parsed_with_year.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _normalize_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    candidate = " ".join(value.strip().upper().split())
    if not candidate:
        return None

    for time_format in TIME_FORMATS:
        try:
            parsed = datetime.strptime(candidate, time_format)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue
    return None


def _normalize_time_range(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None

    earliest = _normalize_time(value.get("earliest"))
    latest = _normalize_time(value.get("latest"))
    if earliest is None or latest is None:
        return None

    return {"earliest": earliest, "latest": latest}
