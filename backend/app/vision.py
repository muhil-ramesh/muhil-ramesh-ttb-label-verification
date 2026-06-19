from __future__ import annotations

import base64
from dataclasses import dataclass, field
from io import BytesIO
import json
import os
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError

from backend.app.models import ExtractedLabel


DEFAULT_VISION_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 4.0
GEMINI_API_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
MAX_IMAGE_LONG_SIDE = 1600
JPEG_QUALITY = 88

EXTRACTED_LABEL_FIELDS = (
    "brand_name",
    "product_class",
    "producer_name",
    "country_of_origin",
    "abv",
    "net_contents",
    "government_warning",
)

VISION_EXTRACTION_PROMPT = """
Extract visible text from this alcohol label into the required structured fields.

Use only text visible in the image. Do not infer, correct, normalize, or guess.
If a field is not visible or not confidently readable, return null.
If the image is not an alcohol label, return null for every field.

Fields:
- brand_name
- product_class
- producer_name
- country_of_origin
- abv
- net_contents
- government_warning

For government_warning, copy the visible warning character-for-character.
Preserve capitalization, punctuation, spacing, line breaks if present, and OCR-like mistakes.
Do not complete the statutory warning from memory.
Do not correct spelling.
Do not normalize case.
If partly readable, return only the readable visible text exactly.
If no meaningful warning text is readable, return null.
""".strip()


class VisionServiceError(Exception):
    """Base error for image extraction failures."""


class VisionConfigurationError(VisionServiceError):
    """Raised when the vision service is missing required configuration."""


class VisionInvalidImageError(VisionServiceError):
    """Raised when the uploaded bytes are not a valid image."""


class VisionTimeoutError(VisionServiceError):
    """Raised when the model call times out."""


class VisionProviderError(VisionServiceError):
    """Raised when the model provider fails before returning usable output."""


class VisionParseError(VisionServiceError):
    """Raised when provider output cannot be validated as an ExtractedLabel."""


class VisionService(Protocol):
    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        ...


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    data_url: str
    width: int
    height: int


@dataclass(frozen=True)
class VisionServiceCall:
    image_bytes: bytes
    content_type: str | None


@dataclass
class FakeVisionService:
    label: ExtractedLabel = field(default_factory=ExtractedLabel)
    error: Exception | None = None
    calls: list[VisionServiceCall] = field(default_factory=list)

    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        self.calls.append(
            VisionServiceCall(image_bytes=image_bytes, content_type=content_type)
        )
        if self.error is not None:
            raise self.error
        return self.label


def extracted_label_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(EXTRACTED_LABEL_FIELDS),
        "properties": {
            field_name: {"type": ["string", "null"]}
            for field_name in EXTRACTED_LABEL_FIELDS
        },
    }


def preprocess_label_image(
    image_bytes: bytes,
    *,
    max_long_side: int = MAX_IMAGE_LONG_SIDE,
    jpeg_quality: int = JPEG_QUALITY,
) -> ProcessedImage:
    if not image_bytes:
        raise VisionInvalidImageError("Image upload is empty.")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image = _to_rgb_on_white(image)
            image.thumbnail(
                (max_long_side, max_long_side),
                Image.Resampling.LANCZOS,
            )

            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise VisionInvalidImageError("Image upload is not a readable image.") from exc

    data = output.getvalue()
    data_url = (
        "data:image/jpeg;base64,"
        f"{base64.b64encode(data).decode('ascii')}"
    )
    return ProcessedImage(
        data=data,
        content_type="image/jpeg",
        data_url=data_url,
        width=image.width,
        height=image.height,
    )


def _to_rgb_on_white(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def _structured_output_format() -> dict[str, Any]:
    return {
        "text": {
            "mimeType": "APPLICATION_JSON",
            "schema": extracted_label_json_schema(),
        },
    }


class GeminiVisionService:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("GEMINI_VISION_MODEL", DEFAULT_VISION_MODEL)
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def extract_label(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ExtractedLabel:
        processed_image = preprocess_label_image(image_bytes)
        response = self._create_response(processed_image)
        return _parse_extracted_label_response(response)

    def _create_response(self, processed_image: ProcessedImage) -> Any:
        request_body = _build_gemini_request_body(processed_image)
        try:
            if self._transport is not None:
                return self._transport(request_body, self.timeout_seconds, self.model)
            return self._post_gemini_request(request_body)
        except VisionServiceError:
            raise
        except Exception as exc:
            if _is_timeout_error(exc):
                raise VisionTimeoutError("Vision model request timed out.") from exc
            raise VisionProviderError("Vision model request failed.") from exc

    def _post_gemini_request(self, request_body: dict[str, Any]) -> Any:
        api_key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise VisionConfigurationError("GEMINI_API_KEY is not configured.")

        url = GEMINI_API_ENDPOINT.format(model=quote(self.model, safe=""))
        request = Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VisionProviderError(f"Gemini API request failed: {detail}") from exc
        except json.JSONDecodeError as exc:
            raise VisionParseError("Gemini API response was not valid JSON.") from exc


def _build_gemini_request_body(processed_image: ProcessedImage) -> dict[str, Any]:
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{VISION_EXTRACTION_PROMPT}\n\n"
                            "Extract the required label fields."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": processed_image.content_type,
                            "data": base64.b64encode(processed_image.data).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "candidateCount": 1,
            "temperature": 0,
            "responseFormat": _structured_output_format(),
        },
    }


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError | socket.timeout):
        return True
    if isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError | socket.timeout):
        return True
    return exc.__class__.__name__ in {
        "APITimeoutError",
        "ReadTimeout",
        "Timeout",
        "TimeoutError",
    }


def _parse_extracted_label_response(response: Any) -> ExtractedLabel:
    payload = _extract_structured_payload(response)
    return _parse_extracted_label_payload(payload)


def _extract_structured_payload(response: Any) -> Any:
    direct_payload = _get_value(response, "output_parsed")
    if direct_payload is not None:
        return direct_payload

    output_text = _get_value(response, "output_text")
    if output_text:
        return output_text

    text = _get_value(response, "text")
    if text:
        return text

    candidates = _get_value(response, "candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            content = _get_value(candidate, "content")
            parts = _get_value(content, "parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                text = _get_value(part, "text")
                if text:
                    return text

    output = _get_value(response, "output")
    if isinstance(output, list):
        for output_item in output:
            content = _get_value(output_item, "content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                parsed = _get_value(content_item, "parsed")
                if parsed is not None:
                    return parsed
                text = _get_value(content_item, "text")
                if text:
                    return text

    raise VisionParseError("Vision response did not contain structured output.")


def _get_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _parse_extracted_label_payload(payload: Any) -> ExtractedLabel:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise VisionParseError("Vision response was not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise VisionParseError("Vision response JSON was not an object.")

    expected_fields = set(EXTRACTED_LABEL_FIELDS)
    actual_fields = set(payload)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(actual_fields - expected_fields)
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if extra:
            details.append(f"extra fields: {', '.join(extra)}")
        raise VisionParseError("; ".join(details))

    try:
        return ExtractedLabel.model_validate(payload)
    except ValidationError as exc:
        raise VisionParseError("Vision response did not match ExtractedLabel.") from exc
