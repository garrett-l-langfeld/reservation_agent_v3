from src.resy_adapter import ResyAdapter


class FakeResyClient:
    def __init__(self):
        self.restaurants = [
            {"id": "r1", "name": "Zuni Cafe", "location": "San Francisco, CA"},
            {"id": "r2", "name": "Zuni Cafe", "location": "New York, NY"},
        ]
        self.availability = [
            {"time": "19:00", "available": True},
            {"display_time": "8 pm", "available": True},
            {"time": "invalid", "available": True},
        ]
        self.book_response = {"status": "success", "confirmation_code": "RSY-1"}
        self.resume_response = {"status": "success", "confirmation_code": "RSY-2"}

    def search_restaurants(self, restaurant_name: str, location: str):
        _ = restaurant_name
        normalized_location = location.strip().lower()
        return [
            item for item in self.restaurants if normalized_location in item["location"].lower()
        ]

    def fetch_availability(self, **kwargs):
        _ = kwargs
        return self.availability

    def book_slot(self, **kwargs):
        _ = kwargs
        return self.book_response

    def resume_booking(self, resume_token: str):
        assert resume_token
        return self.resume_response

    def build_handoff_url(self, **kwargs):
        return f"https://resy.com/mock-handoff/{kwargs['restaurant_id']}"


def test_resy_adapter_ensure_authenticated_defaults_to_authenticated_when_client_has_no_hook():
    adapter = ResyAdapter(FakeResyClient())

    result = adapter.ensure_authenticated()

    assert result == {"status": "authenticated"}


def test_resy_adapter_ensure_authenticated_maps_login_required_to_user_action():
    client = FakeResyClient()
    client.ensure_authenticated_session = lambda: {  # type: ignore[attr-defined]
        "status": "login_required",
        "prompt": "Log in first",
        "debug": {"auth_state": {"needs_login": True}},
    }
    adapter = ResyAdapter(client)

    result = adapter.ensure_authenticated()

    assert result == {
        "status": "user_action_required",
        "reason": "login_required",
        "prompt": "Log in first",
        "resume_token": None,
        "debug": {"auth_state": {"needs_login": True}},
    }


def test_resy_adapter_resolves_exact_match():
    adapter = ResyAdapter(FakeResyClient())

    result = adapter.resolve_restaurant("Zuni Cafe", "San Francisco, CA")

    assert result["status"] == "resolved"
    assert result["match_type"] == "exact"
    assert result["restaurant"]["id"] == "r1"


def test_resy_adapter_extracts_and_normalizes_availability():
    adapter = ResyAdapter(FakeResyClient())

    slots = adapter.get_availability(
        restaurant_id="r1",
        date="2026-05-05",
        party_size=2,
    )

    assert slots == [
        {"time": "7:00 PM", "available": True},
        {"time": "8:00 PM", "available": True},
    ]


def test_resy_adapter_maps_captcha_booking_result():
    client = FakeResyClient()
    client.book_response = {
        "status": "captcha_required",
        "prompt": "Solve challenge",
        "resume_token": "abc123",
    }
    adapter = ResyAdapter(client)

    result = adapter.attempt_booking(
        restaurant_id="r1",
        date="2026-05-05",
        party_size=2,
        slot_time="7:00 PM",
        user_details={"name": "A", "email": "a@example.com", "phone": "1234567890"},
    )

    assert result["status"] == "captcha_required"
    assert result["resume_token"] == "abc123"


def test_resy_adapter_resume_booking_success():
    adapter = ResyAdapter(FakeResyClient())

    result = adapter.resume_booking("resume-token")

    assert result["status"] == "success"
    assert result["confirmation_code"] == "RSY-2"


def test_resy_adapter_resume_booking_checkout_opened_maps_to_user_action():
    client = FakeResyClient()
    client.resume_response = {
        "status": "checkout_opened",
        "prompt": "Checkout still open",
        "resume_token": "resume-next",
        "debug": {"checkout_state": {"checkout_button_count": 1}},
    }
    adapter = ResyAdapter(client)

    result = adapter.resume_booking("resume-token")

    assert result == {
        "status": "user_action_required",
        "reason": "checkout_opened",
        "prompt": "Checkout still open",
        "resume_token": "resume-next",
        "debug": {"checkout_state": {"checkout_button_count": 1}},
    }


def test_resy_adapter_resume_booking_preserves_failure_debug_payload():
    client = FakeResyClient()
    client.resume_response = {
        "status": "failure",
        "reason": "resume_failed",
        "debug": {"checkout_state": {"snapshot_error": True}},
    }
    adapter = ResyAdapter(client)

    result = adapter.resume_booking("resume-token")

    assert result == {
        "status": "failure",
        "reason": "resume_failed",
        "debug": {"checkout_state": {"snapshot_error": True}},
    }


def test_resy_adapter_preserves_failure_debug_payload():
    client = FakeResyClient()
    client.book_response = {
        "status": "failure",
        "reason": "slot_click_failed",
        "debug": {"matching_count": 1, "top_candidates": [{"text": "6:30 PM"}]},
    }
    adapter = ResyAdapter(client)

    result = adapter.attempt_booking(
        restaurant_id="r1",
        date="2026-05-05",
        party_size=2,
        slot_time="6:30 PM",
        user_details={"name": "A", "email": "a@example.com", "phone": "1234567890"},
    )

    assert result["status"] == "failure"
    assert result["reason"] == "slot_click_failed"
    assert result["debug"] == {"matching_count": 1, "top_candidates": [{"text": "6:30 PM"}]}


def test_resy_adapter_maps_checkout_opened_to_user_action_required():
    client = FakeResyClient()
    client.book_response = {
        "status": "checkout_opened",
        "prompt": "Complete checkout and resume",
        "resume_token": "resume-xyz",
        "debug": {"clicked_via": "role_button_contains"},
    }
    adapter = ResyAdapter(client)

    result = adapter.attempt_booking(
        restaurant_id="r1",
        date="2026-05-05",
        party_size=2,
        slot_time="6:30 PM",
        user_details={"name": "A", "email": "a@example.com", "phone": "1234567890"},
    )

    assert result == {
        "status": "user_action_required",
        "reason": "checkout_opened",
        "prompt": "Complete checkout and resume",
        "resume_token": "resume-xyz",
        "debug": {"clicked_via": "role_button_contains"},
    }


def test_resy_adapter_maps_login_refresh_to_user_action_required():
    client = FakeResyClient()
    client.book_response = {
        "status": "login_refresh_required",
        "prompt": "Log in again and resume",
        "resume_token": "resume-login-1",
        "debug": {"auth_state": {"needs_login": True}},
    }
    adapter = ResyAdapter(client)

    result = adapter.attempt_booking(
        restaurant_id="r1",
        date="2026-05-05",
        party_size=2,
        slot_time="6:30 PM",
        user_details={"name": "A", "email": "a@example.com", "phone": "1234567890"},
    )

    assert result == {
        "status": "user_action_required",
        "reason": "login_refresh_required",
        "prompt": "Log in again and resume",
        "resume_token": "resume-login-1",
        "debug": {"auth_state": {"needs_login": True}},
    }
