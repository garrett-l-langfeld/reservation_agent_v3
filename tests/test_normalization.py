from datetime import date

import pytest

from src.normalization import normalize_request


def _base_request() -> dict:
    return {
        "restaurant_name": "Zuni Cafe",
        "location": "San Francisco, CA",
        "date": "2026-05-05",
        "time": "7:00 PM",
        "party_size": 2,
        "user_name": "Alex Example",
        "user_email": "alex@example.com",
        "user_phone": "+1 (415) 555-1212",
    }


def test_normalize_request_keeps_canonical_values():
    normalized, errors = normalize_request(_base_request())

    assert errors == []
    assert normalized["date"] == "2026-05-05"
    assert normalized["time"] == "7:00 PM"


def test_normalize_request_normalizes_alternate_date_formats():
    request = _base_request()
    request["date"] = "05/05/2026"

    normalized, errors = normalize_request(request)

    assert errors == []
    assert normalized["date"] == "2026-05-05"


@pytest.mark.parametrize(
    ("input_date", "expected_date"),
    [
        ("May 5, 2026", "2026-05-05"),
        ("August 14, 2026", "2026-08-14"),
        ("Aug 14, 2026", "2026-08-14"),
        ("May 5", "2026-05-05"),
        ("5/5", "2026-05-05"),
        ("05/05", "2026-05-05"),
        ("5/05", "2026-05-05"),
    ],
)
def test_normalize_request_supports_requested_date_formats(
    input_date: str, expected_date: str
):
    request = _base_request()
    request["date"] = input_date

    normalized, errors = normalize_request(request, reference_date=date(2026, 4, 20))

    assert errors == []
    assert normalized["date"] == expected_date


def test_normalize_request_maps_today_to_current_date():
    request = _base_request()
    request["date"] = "Today"

    normalized, errors = normalize_request(request, reference_date=date(2026, 4, 20))

    assert errors == []
    assert normalized["date"] == "2026-04-20"


def test_normalize_request_maps_tonight_to_current_date():
    request = _base_request()
    request["date"] = "Tonight"

    normalized, errors = normalize_request(request, reference_date=date(2026, 4, 20))

    assert errors == []
    assert normalized["date"] == "2026-04-20"


def test_normalize_request_maps_weekday_to_next_occurrence():
    request = _base_request()
    request["date"] = "Monday"

    normalized, errors = normalize_request(request, reference_date=date(2026, 4, 20))

    assert errors == []
    assert normalized["date"] == "2026-04-27"


def test_normalize_request_normalizes_24_hour_time():
    request = _base_request()
    request["time"] = "19:00"

    normalized, errors = normalize_request(request)

    assert errors == []
    assert normalized["time"] == "7:00 PM"


def test_normalize_request_normalizes_time_range_values():
    request = _base_request()
    request.pop("time")
    request["time_range"] = {"earliest": "17:00", "latest": "8 pm"}

    normalized, errors = normalize_request(request)

    assert errors == []
    assert normalized["time_range"] == {"earliest": "5:00 PM", "latest": "8:00 PM"}


def test_normalize_request_reports_unrecognized_date_format():
    request = _base_request()
    request["date"] = "2026/31/12"

    normalized, errors = normalize_request(request)

    assert "unrecognized_date_format" in errors
    assert normalized["date"] == "2026/31/12"


def test_normalize_request_reports_unrecognized_time_format():
    request = _base_request()
    request["time"] = "tomorrow evening"

    normalized, errors = normalize_request(request)

    assert "unrecognized_time_format" in errors
    assert normalized["time"] == "tomorrow evening"
