# Reservation Agent — Architecture & PRD

_Last updated: April 2026_

---

## 1. Overview

A Resy-first reservation agent that attempts to autonomously book a restaurant reservation based on structured user input. If booking fails, the system falls back to user handoff.

---

## 2. Core Goal

Given:
- restaurant name
- location
- date
- time or time range
- party size

The system should:
1. Find the restaurant on Resy
2. Check availability
3. Select the best slot
4. Attempt to book the reservation
5. Return confirmation OR fallback options

---

## 3. Scope

### In Scope
- Single platform: Resy
- Structured input only
- Availability lookup
- Slot selection
- Attempted booking (best-effort)
- CAPTCHA → prompt user + resume
- Fallback to handoff

### Out of Scope
- Multi-platform support
- Phone reservations
- User accounts
- Payment handling
- Background monitoring
- Preference learning

---

## 4. Core Components

### 4.1 Request Intake
Parses structured user input into a normalized format.

### 4.2 Validation
Ensures:
- valid date/time
- valid party size
- required fields present

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

---

## 5. Booking Strategy

### Primary
- Attempt autonomous booking via browser automation

### Fallback
- If booking fails:
  - return alternatives
  - provide handoff link

### CAPTCHA Handling
- Pause execution
- Prompt user to complete
- Resume flow

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