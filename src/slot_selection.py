from __future__ import annotations

from datetime import datetime
from typing import Any


def select_best_slot(
    availability: list[dict[str, Any]],
    time: str | None = None,
    time_range: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    candidates = _prepare_candidates(availability)
    if not candidates:
        return None

    if time is not None:
        exact = _find_exact(candidates, time)
        if exact is not None:
            return exact

    if time_range is not None:
        in_range = _find_closest_in_range(candidates, time_range)
        if in_range is not None:
            return in_range

    target_minutes = _target_minutes(time=time, time_range=time_range)
    if target_minutes is None:
        return candidates[0]["slot"]

    closest = min(
        candidates,
        key=lambda candidate: (
            abs(candidate["minutes"] - target_minutes),
            candidate["minutes"],
        ),
    )
    return closest["slot"]


def _prepare_candidates(availability: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for slot in availability:
        if not slot.get("available", False):
            continue
        parsed_minutes = _to_minutes(slot.get("time"))
        if parsed_minutes is None:
            continue
        candidates.append({"slot": slot, "minutes": parsed_minutes})

    candidates.sort(key=lambda candidate: candidate["minutes"])
    return candidates


def _find_exact(candidates: list[dict[str, Any]], time: str) -> dict[str, Any] | None:
    for candidate in candidates:
        if candidate["slot"].get("time") == time:
            return candidate["slot"]
    return None


def _find_closest_in_range(
    candidates: list[dict[str, Any]],
    time_range: dict[str, str],
) -> dict[str, Any] | None:
    earliest = _to_minutes(time_range.get("earliest"))
    latest = _to_minutes(time_range.get("latest"))
    if earliest is None or latest is None:
        return None

    midpoint = (earliest + latest) / 2
    matching = [
        candidate
        for candidate in candidates
        if earliest <= candidate["minutes"] <= latest
    ]
    if not matching:
        return None

    selected = min(
        matching,
        key=lambda candidate: (
            abs(candidate["minutes"] - midpoint),
            candidate["minutes"],
        ),
    )
    return selected["slot"]


def _target_minutes(time: str | None, time_range: dict[str, str] | None) -> int | None:
    if time is not None:
        return _to_minutes(time)

    if time_range is not None:
        earliest = _to_minutes(time_range.get("earliest"))
        latest = _to_minutes(time_range.get("latest"))
        if earliest is not None and latest is not None:
            return int((earliest + latest) / 2)

    return None


def _to_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.strptime(value, "%I:%M %p")
    except ValueError:
        return None

    return (parsed.hour * 60) + parsed.minute
