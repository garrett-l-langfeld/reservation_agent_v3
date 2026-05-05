# Reservation Agent — Project Brief

_Task 1.1 output_

## Goal
Build a simple, modular reservation agent that takes structured input and attempts to book a table on Resy. Booking is required for MVP and is best-effort.

## Inputs
- `restaurant_name`
- `location`
- `date`
- `time` OR `time_range`
- `party_size`

## Outputs

### Success
- `restaurant`
- `time`
- `party_size`
- `confirmation_status`
- `confirmation_details` (if available)

### Failure / Fallback
- `reason`
- `alternative_times` (if available)
- `handoff_link` (if applicable)

## Scope (MVP)
- Platform: Resy only
- Structured input only
- Restaurant resolution
- Availability lookup
- Slot selection
- Booking attempt (best-effort, required)
- Login-first flow with persisted local session reuse across runs
- CAPTCHA/verification handling via user-assisted pause and resume as fallback
- Fallback to alternatives + handoff when booking fails

## Non-Goals (MVP)
- Multi-platform support
- Phone reservations
- Multi-account management
- Credential storage/management
- Payment handling
- Preference learning
- Background monitoring
- Calendar/notification integrations
