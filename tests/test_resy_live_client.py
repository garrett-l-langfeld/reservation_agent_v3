from src.resy_live_client import ResumePayload
from src.resy_live_client import _build_search_urls
from src.resy_live_client import _build_venue_base_url
from src.resy_live_client import _checkout_state_indicates_opened
from src.resy_live_client import _click_reserve_now_modal_button
from src.resy_live_client import _collect_checkout_state
from src.resy_live_client import _decode_resume_payload
from src.resy_live_client import _extract_venue_reference
from src.resy_live_client import _extract_times
from src.resy_live_client import _html_looks_like_captcha
from src.resy_live_client import _location_to_city_slug
from src.resy_live_client import _resume_result_from_page
from src.resy_live_client import _slot_time_variants
from src.resy_live_client import _url_looks_like_captcha


def test_location_to_city_slug_matches_resy_city_path_style():
    assert _location_to_city_slug("San Francisco, CA") == "san-francisco-ca"


def test_build_search_urls_prefers_city_scoped_search_first():
    urls = _build_search_urls(
        base_url="https://resy.com",
        location="San Francisco, CA",
        query="Brenda's French Soul Food San Francisco, CA",
    )

    assert urls[0].startswith("https://resy.com/cities/san-francisco-ca/search?query=")
    assert "%27" in urls[0]
    assert urls[1].startswith("https://resy.com/search?query=")


def test_extract_times_handles_mixed_nodes_and_sorts_deduped_values():
    chunks = [
        "Reserve at 7 PM",
        "7:30 PM",
        "7 PM",
        "7:30 PM",
        "8:15 pm",
        "noise",
    ]

    assert _extract_times(chunks) == ["7:00 PM", "7:30 PM", "8:15 PM"]


def test_extract_venue_reference_preserves_city_scoped_path():
    href = "https://resy.com/cities/san-francisco-ca/venues/brendas-french-soul-food?date=2026-05-06"
    assert _extract_venue_reference(href) == "/cities/san-francisco-ca/venues/brendas-french-soul-food"


def test_build_venue_base_url_uses_reference_path_without_requoting():
    url = _build_venue_base_url(
        base_url="https://resy.com",
        restaurant_reference="/cities/san-francisco-ca/venues/brendas-french-soul-food",
    )
    assert url == "https://resy.com/cities/san-francisco-ca/venues/brendas-french-soul-food"


def test_html_captcha_detection_ignores_weak_keyword_only_content():
    html = "<html><body>captcha config loaded for telemetry</body></html>"
    assert _html_looks_like_captcha(html) is False


def test_html_captcha_detection_matches_real_challenge_markers():
    html = "<html><body><div class='g-recaptcha'></div></body></html>"
    assert _html_looks_like_captcha(html) is True


def test_url_captcha_detection_matches_challenge_patterns():
    assert _url_looks_like_captcha("https://resy.com/challenge/page") is True
    assert _url_looks_like_captcha(
        "https://resy.com/cities/san-francisco-ca/venues/brendas-french-soul-food"
    ) is False


def test_slot_time_variants_include_normalized_compact_and_suffix_forms():
    variants = _slot_time_variants("6:30 pm")
    assert "6:30 PM" in variants
    assert "6:30PM" in variants
    assert "6:30" in variants
    assert "6:30 pm" in variants


def test_checkout_state_indicates_opened_when_phrase_or_fields_present():
    assert _checkout_state_indicates_opened({"has_checkout_phrase": True}) is True
    assert _checkout_state_indicates_opened({"checkout_button_count": 1}) is True
    assert _checkout_state_indicates_opened({"fields": {"email": {"present": True}}}) is True
    assert _checkout_state_indicates_opened({"fields": {"email": {"present": False}}}) is False


def test_collect_checkout_state_falls_back_when_page_evaluate_fails():
    class BrokenPage:
        url = "https://resy.com/mock"

        def evaluate(self, _script):
            raise RuntimeError("boom")

    state = _collect_checkout_state(BrokenPage())
    assert state["snapshot_error"] is True
    assert state["url"] == "https://resy.com/mock"


def test_click_reserve_now_modal_button_clicks_visible_button():
    class FakeLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def is_enabled(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Reserve Now"

        def click(self, timeout=None):
            _ = timeout
            return None

        @property
        def first(self):
            return self

    class FakePage:
        def get_by_role(self, role, name):
            _ = (role, name)
            return FakeLocator()

        def locator(self, selector):
            _ = selector
            return FakeLocator()

    result = _click_reserve_now_modal_button(FakePage())
    assert result["clicked"] is True
    assert result["clicked_text"] == "Reserve Now"


def test_click_reserve_now_modal_button_returns_not_clicked_when_absent():
    class EmptyLocator:
        def count(self):
            return 0

        @property
        def first(self):
            return self

    class EmptyPage:
        def get_by_role(self, role, name):
            _ = (role, name)
            return EmptyLocator()

        def locator(self, selector):
            _ = selector
            return EmptyLocator()

    result = _click_reserve_now_modal_button(EmptyPage())
    assert result["clicked"] is False


def test_resume_result_returns_checkout_opened_with_updated_resume_url():
    class FakePage:
        def __init__(self):
            self.url = "https://resy.com/checkout"

        def wait_for_timeout(self, _ms):
            return None

        def content(self):
            return "<html><body>Booking details</body></html>"

        def evaluate(self, _script):
            if "iframe[src*='recaptcha']" in _script:
                return False
            if "strongPhrases" in _script:
                return True
            return {
                "url": self.url,
                "has_checkout_phrase": True,
                "has_checkout_container": True,
                "checkout_buttons": [{"text": "Continue", "visible": True, "disabled": False}],
                "checkout_button_count": 1,
                "fields": {"name": {"present": False}, "email": {"present": True}, "phone": {"present": True}},
                "validation_errors": [],
                "network": {"xhr_fetch_count": 1, "recent_requests": []},
            }

        @property
        def context(self):
            return self

        @property
        def pages(self):
            return [self]

        def is_closed(self):
            return False

    result = _resume_result_from_page(
        FakePage(),
        ResumePayload(url="https://resy.com/original", slot_time="6:30 PM"),
    )
    assert result["status"] == "checkout_opened"
    payload = _decode_resume_payload(result["resume_token"])
    assert payload is not None
    assert payload.url == "https://resy.com/checkout"
