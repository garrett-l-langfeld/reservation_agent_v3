from datetime import date

import pytest

from src.mock_resy_adapter import MockResyAdapter
from src.orchestrator import process_reservation_request, resume_captcha_booking


def _valid_request() -> dict:
    return {
        "restaurant_name": "Zuni Cafe",
        "location": "San Francisco, CA",
        "date": "May 5, 2026",
        "time": "7 pm",
        "party_size": 2,
        "user_name": "Alex Example",
        "user_email": "alex@example.com",
        "user_phone": "+1 (415) 555-1212",
    }


def test_process_reservation_success_with_mock_adapter():
    result = process_reservation_request(
        _valid_request(),
        adapter=MockResyAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "success"
    assert result["time"] == "7:00 PM"
    assert result["confirmation_status"] == "confirmed"


def test_process_reservation_fallback_when_booking_fails():
    class BookingFailAdapter(MockResyAdapter):
        def resolve_restaurant(self, restaurant_name: str, location: str) -> dict:
            _ = (restaurant_name, location)
            return {
                "status": "resolved",
                "match_type": "exact",
                "restaurant": {
                    "id": "resy_booking_fail",
                    "name": "Fail Bistro",
                    "location": "San Francisco, CA",
                },
            }

    result = process_reservation_request(
        _valid_request(),
        adapter=BookingFailAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "failure"
    assert result["reason"] == "mock_booking_failure"
    assert result["handoff_link"] is not None
    assert len(result["alternative_times"]) >= 1


def test_process_reservation_includes_booking_debug_on_failure():
    class BookingFailWithDebugAdapter(MockResyAdapter):
        def attempt_booking(self, *args, **kwargs):  # type: ignore[override]
            _ = (args, kwargs)
            return {
                "status": "failure",
                "reason": "slot_click_failed",
                "debug": {"matching_count": 2, "top_candidates": [{"text": "6:30 PM"}]},
            }

    result = process_reservation_request(
        _valid_request(),
        adapter=BookingFailWithDebugAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "failure"
    assert result["reason"] == "slot_click_failed"
    assert result["booking_debug"] == {
        "matching_count": 2,
        "top_candidates": [{"text": "6:30 PM"}],
    }


def test_process_reservation_no_availability_response():
    class NoAvailabilityAdapter(MockResyAdapter):
        def resolve_restaurant(self, restaurant_name: str, location: str) -> dict:
            _ = (restaurant_name, location)
            return {
                "status": "resolved",
                "match_type": "exact",
                "restaurant": {
                    "id": "resy_no_availability",
                    "name": "Busy Spot",
                    "location": "San Francisco, CA",
                },
            }

    result = process_reservation_request(
        _valid_request(),
        adapter=NoAvailabilityAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "no_availability"
    assert result["handoff_link"] is not None


def test_process_reservation_invalid_input_response():
    request = _valid_request()
    request.pop("user_email")

    result = process_reservation_request(
        request,
        adapter=MockResyAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "failure"
    assert result["reason"] == "invalid_request"
    assert "missing_required_field:user_email" in result["errors"]


def test_process_reservation_platform_failure_response():
    class BrokenAdapter(MockResyAdapter):
        def get_availability(self, *args, **kwargs):  # type: ignore[override]
            _ = (args, kwargs)
            raise RuntimeError("mock platform down")

    result = process_reservation_request(
        _valid_request(),
        adapter=BrokenAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "failure"
    assert result["reason"] == "platform_failure"


def test_process_reservation_handles_captcha_pause_prompt_resume():
    class CaptchaAdapter(MockResyAdapter):
        def attempt_booking(self, *args, **kwargs):  # type: ignore[override]
            _ = (args, kwargs)
            return {
                "status": "captcha_required",
                "prompt": "Complete CAPTCHA in browser",
                "resume_token": "resume-123",
            }

        def resume_booking(self, resume_token: str) -> dict:
            assert resume_token == "resume-123"
            return {"status": "success", "confirmation_code": "RESUME-OK"}

    adapter = CaptchaAdapter()
    initial = process_reservation_request(
        _valid_request(),
        adapter=adapter,
        reference_date=date(2026, 4, 20),
    )

    assert initial["status"] == "requires_user_action"
    assert initial["reason"] == "captcha_required"
    assert initial["resume_token"] == "resume-123"

    resumed = resume_captcha_booking(adapter, initial["resume_token"])

    assert resumed["status"] == "success"
    assert resumed["confirmation_details"] == "RESUME-OK"


def test_process_reservation_handles_checkout_opened_as_user_action_required():
    class CheckoutOpenedAdapter(MockResyAdapter):
        def attempt_booking(self, *args, **kwargs):  # type: ignore[override]
            _ = (args, kwargs)
            return {
                "status": "user_action_required",
                "prompt": "Complete checkout details",
                "resume_token": "resume-checkout-123",
                "debug": {"clicked_via": "role_button_contains"},
            }

    result = process_reservation_request(
        _valid_request(),
        adapter=CheckoutOpenedAdapter(),
        reference_date=date(2026, 4, 20),
    )

    assert result["status"] == "requires_user_action"
    assert result["reason"] == "checkout_opened"
    assert result["resume_token"] == "resume-checkout-123"
    assert result["booking_debug"] == {"clicked_via": "role_button_contains"}


def test_process_reservation_emits_required_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")

    process_reservation_request(
        _valid_request(),
        adapter=MockResyAdapter(),
        reference_date=date(2026, 4, 20),
    )

    messages = [record.message for record in caplog.records]
    assert "request_received" in messages
    assert "validation_complete" in messages
    assert "availability_received" in messages
    assert "slot_selected" in messages
    assert "booking_attempt" in messages
