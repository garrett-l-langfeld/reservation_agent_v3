# Reservation Agent — Response Schema

_Task 2.2 output_

## Success Response

```json
{
  "status": "success",
  "restaurant": "string",
  "time": "h:mm AM/PM",
  "party_size": "integer",
  "confirmation_status": "confirmed|pending",
  "confirmation_details": "string|null"
}
```

## Failure Response

```json
{
  "status": "failure",
  "reason": "string",
  "alternative_times": ["h:mm AM/PM"],
  "handoff_link": "string|null"
}
```

## Requires User Action Response

```json
{
  "status": "requires_user_action",
  "reason": "login_required|login_refresh_required|captcha_required|checkout_opened|sms_verification_required",
  "prompt": "string",
  "resume_token": "string|null",
  "booking_debug": "object|null"
}
```

### Notes
- `sms_verification_required` is a rare fallback and may still occur even when a logged-in session exists.
- `resume_token` is present when the flow can continue from the current browser/session context.

## No Availability Response

```json
{
  "status": "no_availability",
  "reason": "No slots found for requested date/time",
  "alternative_times": ["h:mm AM/PM"],
  "handoff_link": "string|null"
}
```

## Ambiguous Restaurant Response

```json
{
  "status": "ambiguous_restaurant",
  "reason": "Multiple restaurant matches found",
  "candidates": [
    {
      "name": "string",
      "location": "string",
      "resy_id": "string"
    }
  ]
}
```
