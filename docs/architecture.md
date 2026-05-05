# Reservation Agent — Architecture & PRD

_Last updated: April 2026_

---

## 1. Overview

A Resy-first reservation agent that attempts to autonomously book a restaurant reservation based on structured user input. The primary strategy is login-first with persistent local session reuse so repeat bookings can proceed without repeated login. If booking fails or authentication challenges are forced, the system falls back to user-assisted continuation.

---

## 2. Core Goal

Given:
- restaurant name
- location
- date
- time or time range
- party size
- user name
- user email
- user phone

The system should:
1. Open Resy and verify authenticated session state
2. If logged out, click `Log In` and wait for user-assisted login
3. Find the restaurant on Resy
4. Check availability
5. Select the best slot
6. Attempt to book the reservation
7. Return confirmation OR fallback options

---

## 3. Scope

### In Scope
- Single platform: Resy
- Structured input only
- Availability lookup
- Slot selection
- Attempted booking (best-effort)
- Limited user account session reuse (no credential storage)
- CAPTCHA/verification/user-action prompts as fallback
- Fallback to handoff

### Out of Scope
- Multi-platform support
- Phone reservations
- Multi-account management
- Credential vaulting/storage
- Payment handling
- Background monitoring
- Preference learning

---

## 4. Core Components

### 4.1 Request Intake
Parses structured user input into a normalized format.
Includes required booking contact fields: name, email, and phone.

### 4.2 Validation
Ensures:
- valid date/time
- valid party size
- required fields present
- valid email format
- valid phone format

### 4.3 Platform Adapter (Resy)
Responsible for:
- restaurant resolution
- availability lookup
- booking attempt
- handoff generation

### 4.4 Slot Selection
Determines best reservation time:
1. exact match
2. closest within range
3. nearest alternative
4. fail if none

### 4.5 Orchestrator
Coordinates:
- validation
- adapter calls
- selection
- booking
- response formatting

### 4.6 Session Manager
Responsible for:
- one-time login bootstrap in headed mode
- loading persisted local auth/session artifacts
- enforcing auth preflight before restaurant search
- clicking `Log In` and pausing when logged out
- validating session health before booking and before final submit
- refreshing session via user-assisted login when expired

---

## 5. Booking Strategy

### Primary
- Attempt authenticated autonomous booking via browser automation using existing logged-in session
- Run an auth preflight check before restaurant search
- If logged out, enter user-assisted login branch, then continue automatically after login is detected

### Fallback
- If booking cannot complete autonomously:
  - return `requires_user_action` with actionable reason/prompt/resume token
  - return alternatives and/or handoff link when appropriate

### CAPTCHA Handling
- CAPTCHA and forced verification are exception paths
- Pause execution
- Prompt user to complete required action
- Resume flow with preserved context

### Failure / User-Action Reasons
- `login_required`
- `login_refresh_required`
- `captcha_required`
- `checkout_opened`
- `sms_verification_required` (rare fallback when provider still forces verification despite login)

---

## 6. Output Contract

### Success
- restaurant
- time
- party size
- confirmation status
- confirmation details (if available)

### Failure
- reason
- alternative times (if available)
- handoff link (if applicable)

---

## 7. Constraints

- Keep dependencies minimal
- Prefer deterministic logic
- Avoid complex infrastructure
- No reliance on anti-bot evasion as a core dependency
- Do not capture or store user credentials; persist only local browser session artifacts

---

## 8. Success Criteria

- End-to-end booking works on common cases
- Failures degrade gracefully
- System is usable without manual debugging

---

## 9. Future Extensions

- OpenTable integration (API or adapter)
- Multi-platform support
- User preferences
- Calendar integration
- Notifications
