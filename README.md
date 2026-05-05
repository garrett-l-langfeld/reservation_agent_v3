# Reservation Agent (Resy)

A Python CLI that automates restaurant reservation attempts through Resy using a real browser flow, with support for login preflight, persistent sessions, and structured JSON results.

## What This Project Does

- Normalizes and validates reservation requests
- Resolves restaurants and checks availability
- Selects the best slot for the requested time
- Runs booking flow in a real browser (`Playwright`) when using `--adapter real`
- Supports user-action handoffs for login/CAPTCHA/checkout steps
- Returns machine-readable JSON status for every run

## Current Scope

- Primary platform: **Resy**
- Primary execution mode for live bookings: **headed browser**
- Session reuse: persistent browser profile directory (no credential storage in code)

## Requirements

- Python 3.11+
- `pip`
- Playwright browser dependencies

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python -m playwright install
```

## Run Tests

```bash
.venv/bin/python -m pytest
```

## CLI Usage

```bash
.venv/bin/python -m src.main [OPTIONS]
```

### Required request input (choose one)

- `--request-json '{...}'`
- `--request-file /path/to/request.json`

### Important options

- `--adapter {mock,real}` (default: `mock`)
- `--headed` (recommended for real flow)
- `--timeout-ms 20000` (per Playwright operation)
- `--session-profile-dir .resy_profile` (persistent session state)
- `--reference-date YYYY-MM-DD` (deterministic parsing/testing)

## Example: Real Headed Run

```bash
.venv/bin/python -m src.main --adapter real --headed --session-profile-dir .resy_profile --request-json '{"restaurant_name":"Poesia Osteria Italiana","location":"San Francisco, CA","date":"2026-05-13","time":"6:30 PM","party_size":2,"user_name":"Alex Example","user_email":"alex@example.com","user_phone":"555-555-0123"}'
```

## Request Shape

```json
{
  "restaurant_name": "The Stinking Rose",
  "location": "San Francisco, CA",
  "date": "2026-05-12",
  "time": "6:30 PM",
  "party_size": 2,
  "user_name": "Your Name",
  "user_email": "you@example.com",
  "user_phone": "555-555-5555"
}
```

## Response Shape (High Level)

### Success

```json
{
  "status": "success",
  "restaurant": "...",
  "time": "6:30 PM",
  "party_size": 2,
  "confirmation_status": "confirmed",
  "confirmation_details": "..."
}
```

### Requires User Action

```json
{
  "status": "requires_user_action",
  "reason": "login_required",
  "prompt": "...",
  "resume_token": "...",
  "booking_debug": {}
}
```

Common `reason` values include:

- `login_required`
- `login_refresh_required`
- `captcha_required`
- `checkout_opened`
- `sms_verification_required` (fallback path)

### Failure

```json
{
  "status": "failure",
  "reason": "restaurant_not_found"
}
```

## Real Browser Flow Notes

- The real adapter checks auth preflight before restaurant search.
- If a login CTA is present, it enters login flow.
- If no login CTA is present, it proceeds assuming active login session.
- After slot selection, the flow attempts modal actions (for example `Reserve Now` and `Confirm`) including iframe contexts.
- On a `Reservation Booked` confirmation screen, the run should stop and return success.

## Session Persistence

Use `--session-profile-dir` to keep browser session state across runs.

- First run may require manual login
- Later runs can reuse session if still valid
- If session expires, you may receive `login_refresh_required`

## Project Structure

```text
.
├── AGENTS.md
├── PROJECT_STATE.md
├── TASKS.md
├── docs/
├── src/
└── tests/
```

## Safety and Responsibility

- Respect website terms and applicable laws.
- Do not commit personal data or secrets.
- Treat live booking automation as best effort; always review final confirmation.

## License

Add your preferred license (for example MIT) before publishing publicly.
