from src.resy_live_client import _build_search_urls
from src.resy_live_client import _build_venue_base_url
from src.resy_live_client import _extract_venue_reference
from src.resy_live_client import _extract_times
from src.resy_live_client import _html_looks_like_captcha
from src.resy_live_client import _location_to_city_slug
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
