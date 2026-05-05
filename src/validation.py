from __future__ import annotations

import re
from datetime import datetime
from typing import Any

TIME_PATTERN = re.compile(r"^(0?[1-9]|1[0-2]):[0-5][0-9] (AM|PM)$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9()\-\s]{10,}$")


def validate_request(request: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    required_fields = [
        "restaurant_name",
        "location",
        "date",
        "party_size",
        "user_name",
        "user_email",
        "user_phone",
    ]

    for field in required_fields:
        if field not in request or request[field] in (None, ""):
            errors.append(f"missing_required_field:{field}")

    if "date" in request and request.get("date") not in (None, ""):
        if not _is_valid_date(request["date"]):
            errors.append("invalid_date")

    if "party_size" in request and request.get("party_size") not in (None, ""):
        party_size = request["party_size"]
        if not isinstance(party_size, int) or party_size <= 0:
            errors.append("invalid_party_size")

    has_time = request.get("time") not in (None, "")
    has_time_range = request.get("time_range") not in (None, "")

    if has_time and has_time_range:
        errors.append("invalid_time_input")
    elif not has_time and not has_time_range:
        errors.append("missing_time_or_time_range")
    elif has_time:
        if not _is_valid_time(request["time"]):
            errors.append("invalid_time")
    else:
        if not _is_valid_time_range(request.get("time_range")):
            errors.append("invalid_time_range")

    if "user_email" in request and request.get("user_email") not in (None, ""):
        if not _is_valid_email(request["user_email"]):
            errors.append("invalid_email")

    if "user_phone" in request and request.get("user_phone") not in (None, ""):
        if not _is_valid_phone(request["user_phone"]):
            errors.append("invalid_phone")

    return errors


def _is_valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def _is_valid_time(value: Any) -> bool:
    return isinstance(value, str) and bool(TIME_PATTERN.match(value))


def _is_valid_time_range(value: Any) -> bool:
    if not isinstance(value, dict):
        return False

    earliest = value.get("earliest")
    latest = value.get("latest")
    if not _is_valid_time(earliest) or not _is_valid_time(latest):
        return False

    earliest_minutes = _to_minutes(earliest)
    latest_minutes = _to_minutes(latest)
    return earliest_minutes <= latest_minutes


def _is_valid_email(value: Any) -> bool:
    return isinstance(value, str) and bool(EMAIL_PATTERN.match(value))


def _is_valid_phone(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if not PHONE_PATTERN.match(value):
        return False
    digit_count = sum(character.isdigit() for character in value)
    return 10 <= digit_count <= 15


def _to_minutes(value: str) -> int:
    parsed = datetime.strptime(value, "%I:%M %p")
    return (parsed.hour * 60) + parsed.minute
