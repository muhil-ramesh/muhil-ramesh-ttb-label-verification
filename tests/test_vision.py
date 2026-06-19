from io import BytesIO
import json

import pytest
from PIL import Image

from backend.app.models import ExtractedLabel
from backend.app.vision import (
    EXTRACTED_LABEL_FIELDS,
    FakeVisionService,
    GeminiVisionService,
    VisionConfigurationError,
    VisionInvalidImageError,
    VisionParseError,
    VisionTimeoutError,
    extracted_label_json_schema,
    preprocess_label_image,
)


WARNING = "GOVERNMENT WARNING: EXACTLY AS PRINTED"


def image_bytes(size: tuple[int, int] = (800, 600)) -> bytes:
    image = Image.new("RGB", size, "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def extracted_payload(**overrides) -> dict[str, str | None]:
    payload = {
        "brand_name": "Sunset Ridge",
        "product_class": "Cabernet Sauvignon",
        "producer_name": "North Valley Estate Winery LLC",
        "country_of_origin": "USA",
        "abv": "45% Alc./Vol. (90 Proof)",
        "net_contents": "750 mL",
        "government_warning": WARNING,
    }
    payload.update(overrides)
    return payload


class StubTransport:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request_body, timeout_seconds, model):
        self.calls.append(
            {
                "request_body": request_body,
                "timeout_seconds": timeout_seconds,
                "model": model,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


class Timeout(Exception):
    pass


def test_fake_vision_service_returns_label_and_records_call() -> None:
    label = ExtractedLabel(brand_name="Sunset Ridge")
    service = FakeVisionService(label=label)
    upload = b"not inspected by fake"

    result = service.extract_label(upload, content_type="image/jpeg")

    assert result == label
    assert len(service.calls) == 1
    assert service.calls[0].image_bytes == upload
    assert service.calls[0].content_type == "image/jpeg"


def test_preprocess_downscales_and_reencodes_to_jpeg_data_url() -> None:
    processed = preprocess_label_image(image_bytes((2400, 1200)), max_long_side=1600)

    assert processed.content_type == "image/jpeg"
    assert processed.data_url.startswith("data:image/jpeg;base64,")
    assert max(processed.width, processed.height) == 1600
    assert processed.data.startswith(b"\xff\xd8")


def test_invalid_image_fails_before_provider_call() -> None:
    transport = StubTransport(response=gemini_response(extracted_payload()))
    service = GeminiVisionService(transport=transport)

    with pytest.raises(VisionInvalidImageError):
        service.extract_label(b"not an image")

    assert transport.calls == []


def test_gemini_service_uses_strict_schema_and_inline_image() -> None:
    transport = StubTransport(response=gemini_response(extracted_payload()))
    service = GeminiVisionService(
        transport=transport,
        model="gemini-test-model",
        timeout_seconds=3.5,
    )

    result = service.extract_label(image_bytes(), content_type="image/png")

    assert result.brand_name == "Sunset Ridge"
    assert result.government_warning == WARNING

    [call] = transport.calls
    assert call["model"] == "gemini-test-model"
    assert call["timeout_seconds"] == 3.5

    request_body = call["request_body"]
    generation_config = request_body["generationConfig"]
    assert generation_config["candidateCount"] == 1
    assert generation_config["temperature"] == 0

    response_format = generation_config["responseFormat"]["text"]
    assert response_format["mimeType"] == "APPLICATION_JSON"
    assert response_format["schema"] == extracted_label_json_schema()

    schema = response_format["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(EXTRACTED_LABEL_FIELDS)

    prompt = request_body["contents"][0]["parts"][0]["text"]
    assert "character-for-character" in prompt
    assert "Do not complete the statutory warning from memory." in prompt
    assert "Do not normalize case." in prompt

    image_part = request_body["contents"][0]["parts"][1]["inline_data"]
    assert image_part["mime_type"] == "image/jpeg"
    assert isinstance(image_part["data"], str)
    assert len(image_part["data"]) > 100


def test_non_label_or_unreadable_image_returns_all_nulls_from_model() -> None:
    null_payload = {field: None for field in EXTRACTED_LABEL_FIELDS}
    transport = StubTransport(response=gemini_response(null_payload))
    service = GeminiVisionService(transport=transport)

    result = service.extract_label(image_bytes())

    assert result == ExtractedLabel()


def test_misread_warning_is_preserved_from_structured_output() -> None:
    misread_warning = "GOVERNMENT WARNlNG: EXACTLY AS PRlNTED"
    transport = StubTransport(
        response=gemini_response(
            extracted_payload(government_warning=misread_warning)
        )
    )
    service = GeminiVisionService(transport=transport)

    result = service.extract_label(image_bytes())

    assert result.government_warning == misread_warning


def test_malformed_json_raises_parse_error() -> None:
    transport = StubTransport(response=gemini_text_response("{not-json"))
    service = GeminiVisionService(transport=transport)

    with pytest.raises(VisionParseError):
        service.extract_label(image_bytes())


def test_missing_or_extra_structured_fields_raise_parse_error() -> None:
    missing_payload = extracted_payload()
    missing_payload.pop("government_warning")
    missing_transport = StubTransport(response=gemini_response(missing_payload))

    with pytest.raises(VisionParseError, match="missing fields"):
        GeminiVisionService(transport=missing_transport).extract_label(image_bytes())

    extra_payload = extracted_payload(extra_field="not allowed")
    extra_transport = StubTransport(response=gemini_response(extra_payload))

    with pytest.raises(VisionParseError, match="extra fields"):
        GeminiVisionService(transport=extra_transport).extract_label(image_bytes())


def test_provider_timeout_maps_to_typed_timeout_error() -> None:
    transport = StubTransport(error=Timeout("timed out"))
    service = GeminiVisionService(transport=transport)

    with pytest.raises(VisionTimeoutError):
        service.extract_label(image_bytes())


def test_missing_gemini_api_key_raises_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    service = GeminiVisionService()

    with pytest.raises(VisionConfigurationError, match="GEMINI_API_KEY"):
        service.extract_label(image_bytes())


def gemini_response(payload: dict[str, str | None]) -> dict:
    return gemini_text_response(json.dumps(payload))


def gemini_text_response(text: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": text,
                        }
                    ]
                }
            }
        ]
    }
