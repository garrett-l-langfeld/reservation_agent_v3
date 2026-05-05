from src.resy_live_client import ResumePayload
from src.resy_live_client import _build_search_urls
from src.resy_live_client import _build_venue_base_url
from src.resy_live_client import _collect_auth_state
from src.resy_live_client import _checkout_state_indicates_opened
from src.resy_live_client import _click_confirm_modal_button
from src.resy_live_client import _click_reserve_now_modal_button
from src.resy_live_client import _click_login_button
from src.resy_live_client import _collect_header_action_snapshot
from src.resy_live_client import _collect_checkout_state
from src.resy_live_client import _collect_login_modal_state
from src.resy_live_client import _decode_resume_payload
from src.resy_live_client import _extract_venue_reference
from src.resy_live_client import _extract_times
from src.resy_live_client import _html_looks_like_captcha
from src.resy_live_client import _location_to_city_slug
from src.resy_live_client import _page_looks_sms_verification
from src.resy_live_client import _extract_confirmation_code
from src.resy_live_client import _page_looks_confirmed
from src.resy_live_client import _open_resy_navigation_menu
from src.resy_live_client import _resume_result_from_page
from src.resy_live_client import _slot_time_variants
from src.resy_live_client import _wait_for_login_modal_or_authenticated_session
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


def test_collect_auth_state_returns_fallback_on_evaluate_error():
    class BrokenPage:
        def evaluate(self, _script):
            raise RuntimeError("boom")

    state = _collect_auth_state(BrokenPage())
    assert state["detection_error"] is True


def test_collect_auth_state_infers_logged_in_when_login_cta_absent():
    class Page:
        def evaluate(self, _script):
            return {
                "logged_in": True,
                "needs_login": False,
                "has_login_cta": False,
                "has_login_text": False,
                "has_account_element": False,
                "has_logout_text": False,
                "inferred_logged_in_from_missing_login_cta": True,
                "url": "https://resy.com/?date=2026-04-26&seats=2",
            }

    state = _collect_auth_state(Page())
    assert state["logged_in"] is True
    assert state["needs_login"] is False
    assert state["inferred_logged_in_from_missing_login_cta"] is True


def test_page_looks_sms_verification_detects_code_prompt():
    class SmsPage:
        def content(self):
            return "<html><body>Enter verification code we texted you</body></html>"

    assert _page_looks_sms_verification(SmsPage()) is True


def test_page_looks_confirmed_detects_reservation_booked_screen():
    class ConfirmedPage:
        def content(self):
            return "<html><body><h1>Reservation Booked.</h1><p>Please check your inbox for a confirmation email.</p></body></html>"

    assert _page_looks_confirmed(ConfirmedPage()) is True


def test_page_looks_confirmed_detects_reservation_booked_in_frame():
    class Frame:
        def content(self):
            return "<html><body><h1>Reservation Booked.</h1></body></html>"

    class ConfirmedPage:
        def content(self):
            return "<html><body>Venue page</body></html>"

        @property
        def frames(self):
            return [self, Frame()]

    assert _page_looks_confirmed(ConfirmedPage()) is True


def test_extract_confirmation_code_ignores_doctype_and_returns_booked_summary():
    html = """
    <!DOCTYPE html>
    <html>
      <body>
        <h1>Reservation Booked.</h1>
        <p>Please check your inbox for a confirmation email.</p>
      </body>
    </html>
    """

    assert _extract_confirmation_code(html) == (
        "Reservation Booked. Please check your inbox for a confirmation email."
    )


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


def test_click_confirm_modal_button_clicks_visible_button():
    class FakeLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Confirm"

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

    result = _click_confirm_modal_button(FakePage())
    assert result["clicked"] is True
    assert result["clicked_text"] == "Confirm"


def test_click_confirm_modal_button_returns_not_clicked_when_absent():
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

    result = _click_confirm_modal_button(EmptyPage())
    assert result["clicked"] is False


def test_click_login_button_uses_dom_fallback_when_locators_miss():
    class EmptyLocator:
        def count(self):
            return 0

        @property
        def first(self):
            return self

    class LoginPage:
        def get_by_role(self, role, name):
            _ = (role, name)
            return EmptyLocator()

        def locator(self, selector):
            _ = selector
            return EmptyLocator()

        def evaluate(self, _script):
            return {
                "clicked": True,
                "clicked_via": "evaluate_login_button_scan",
                "clicked_text": "Log in",
            }

    result = _click_login_button(LoginPage())
    assert result["clicked"] is True
    assert result["clicked_via"] == "evaluate_login_button_scan"


