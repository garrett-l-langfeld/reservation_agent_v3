from __future__ import annotations

from typing import Any

from src.platform_adapter import PlatformAdapter


class MockResyAdapter(PlatformAdapter):
    def resolve_restaurant(self, restaurant_name: str, location: str) -> dict[str, Any]:
        name = restaurant_name.strip().lower()
        normalized_location = location.strip().lower()

        if name == "springfield grill":
            return {
                "status": "ambiguous",
                "candidates": [
                    {
                        "id": "resy_springfield_grill_il",
                        "name": "Springfield Grill",
                        "location": "Springfield, IL",
                    },
                    {
                        "id": "resy_springfield_grill_ma",
                        "name": "Springfield Grill",
                        "location": "Springfield, MA",
                    },
                ],
            }

        if name == "zuni cafe" and normalized_location == "san francisco, ca":
            return {
                "status": "resolved",
                "match_type": "exact",
                "restaurant": {
                    "id": "resy_zuni_cafe_sf",
                    "name": "Zuni Cafe",
                    "location": "San Francisco, CA",
                },
            }

        if name == "zuni" and "san francisco" in normalized_location:
            return {
                "status": "resolved",
                "match_type": "near",
                "restaurant": {
                    "id": "resy_zuni_cafe_sf",
                    "name": "Zuni Cafe",
                    "location": "San Francisco, CA",
                },
            }

        return {"status": "not_found"}

    def get_availability(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        time: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = (date, party_size, time, time_range)

        if restaurant_id == "resy_no_availability":
            return []

        if restaurant_id == "resy_zuni_cafe_sf":
            return [
                {"time": "5:30 PM", "available": True},
                {"time": "7:00 PM", "available": True},
                {"time": "8:15 PM", "available": True},
            ]

        return [{"time": "6:00 PM", "available": True}]

    def attempt_booking(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        slot_time: str,
        user_details: dict[str, Any],
    ) -> dict[str, Any]:
        _ = (date, party_size, user_details)

        if restaurant_id == "resy_booking_fail":
            return {"status": "failure", "reason": "mock_booking_failure"}

        return {
            "status": "success",
            "restaurant_id": restaurant_id,
            "reserved_time": slot_time,
            "confirmation_code": "MOCK-12345",
        }

    def generate_handoff(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        requested_time: str | None = None,
    ) -> str:
        time_segment = requested_time or "any-time"
        return (
            f"https://resy.com/handoff?restaurant_id={restaurant_id}"
            f"&date={date}&party_size={party_size}&time={time_segment}"
        )
