from __future__ import annotations

import argparse
import json
from datetime import date
from datetime import datetime
from typing import Any

from src.mock_resy_adapter import MockResyAdapter
from src.orchestrator import process_reservation_request


def greet(name: str = "world") -> str:
    return f"Hello, {name}!"


def run_with_mock_adapter(
    request: dict[str, Any],
    reference_date: date | None = None,
) -> dict[str, Any]:
    adapter = MockResyAdapter()
    return process_reservation_request(
        request,
        adapter=adapter,
        reference_date=reference_date,
    )


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run reservation orchestration against the mock Resy adapter.",
    )
    request_group = parser.add_mutually_exclusive_group(required=True)
    request_group.add_argument(
        "--request-json",
        help="Reservation request as a JSON object string.",
    )
    request_group.add_argument(
        "--request-file",
        help="Path to a JSON file containing the reservation request.",
    )
    parser.add_argument(
        "--reference-date",
        help="Optional YYYY-MM-DD date for deterministic normalization.",
    )

    args = parser.parse_args(argv)

    try:
        request = _load_request(args.request_json, args.request_file)
        parsed_reference_date = _parse_reference_date(args.reference_date)
    except ValueError as error:
        print(json.dumps({"status": "failure", "reason": str(error)}))
        return 2

    result = run_with_mock_adapter(
        request=request,
        reference_date=parsed_reference_date,
    )
    print(json.dumps(result))
    return 0


def _load_request(
    request_json: str | None,
    request_file: str | None,
) -> dict[str, Any]:
    if request_json is not None:
        try:
            payload = json.loads(request_json)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid_request_json:{error.msg}") from error
    elif request_file is not None:
        try:
            with open(request_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise ValueError(f"request_file_error:{error}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid_request_file_json:{error.msg}") from error
    else:
        raise ValueError("missing_request_input")

    if not isinstance(payload, dict):
        raise ValueError("request_must_be_json_object")
    return payload


def _parse_reference_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("invalid_reference_date") from error


if __name__ == "__main__":
    raise SystemExit(run_cli())
