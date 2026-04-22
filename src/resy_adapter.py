from __future__ import annotations

from datetime import datetime
from typing import Any

from src.platform_adapter import PlatformAdapter


class ResyAdapter(PlatformAdapter):
    def __init__(self, client: Any):
        self.client = client

    def resolve_restaurant(self, restaurant_name: str, location: str) -> dict[str, Any]:
        results = self.client.search_restaurants(restaurant_name, location)
        if not results:
            return {"status": "not_found"}

        normalized_name = restaurant_name.strip().lower()
        normalized_location = location.strip().lower()

        exact_matches = [
            item
            for item in results
            if item.get("name", "").strip().lower() == normalized_name
            and item.get("location", "").strip().lower() == normalized_location
        ]
        if exact_matches:
            match = exact_matches[0]
            return {
                "status": "resolved",
                "match_type": "exact",
                "restaurant": {
                    "id": str(match["id"]),
                    "name": match["name"],
                    "location": match["location"],
                },
            }

        if len(results) == 1:
            match = results[0]
            return {
                "status": "resolved",
                "match_type": "near",
                "restaurant": {
                    "id": str(match["id"]),
                    "name": match["name"],
                    "location": match["location"],
                },
            }

        return {
            "status": "ambiguous",
            "candidates": [
                {
                    "id": str(item["id"]),
                    "name": item["name"],
                    "location": item["location"],
                }
                for item in results
            ],
        }

    def get_availability(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        time: str | None = None,
        time_range: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        payload = self.client.fetch_availability(
            restaurant_id=restaurant_id,
            date=date,
            party_size=party_size,
            time=time,
            time_range=time_range,
        )

        extracted: list[dict[str, Any]] = []
        for item in payload:
            raw_time = item.get("time") or item.get("display_time")
            normalized = _normalize_time(raw_time)
            if normalized is None:
                continue
            extracted.append(
                {
                    "time": normalized,
                    "available": bool(item.get("available", True)),
                }
            )

        return extracted

    def attempt_booking(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        slot_time: str,
        user_details: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.client.book_slot(
            restaurant_id=restaurant_id,
            date=date,
            party_size=party_size,
            slot_time=slot_time,
            user_details=user_details,
        )

        status = result.get("status")
        if status in {"success", "confirmed"}:
            return {
                "status": "success",
                "confirmation_code": result.get("confirmation_code"),
            }

        if status in {"captcha", "captcha_required"}:
            return {
                "status": "captcha_required",
                "prompt": result.get(
                    "prompt", "Please complete CAPTCHA and resume booking"
                ),
                "resume_token": result.get("resume_token"),
            }

        if status in {"checkout_opened", "user_action_required"}:
            return {
                "status": "user_action_required",
                "prompt": result.get(
                    "prompt",
                    "Booking details opened. Complete remaining checkout steps and resume.",
                ),
                "resume_token": result.get("resume_token"),
                "debug": result.get("debug"),
            }

        return {
            "status": "failure",
            "reason": result.get("reason", "booking_failed"),
            "debug": result.get("debug"),
        }

    def generate_handoff(
        self,
        restaurant_id: str,
        date: str,
        party_size: int,
        requested_time: str | None = None,
    ) -> str:
        if hasattr(self.client, "build_handoff_url"):
            return self.client.build_handoff_url(
                restaurant_id=restaurant_id,
                date=date,
                party_size=party_size,
                requested_time=requested_time,
            )

        time_segment = requested_time or "any-time"
        return (
            f"https://resy.com/handoff?restaurant_id={restaurant_id}"
            f"&date={date}&party_size={party_size}&time={time_segment}"
        )

    def resume_booking(self, resume_token: str) -> dict[str, Any]:
        if not hasattr(self.client, "resume_booking"):
            return {"status": "failure", "reason": "resume_not_supported"}

        result = self.client.resume_booking(resume_token)
        status = result.get("status")
        if status in {"success", "confirmed"}:
            return {
                "status": "success",
                "confirmation_code": result.get("confirmation_code"),
            }
        if status in {"checkout_opened", "user_action_required"}:
            return {
                "status": "user_action_required",
                "reason": "checkout_opened",
                "prompt": result.get(
                    "prompt",
                    "Checkout is open. Complete remaining steps in browser and resume.",
                ),
                "resume_token": result.get("resume_token"),
                "debug": result.get("debug"),
            }
        if status in {"captcha", "captcha_required"}:
            return {
                "status": "captcha_required",
                "reason": "captcha_required",
                "prompt": result.get("prompt", "Complete CAPTCHA and resume booking."),
                "resume_token": result.get("resume_token"),
                "debug": result.get("debug"),
            }

        return {
            "status": "failure",
            "reason": result.get("reason", "resume_failed"),
            "debug": result.get("debug"),
        }


def _normalize_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    candidate = " ".join(value.strip().upper().split())
    for time_format in ("%I:%M %p", "%I:%M%p", "%I %p", "%H:%M"):
        try:
            parsed = datetime.strptime(candidate, time_format)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue

    return None
