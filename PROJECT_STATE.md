# Reservation Agent — Project State

## Current Status
NOT STARTED

---

## Current Phase
Phase 1 — Project Definition

---

## Completed Phases
- None

---

## Next Task
Task 1.1 — Create project brief

---

## Known Risks
- Resy anti-bot / CAPTCHA
- Booking flow fragility
- UI changes

---

## Key Decisions
- Platform: Resy
- Autobooking: YES (best-effort)
- Fallback: YES (handoff)
- CAPTCHA: user-assisted

---

## Open Questions
- What user info is required for booking? (name, email, phone)
- How should CAPTCHA UX work? (CLI pause vs browser handoff)
- Retry strategy for failed bookings?

---

## Notes for Codex
- Do not expand scope
- Do not introduce heavy frameworks
- Keep everything modular and simple
- Ask for clarification if uncertain