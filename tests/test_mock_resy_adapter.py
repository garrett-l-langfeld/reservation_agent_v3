from src.mock_resy_adapter import MockResyAdapter


def test_resolve_restaurant_exact_match():
    adapter = MockResyAdapter()

    result = adapter.resolve_restaurant("Zuni Cafe", "San Francisco, CA")

    assert result["status"] == "resolved"
    assert result["match_type"] == "exact"
    assert result["restaurant"]["id"] == "resy_zuni_cafe_sf"


def test_resolve_restaurant_near_match():
    adapter = MockResyAdapter()

    result = adapter.resolve_restaurant("Zuni", "San Francisco")

    assert result["status"] == "resolved"
    assert result["match_type"] == "near"
    assert result["restaurant"]["id"] == "resy_zuni_cafe_sf"


def test_resolve_restaurant_ambiguous():
    adapter = MockResyAdapter()

    result = adapter.resolve_restaurant("Springfield Grill", "Springfield")

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2


def test_get_availability_no_availability():
    adapter = MockResyAdapter()

    result = adapter.get_availability(
        restaurant_id="resy_no_availability",
        date="2026-05-05",
        party_size=2,
    )

    assert result == []
