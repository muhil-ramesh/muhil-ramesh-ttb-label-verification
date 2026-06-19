from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_frontend_verify_request_has_client_timeout() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "AbortController" in response.text
    assert "requestTimeoutMs = 16000" in response.text
    assert "The label took too long to read." in response.text
    assert (
        "capital letters, punctuation, spaces, and line breaks"
        in response.text
    )
