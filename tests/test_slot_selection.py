from src.slot_selection import select_best_slot


def _availability(times: list[str]) -> list[dict]:
    return [{"time": time, "available": True} for time in times]


def test_select_best_slot_prefers_exact_match():
    slots = _availability(["5:30 PM", "7:00 PM", "8:15 PM"])

    selected = select_best_slot(slots, time="7:00 PM")

    assert selected is not None
    assert selected["time"] == "7:00 PM"


def test_select_best_slot_chooses_closest_in_range():
    slots = _availability(["5:00 PM", "6:30 PM", "7:45 PM", "9:00 PM"])

    selected = select_best_slot(
        slots,
        time_range={"earliest": "6:00 PM", "latest": "8:00 PM"},
    )

    assert selected is not None
    assert selected["time"] == "6:30 PM"


def test_select_best_slot_falls_back_to_closest_overall_when_range_has_no_match():
    slots = _availability(["4:00 PM", "5:00 PM", "9:00 PM"])

    selected = select_best_slot(
        slots,
        time_range={"earliest": "6:00 PM", "latest": "8:00 PM"},
    )

    assert selected is not None
    assert selected["time"] == "5:00 PM"


def test_select_best_slot_returns_none_when_no_available_slots():
    slots = [{"time": "7:00 PM", "available": False}]

    selected = select_best_slot(slots, time="7:00 PM")

    assert selected is None


def test_select_best_slot_falls_back_to_closest_overall_for_exact_request():
    slots = _availability(["6:45 PM", "7:15 PM"])

    selected = select_best_slot(slots, time="7:00 PM")

    assert selected is not None
    assert selected["time"] == "6:45 PM"
