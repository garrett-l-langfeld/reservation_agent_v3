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
Implement auth preflight before restaurant search for real Resy runs: check login first, click `Log In` when needed, wait for user login, then continue with restaurant resolution/availability using persisted session state.

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
- Session persistence: YES (reuse authenticated local browser session across runs)
- Required booking info: user name, email, and phone
- Added minimal CLI for orchestrator execution via `src/main.py` with `--request-json` or `--request-file`

---

## Open Questions
- Session TTL/expiry handling strategy for `login_refresh_required`
- How to validate profile/session artifact hygiene over long-running local usage
- Most reliable login-detection signals across Resy page variants before search begins

---

## Notes for Codex
- Do not expand scope
- Do not introduce heavy frameworks
- Keep everything modular and simple
- Ask for clarification if uncertain
