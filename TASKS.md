# Reservation Agent — Task Plan

## Rules for Codex
- Work sequentially
- Do NOT skip steps
- Do NOT add extra features
- Keep implementation minimal and modular

---

## Phase 1 — Project Definition

### Task 1.1
Create a project brief describing:
- inputs
- outputs
- scope
- non-goals
- booking = in scope (best-effort)

---

## Phase 2 — Input / Output Contract

### Task 2.1
Define request schema:
- restaurant_name
- location
- date
- time OR time_range
- party_size
- user_name
- user_email
- user_phone

### Task 2.2
Define response schema:
- success
- failure
- no availability
- ambiguous restaurant

---

## Phase 3 — Platform Adapter Interface

### Task 3.1
Define interface with methods:
- resolve_restaurant
- get_availability
- attempt_booking
- generate_handoff

---

## Phase 4 — Mock Adapter

### Task 4.1
Create mock adapter with:
- exact match scenario
- near match scenario
- no availability
- ambiguous restaurant

---

## Phase 5 — Validation

### Task 5.1
Validate:
- required fields
- valid date/time
- party size
- email format
- phone format

### Task 5.2
Normalize:
- time formats
- date formats

---

## Phase 6 — Slot Selection

### Task 6.1
Implement ranking logic:
1. exact match
2. closest in range
3. closest overall
4. no match

---

## Phase 7 — Orchestrator

### Task 7.1
Wire flow:
- validate
- resolve restaurant
- get availability
- select slot
- attempt booking
- format response

---

## Phase 8 — Resy Integration

### Task 8.1
Implement Resy adapter:
- search restaurant
- extract availability
- attempt booking

### Task 8.2
Handle CAPTCHA:
- pause execution
- prompt user
- resume

### Task 8.3
Fallback behavior:
- booking fails → return alternatives + handoff

---

## Phase 9 — Logging

### Task 9.1
Add logs:
- request
- validation
- availability
- selection
- booking attempt
- fallback

---

## Phase 10 — Testing

### Task 10.1
Test scenarios:
- success booking
- fallback booking
- no availability
- invalid input
- platform failure

---

## Done Criteria
- End-to-end flow works
- Booking succeeds in common cases
- Failures are handled cleanly
