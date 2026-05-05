import json

from src.mock_resy_adapter import MockResyAdapter
from src.main import run_cli
from src.main import run_with_real_adapter


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


def test_run_cli_supports_real_adapter_via_factory(monkeypatch, capsys):
    created: dict[str, int | bool | str] = {}

    def fake_create_real_adapter(*, headless: bool, timeout_ms: int, session_profile_dir: str):
        created["called"] = True
        created["headless"] = headless
        created["timeout_ms"] = timeout_ms
        created["session_profile_dir"] = session_profile_dir
        return MockResyAdapter()

    monkeypatch.setattr("src.main._create_real_adapter", fake_create_real_adapter)

    exit_code = run_cli(
        [
            "--request-json",
            json.dumps(_request_payload()),
            "--adapter",
            "real",
            "--timeout-ms",
            "1234",
        ]
    )

    captured = capsys.readouterr()
    response = json.loads(captured.out)

    assert exit_code == 0
    assert response["status"] == "success"
    assert created == {
        "called": True,
        "headless": True,
        "timeout_ms": 1234,
        "session_profile_dir": ".resy_profile",
    }


def test_run_with_real_adapter_closes_client(monkeypatch):
    closed = {"called": False}

    class FakeClient:
        def close(self):
            closed["called"] = True

    class FakeAdapter(MockResyAdapter):
        def __init__(self):
            self.client = FakeClient()

    def fake_create_real_adapter(*, headless: bool, timeout_ms: int, session_profile_dir: str):
        _ = (headless, timeout_ms, session_profile_dir)
        return FakeAdapter()

    monkeypatch.setattr("src.main._create_real_adapter", fake_create_real_adapter)

    result = run_with_real_adapter(_request_payload(), reference_date=None)

    assert result["status"] == "success"
    assert closed["called"] is True
