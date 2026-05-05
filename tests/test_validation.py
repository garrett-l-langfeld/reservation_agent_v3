from src.validation import validate_request


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


def test_validate_request_accepts_valid_exact_time_request():
    errors = validate_request(_base_request())
    assert errors == []


def test_validate_request_accepts_valid_time_range_request():
    request = _base_request()
    request.pop("time")
    request["time_range"] = {"earliest": "5:00 PM", "latest": "8:00 PM"}

    errors = validate_request(request)

    assert errors == []


def test_validate_request_rejects_missing_required_fields():
    request = _base_request()
    request.pop("user_email")

    errors = validate_request(request)

    assert "missing_required_field:user_email" in errors


def test_validate_request_rejects_invalid_date():
    request = _base_request()
    request["date"] = "2026-13-05"

    errors = validate_request(request)

    assert "invalid_date" in errors


def test_validate_request_rejects_invalid_party_size():
    request = _base_request()
    request["party_size"] = 0

    errors = validate_request(request)

    assert "invalid_party_size" in errors


def test_validate_request_rejects_invalid_time_format():
    request = _base_request()
    request["time"] = "19:00"

    errors = validate_request(request)

    assert "invalid_time" in errors


def test_validate_request_rejects_missing_time_and_time_range():
    request = _base_request()
    request.pop("time")

    errors = validate_request(request)

    assert "missing_time_or_time_range" in errors


def test_validate_request_rejects_both_time_and_time_range():
    request = _base_request()
    request["time_range"] = {"earliest": "5:00 PM", "latest": "8:00 PM"}

    errors = validate_request(request)

    assert "invalid_time_input" in errors


def test_validate_request_rejects_invalid_email():
    request = _base_request()
    request["user_email"] = "not-an-email"

    errors = validate_request(request)

    assert "invalid_email" in errors


def test_validate_request_rejects_invalid_phone():
    request = _base_request()
    request["user_phone"] = "555-12"

    errors = validate_request(request)

    assert "invalid_phone" in errors
