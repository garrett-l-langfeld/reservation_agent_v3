# Reservation Agent — Project State

## Current Status
IN PROGRESS (MVP CORE COMPLETE)

---

## Current Phase
Phase 10 — Testing (Completed)

---

## Completed Phases
- Phase 1 — Project Definition
- Phase 2 — Input / Output Contract
- Phase 3 — Platform Adapter Interface
- Phase 4 — Mock Adapter
- Phase 5 — Validation
- Phase 6 — Slot Selection
- Phase 7 — Orchestrator
- Phase 8 — Resy Integration
- Phase 9 — Logging
- Phase 10 — Testing

---

## Next Task
Prepare for production hardening of real browser automation and anti-bot resilience (CLI entrypoint now available for local end-to-end runs)

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
- Required booking info: user name, email, and phone
- Added minimal CLI for orchestrator execution via `src/main.py` with `--request-json` or `--request-file`

---

## Open Questions
- How should CAPTCHA UX work? (CLI pause vs browser handoff)
- Retry strategy for failed bookings?

---

## Notes for Codex
- Do not expand scope
- Do not introduce heavy frameworks
- Keep everything modular and simple
- Ask for clarification if uncertain
