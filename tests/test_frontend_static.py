from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_frontend_verify_request_has_client_timeout() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "AbortController" in response.text
    assert "requestTimeoutMs = 16000" in response.text
    assert "The label took too long to read." in response.text
    assert "Line breaks do not matter." in response.text


def test_frontend_prefills_standard_government_warning() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "standardGovernmentWarning" in response.text
    assert "According to the Surgeon General" in response.text
    assert "prefillStandardWarning" in response.text


def test_frontend_batch_view_is_available() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Batch Labels" in response.text
    assert "Choose label images" in response.text
    assert "batch-image-input" in response.text
    assert "multiple" in response.text
    assert "Check All Labels" in response.text


def test_frontend_batch_request_has_summary_drilldown_and_progress() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'fetch("/verify/batch"' in response.text
    assert 'formData.append("image_ids"' in response.text
    assert "Approved" in response.text
    assert "Needs Review" in response.text
    assert "Total" in response.text
    assert "<details" in response.text
    assert "Expected" in response.text
    assert "Found" in response.text
    assert "Checking ${count} label" in response.text
    assert "progress-bar" in response.text
