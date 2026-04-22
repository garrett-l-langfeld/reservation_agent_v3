from __future__ import annotations

import logging
from datetime import date
from typing import Any

from src.normalization import normalize_request
from src.platform_adapter import PlatformAdapter
from src.slot_selection import select_best_slot
from src.validation import validate_request

LOGGER = logging.getLogger(__name__)


def process_reservation_request(
    request: dict[str, Any],
    adapter: PlatformAdapter,
    reference_date: date | None = None,
) -> dict[str, Any]:
    LOGGER.info("request_received", extra={"restaurant": request.get("restaurant_name")})

    normalized_request, normalization_errors = normalize_request(
        request,
        reference_date=reference_date,
    )

    validation_errors = validate_request(normalized_request)
    all_errors = normalization_errors + validation_errors
    LOGGER.info("validation_complete", extra={"error_count": len(all_errors)})
    if all_errors:
        return {
            "status": "failure",
            "reason": "invalid_request",
            "errors": all_errors,
            "alternative_times": [],
            "handoff_link": None,
        }

    try:
        resolution = adapter.resolve_restaurant(
            normalized_request["restaurant_name"],
            normalized_request["location"],
        )
        if resolution["status"] == "not_found":
            return {
                "status": "failure",
                "reason": "restaurant_not_found",
                "alternative_times": [],
                "handoff_link": None,
            }

        if resolution["status"] == "ambiguous":
            return {
                "status": "ambiguous_restaurant",
                "reason": "Multiple restaurant matches found",
                "candidates": [
                    {
                        "name": candidate["name"],
                        "location": candidate["location"],
                        "resy_id": candidate["id"],
                    }
                    for candidate in resolution.get("candidates", [])
                ],
            }

        restaurant = resolution["restaurant"]
        availability = adapter.get_availability(
            restaurant_id=restaurant["id"],
            date=normalized_request["date"],
            party_size=normalized_request["party_size"],
            time=normalized_request.get("time"),
            time_range=normalized_request.get("time_range"),
        )
        LOGGER.info("availability_received", extra={"slots": len(availability)})

        alternative_times = _extract_alternative_times(availability)
        if not availability:
            LOGGER.info("fallback_no_availability")
            return {
                "status": "no_availability",
                "reason": "No slots found for requested date/time",
                "alternative_times": alternative_times,
                "handoff_link": adapter.generate_handoff(
                    restaurant_id=restaurant["id"],
                    date=normalized_request["date"],
                    party_size=normalized_request["party_size"],
                    requested_time=normalized_request.get("time"),
                ),
            }

        selected_slot = select_best_slot(
            availability,
            time=normalized_request.get("time"),
            time_range=normalized_request.get("time_range"),
        )
        LOGGER.info(
            "slot_selected",
            extra={"selected_time": selected_slot["time"] if selected_slot else None},
        )
        if selected_slot is None:
            LOGGER.info("fallback_no_match")
            return {
                "status": "no_availability",
                "reason": "No slots found for requested date/time",
                "alternative_times": alternative_times,
                "handoff_link": adapter.generate_handoff(
                    restaurant_id=restaurant["id"],
                    date=normalized_request["date"],
                    party_size=normalized_request["party_size"],
                    requested_time=normalized_request.get("time"),
                ),
            }

        LOGGER.info("booking_attempt", extra={"slot_time": selected_slot["time"]})
        booking_result = adapter.attempt_booking(
            restaurant_id=restaurant["id"],
            date=normalized_request["date"],
            party_size=normalized_request["party_size"],
            slot_time=selected_slot["time"],
            user_details={
                "name": normalized_request["user_name"],
                "email": normalized_request["user_email"],
                "phone": normalized_request["user_phone"],
            },
        )

        if booking_result.get("status") == "success":
            return {
                "status": "success",
                "restaurant": restaurant["name"],
                "time": selected_slot["time"],
                "party_size": normalized_request["party_size"],
                "confirmation_status": "confirmed",
                "confirmation_details": booking_result.get("confirmation_code"),
            }

        if booking_result.get("status") == "captcha_required":
            LOGGER.info("fallback_captcha_required")
            return {
                "status": "requires_user_action",
                "reason": "captcha_required",
                "prompt": booking_result.get(
                    "prompt", "Complete CAPTCHA in browser and resume"
                ),
                "resume_token": booking_result.get("resume_token"),
                "restaurant": restaurant["name"],
                "time": selected_slot["time"],
                "alternative_times": alternative_times,
            }

        if booking_result.get("status") == "user_action_required":
            LOGGER.info("fallback_checkout_user_action_required")
            return {
                "status": "requires_user_action",
                "reason": "checkout_opened",
                "prompt": booking_result.get(
                    "prompt", "Complete checkout details in browser and resume"
                ),
                "resume_token": booking_result.get("resume_token"),
                "restaurant": restaurant["name"],
                "time": selected_slot["time"],
                "alternative_times": alternative_times,
                "booking_debug": booking_result.get("debug"),
            }

        LOGGER.info("fallback_booking_failed")
        booking_debug = booking_result.get("debug")
        return {
            "status": "failure",
            "reason": booking_result.get("reason", "booking_failed"),
            "alternative_times": alternative_times,
            "handoff_link": adapter.generate_handoff(
                restaurant_id=restaurant["id"],
                date=normalized_request["date"],
                party_size=normalized_request["party_size"],
                requested_time=normalized_request.get("time") or selected_slot["time"],
            ),
            "booking_debug": booking_debug,
        }
    except Exception:
        LOGGER.exception("platform_failure")
        return {
            "status": "failure",
            "reason": "platform_failure",
            "alternative_times": [],
            "handoff_link": None,
        }


def resume_captcha_booking(
    adapter: Any,
    resume_token: str,
) -> dict[str, Any]:
    LOGGER.info("captcha_resume_attempt")
    if not hasattr(adapter, "resume_booking"):
        return {
            "status": "failure",
            "reason": "resume_not_supported",
            "alternative_times": [],
            "handoff_link": None,
        }

    try:
        result = adapter.resume_booking(resume_token)
    except Exception:
        LOGGER.exception("captcha_resume_failure")
        return {
            "status": "failure",
            "reason": "platform_failure",
            "alternative_times": [],
            "handoff_link": None,
        }

    if result.get("status") == "success":
        return {
            "status": "success",
            "confirmation_status": "confirmed",
            "confirmation_details": result.get("confirmation_code"),
        }

    return {
        "status": "failure",
        "reason": result.get("reason", "resume_failed"),
        "alternative_times": [],
        "handoff_link": None,
    }


def _extract_alternative_times(availability: list[dict[str, Any]]) -> list[str]:
    alternatives: list[str] = []
    for slot in availability:
        if slot.get("available") and isinstance(slot.get("time"), str):
            alternatives.append(slot["time"])
    return alternatives