def test_click_login_button_uses_exact_nav_dom_fallback_when_present():
    class EmptyLocator:
        def count(self):
            return 0

    class LoginPage:
        def get_by_role(self, role, name):
            _ = (role, name)
            return EmptyLocator()

        def locator(self, selector):
            _ = selector
            return EmptyLocator()

        def evaluate(self, _script):
            return {
                "clicked": True,
                "clicked_via": "evaluate_exact_nav_login_button",
                "clicked_text": "Log in",
                "dom_candidates": [{"selector": "button.Button.Button--login", "matched": True}],
            }

    result = _click_login_button(LoginPage())
    assert result["clicked"] is True
    assert result["clicked_via"] == "evaluate_exact_nav_login_button"
    assert result["dom_candidates"][0]["matched"] is True


def test_open_resy_navigation_menu_clicks_visible_menu_button():
    class MenuLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Menu"

        def click(self, timeout=None):
            _ = timeout
            return None

    class BannerLocator:
        def get_by_role(self, role, name, exact=False):
            _ = exact
            if role == "button" and name == "Menu":
                return MenuLocator()
            return MenuLocator()

    class Page:
        def get_by_role(self, role, name=None, exact=False):
            if role == "banner":
                return BannerLocator()
            _ = (role, name, exact)
            return MenuLocator()

        def locator(self, selector):
            _ = selector
            return MenuLocator()

    result = _open_resy_navigation_menu(Page())
    assert result["opened"] is True
    assert result["opened_via"] == "banner_role_button_menu"


def test_open_resy_navigation_menu_skips_login_labeled_button():
    class LoginLikeMenuLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Log in"

        def click(self, timeout=None):
            _ = timeout
            raise AssertionError("should not click login-like button as menu")

    class EmptyLocator:
        def count(self):
            return 0

    class BannerLocator:
        def get_by_role(self, role, name, exact=False):
            _ = (role, name, exact)
            return EmptyLocator()

    class Page:
        def get_by_role(self, role, name=None, exact=False):
            if role == "banner":
                return BannerLocator()
            _ = (role, name, exact)
            return EmptyLocator()

        def locator(self, selector):
            if selector == "[data-test-id='menu_container-button-menu'], [data-testid='menu_container-button-menu']":
                return LoginLikeMenuLocator()
            return EmptyLocator()

        def wait_for_timeout(self, _ms):
            return None

        def evaluate(self, _script):
            return {"top_buttons": [{"text": "Log in", "visible": True}], "body_has_menu": False, "body_has_log_in": True}

    result = _open_resy_navigation_menu(Page())
    assert result["opened"] is False
    assert any(
        selector.get("skipped_reason") == "menu_selector_matched_login_button"
        for poll in result["poll_diagnostics"]
        for selector in poll["selectors"]
    )


def test_collect_header_action_snapshot_returns_top_buttons():
    class Page:
        def evaluate(self, _script):
            return {
                "top_buttons": [
                    {
                        "text": "Menu",
                        "aria_label": "",
                        "class_name": "Button Button--menu",
                        "data_test_id": "menu_button",
                        "visible": True,
                        "top": 24,
                        "left": 1000,
                    }
                ],
                "body_has_menu": True,
                "body_has_log_in": False,
            }

    result = _collect_header_action_snapshot(Page())
    assert result["top_buttons"][0]["text"] == "Menu"
    assert result["body_has_menu"] is True


def test_click_login_button_opens_menu_before_clicking_login():
    class EmptyLocator:
        def count(self):
            return 0

    class MenuLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Menu"

        def click(self, timeout=None):
            _ = timeout
            return None

    class LoginLocator:
        def count(self):
            return 1

        def nth(self, index):
            _ = index
            return self

        @property
        def first(self):
            return self

        def is_visible(self):
            return True

        def inner_text(self, timeout=None):
            _ = timeout
            return "Log in"

        def click(self, timeout=None, force=False):
            _ = (timeout, force)
            return None

    class BannerLocator:
        def get_by_role(self, role, name, exact=False):
            _ = exact
            if role == "button" and name == "Menu":
                return MenuLocator()
            return EmptyLocator()

    class Page:
        def get_by_role(self, role, name=None, exact=False):
            if role == "banner":
                return BannerLocator()
            if role == "button" and name == "Menu":
                return MenuLocator()
            _ = (role, name, exact)
            return EmptyLocator()

        def wait_for_timeout(self, _ms):
            return None

        def locator(self, selector):
            if selector == "button:has-text('Log in'), button:has-text('Sign in')":
                return LoginLocator()
            return EmptyLocator()

        def evaluate(self, _script):
            return {"clicked": False, "dom_candidates": []}

    result = _click_login_button(Page())
    assert result["clicked"] is True
    assert result["menu_open_attempt"]["opened"] is True
    assert result["clicked_text"] == "Log in"


