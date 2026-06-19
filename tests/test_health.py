from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ttb-label-verification",
        "environment": "local",
    }


def test_root_serves_frontend() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "TTB Label Verification" in response.text
    assert "/static/app.js" in response.text


def test_frontend_script_calls_health() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'fetch("/health"' in response.text
