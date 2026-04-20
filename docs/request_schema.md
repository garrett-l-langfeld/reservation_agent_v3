# Reservation Agent — Request Schema

_Task 2.1 output_

## Schema

```json
{
  "restaurant_name": "string",
  "location": "string",
  "date": "YYYY-MM-DD",
  "time": "h:mm AM/PM (optional)",
  "time_range": {
    "earliest": "h:mm AM/PM",
    "latest": "h:mm AM/PM"
  },
  "party_size": "integer"
}
```

## Rules
- Required fields: `restaurant_name`, `location`, `date`, `party_size`
- Exactly one of `time` or `time_range` must be provided
- `party_size` must be a positive integer

## Example (Exact Time)

```json
{
  "restaurant_name": "Zuni Cafe",
  "location": "San Francisco, CA",
  "date": "2026-05-05",
  "time": "7:00 PM",
  "party_size": 2
}
```

## Example (Time Range)

```json
{
  "restaurant_name": "Zuni Cafe",
  "location": "San Francisco, CA",
  "date": "2026-05-05",
  "time_range": {
    "earliest": "5:00 PM",
    "latest": "8:00 PM"
  },
  "party_size": 2
}
```