def test_open_resy_navigation_menu_returns_poll_diagnostics_when_missing():
    class EmptyLocator:
        def count(self):
            return 0

    class Page:
        def get_by_role(self, role, name=None, exact=False):
            if role == "banner":
                return self
            _ = (role, name, exact)
            return EmptyLocator()

        def locator(self, selector):
            _ = selector
            return EmptyLocator()

        def wait_for_timeout(self, _ms):
            return None

        def evaluate(self, _script):
            return {
                "top_buttons": [{"text": "Search", "visible": True, "top": 20, "left": 300}],
                "body_has_menu": False,
                "body_has_log_in": False,
            }

    result = _open_resy_navigation_menu(Page())
    assert result["opened"] is False
    assert len(result["poll_diagnostics"]) >= 1
    assert result["poll_diagnostics"][0]["header_snapshot"]["top_buttons"][0]["text"] == "Search"


def test_click_login_button_uses_visible_match_when_first_locator_is_hidden():
    class Candidate:
        def __init__(self, index, clicked):
            self.index = index
            self.clicked = clicked

        def is_visible(self):
            return self.index == 1

        def inner_text(self, timeout=None):
            _ = timeout
            return "Log in" if self.index == 1 else "Hidden"

        def click(self, timeout=None, force=False):
            _ = (timeout, force)
            self.clicked.append(self.index)

    class MultiLocator:
        def __init__(self, clicked):
            self.clicked = clicked

        def count(self):
            return 2

        def nth(self, index):
            return Candidate(index, self.clicked)

        @property
        def first(self):
            return Candidate(0, self.clicked)

    class LoginPage:
        def __init__(self):
            self.clicked = []

        def get_by_role(self, role, name):
            _ = (role, name)
            return MultiLocator(self.clicked)

        def locator(self, selector):
            _ = selector
            return MultiLocator(self.clicked)

    page = LoginPage()
    result = _click_login_button(page)
    assert result["clicked"] is True
    assert result["clicked_via"] == "css_resy_nav_login_button_exact_path"
    assert page.clicked == [1]


def test_click_login_button_returns_diagnostics_when_no_path_clicks():
    class EmptyLocator:
        def count(self):
            return 0

    class LoginPage:
        def get_by_role(self, role, name):
            _ = (role, name)
            return EmptyLocator()

        def locator(self, selector):
            _ = selector
            return EmptyLocator()

        def evaluate(self, _script):
            return {
                "clicked": False,
                "dom_candidates": [{"tag": "button", "text": "Menu", "visible": True}],
                "body_has_log_in": True,
                "exact_nav_selector_matches": [{"selector": "button.Button.Button--login", "matched": False}],
            }

    result = _click_login_button(LoginPage())
    assert result["clicked"] is False
    assert result["body_has_log_in"] is True
    assert result["selector_diagnostics"][0]["candidate_count"] == 0
    assert result["exact_nav_selector_matches"][0]["matched"] is False


def test_wait_for_login_modal_or_authenticated_session_returns_modal_opened():
    class FakePage:
        url = "https://resy.com/?date=2026-04-26&seats=2"

        def wait_for_timeout(self, _ms):
            return None

        def content(self):
            return "<html><body>Log in</body></html>"

        def evaluate(self, script):
            if "hasLoginCta" in script:
                return {
                    "logged_in": False,
                    "needs_login": True,
                    "has_login_cta": True,
                    "has_account_element": False,
                    "has_logout_text": False,
                    "url": self.url,
                }
            if "modalSelectors" in script:
                return {
                    "modal_visible": True,
                    "modal_text": "Resy's hospitality platform securely manages your account information and reservations.",
                    "has_auth_phrase": True,
                    "has_phone_prompt": True,
                    "has_email_password_link": True,
                    "has_one_time_code_link": True,
                    "url": self.url,
                }
            return False

        @property
        def context(self):
            return self

        @property
        def pages(self):
            return [self]

        def is_closed(self):
            return False

    result = _wait_for_login_modal_or_authenticated_session(FakePage(), timeout_ms=100)
    assert result["status"] == "login_modal_opened"
    assert result["login_modal_state"]["modal_visible"] is True


