import json

from src.main import run_cli


def _request_payload() -> dict:
    return {
        "restaurant_name": "Zuni Cafe",
        "location": "San Francisco, CA",
        "date": "May 5, 2026",
        "time": "7 pm",
        "party_size": 2,
        "user_name": "Alex Example",
        "user_email": "alex@example.com",
        "user_phone": "+1 (415) 555-1212",
    }


def test_run_cli_accepts_request_json(capsys):
    exit_code = run_cli(["--request-json", json.dumps(_request_payload())])

    captured = capsys.readouterr()
    response = json.loads(captured.out)

    assert exit_code == 0
    assert response["status"] == "success"


def test_run_cli_accepts_request_file(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request_payload()), encoding="utf-8")

    exit_code = run_cli(["--request-file", str(request_path), "--reference-date", "2026-04-20"])

    captured = capsys.readouterr()
    response = json.loads(captured.out)

    assert exit_code == 0
    assert response["status"] == "success"


def test_run_cli_rejects_invalid_request_json(capsys):
    exit_code = run_cli(["--request-json", "{bad json}"])

    captured = capsys.readouterr()
    response = json.loads(captured.out)

    assert exit_code == 2
    assert response["status"] == "failure"
    assert response["reason"].startswith("invalid_request_json:")
