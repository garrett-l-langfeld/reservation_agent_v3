from __future__ import annotations

import argparse
import json
from datetime import date
from datetime import datetime
from typing import Any

from src.mock_resy_adapter import MockResyAdapter
from src.orchestrator import process_reservation_request
from src.resy_adapter import ResyAdapter
from src.resy_live_client import ResyLiveClient


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


def run_with_real_adapter(
    request: dict[str, Any],
    reference_date: date | None = None,
    *,
    headless: bool = True,
    timeout_ms: int = 20_000,
) -> dict[str, Any]:
    adapter = _create_real_adapter(headless=headless, timeout_ms=timeout_ms)
    try:
        return process_reservation_request(
            request,
            adapter=adapter,
            reference_date=reference_date,
        )
    finally:
        _close_adapter_client(adapter)


def _create_real_adapter(*, headless: bool, timeout_ms: int) -> ResyAdapter:
    return ResyAdapter(ResyLiveClient(headless=headless, timeout_ms=timeout_ms))


def _close_adapter_client(adapter: Any) -> None:
    client = getattr(adapter, "client", None)
    close = getattr(client, "close", None)
    if callable(close):
        close()


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run reservation orchestration against mock or live Resy adapters.",
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
    parser.add_argument(
        "--adapter",
        choices=["mock", "real"],
        default="mock",
        help="Adapter backend to use (default: mock).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run live adapter with a visible browser window (real adapter only).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=20_000,
        help="Per-operation Playwright timeout in milliseconds (real adapter only).",
    )

    args = parser.parse_args(argv)

    try:
        request = _load_request(args.request_json, args.request_file)
        parsed_reference_date = _parse_reference_date(args.reference_date)
    except ValueError as error:
        print(json.dumps({"status": "failure", "reason": str(error)}))
        return 2

    if args.adapter == "mock":
        result = run_with_mock_adapter(
            request=request,
            reference_date=parsed_reference_date,
        )
    else:
        try:
            result = run_with_real_adapter(
                request=request,
                reference_date=parsed_reference_date,
                headless=not args.headed,
                timeout_ms=args.timeout_ms,
            )
        except Exception as error:
            print(
                json.dumps(
                    {
                        "status": "failure",
                        "reason": "real_adapter_init_or_runtime_error",
                        "details": str(error),
                    }
                )
            )
            return 2

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