def test_wait_for_login_modal_or_authenticated_session_keeps_waiting_when_requested():
    class FakePage:
        url = "https://resy.com/?date=2026-04-26&seats=2"

        def wait_for_timeout(self, _ms):
            return None

        def content(self):
            return "<html><body>Log in</body></html>"

        def evaluate(self, script):
            if "hasLoginCta" in script:
                return {
                    "logged_in": False,
                    "needs_login": True,
                    "has_login_cta": True,
                    "has_account_element": False,
                    "has_logout_text": False,
                    "url": self.url,
                }
            if "modalSelectors" in script:
                return {
                    "modal_visible": True,
                    "modal_text": "Resy's hospitality platform securely manages your account information and reservations.",
                    "has_auth_phrase": True,
                    "has_phone_prompt": True,
                    "has_email_password_link": True,
                    "has_one_time_code_link": True,
                    "url": self.url,
                }
            return False

        @property
        def context(self):
            return self

        @property
        def pages(self):
            return [self]

        def is_closed(self):
            return False

    result = _wait_for_login_modal_or_authenticated_session(
        FakePage(),
        timeout_ms=25,
        return_on_modal_open=False,
    )
    assert result["status"] == "timeout"
    assert result["modal_seen"] is True


def test_wait_for_login_modal_or_authenticated_session_infers_auth_after_modal_completion():
    class FakePage:
        url = "https://resy.com/?date=2026-04-26&seats=2"

        def __init__(self):
            self.step = 0

        def wait_for_timeout(self, _ms):
            self.step += 1
            return None

        def content(self):
            return "<html><body>Resy</body></html>"

        def evaluate(self, script):
            if "hasLoginCta" in script:
                if self.step == 0:
                    return {
                        "logged_in": False,
                        "needs_login": True,
                        "has_login_cta": True,
                        "has_account_element": False,
                        "has_logout_text": False,
                        "url": self.url,
                    }
                return {
                    "logged_in": False,
                    "needs_login": False,
                    "has_login_cta": False,
                    "has_account_element": False,
                    "has_logout_text": False,
                    "url": self.url,
                }
            if "modalSelectors" in script:
                if self.step == 0:
                    return {
                        "modal_visible": True,
                        "modal_text": "Please enter your mobile phone number",
                        "has_auth_phrase": True,
                        "has_phone_prompt": True,
                        "has_email_password_link": True,
                        "has_one_time_code_link": True,
                        "url": self.url,
                    }
                return {
                    "modal_visible": False,
                    "modal_text": "",
                    "has_auth_phrase": False,
                    "has_phone_prompt": False,
                    "has_email_password_link": False,
                    "has_one_time_code_link": False,
                    "url": self.url,
                }
            return False

        @property
        def context(self):
            return self

        @property
        def pages(self):
            return [self]

        def is_closed(self):
            return False

    result = _wait_for_login_modal_or_authenticated_session(
        FakePage(),
        timeout_ms=2_000,
        return_on_modal_open=False,
    )
    assert result["status"] == "authenticated"
    assert result["auth_state"]["inferred_from_modal_completion"] is True


def test_collect_login_modal_state_detects_resy_login_modal_copy():
    class LoginModalPage:
        def evaluate(self, script):
            if "modalSelectors" in script:
                return {
                    "modal_visible": True,
                    "modal_text": "Resy's hospitality platform securely manages your account information and reservations.",
                    "has_auth_phrase": True,
                    "has_phone_prompt": True,
                    "has_email_password_link": True,
                    "has_one_time_code_link": True,
                    "url": "https://resy.com/?date=2026-04-26&seats=2",
                }
            raise AssertionError("unexpected script")

    state = _collect_login_modal_state(LoginModalPage())
    assert state["modal_visible"] is True
    assert state["has_auth_phrase"] is True


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


def test_resume_result_returns_login_refresh_required_when_logged_out():
    class FakePage:
        url = "https://resy.com/login"

        def wait_for_timeout(self, _ms):
            return None

        def content(self):
            return "<html><body>Log In</body></html>"

        def evaluate(self, _script):
            if "const normalize = (value)" in _script:
                return {
                    "logged_in": False,
                    "needs_login": True,
                    "has_login_cta": True,
                    "has_account_element": False,
                    "has_logout_text": False,
                    "url": self.url,
                }
            return False

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
    assert result["status"] == "login_refresh_required"
