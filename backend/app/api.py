from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.comparison import verify_label
from backend.app.models import ApplicationData, VerificationResult
from backend.app.vision import (
    GeminiVisionService,
    VisionConfigurationError,
    VisionInvalidImageError,
    VisionParseError,
    VisionProviderError,
    VisionService,
    VisionTimeoutError,
)


logger = logging.getLogger("backend.app.verify")

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def get_vision_service() -> VisionService:
    return GeminiVisionService()


@router.post("/verify", response_model=VerificationResult)
async def verify(
    image: UploadFile | None = File(default=None),
    application_data: str | None = Form(default=None),
    vision_service: VisionService = Depends(get_vision_service),
) -> VerificationResult | JSONResponse:
    start = time.perf_counter()

    image_error = _validate_image_metadata(image)
    if image_error is not None:
        return _error_response(*image_error, start=start)

    assert image is not None
    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        return _error_response(
            400,
            "empty_image",
            "Upload a non-empty label image.",
            start=start,
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return _error_response(
            413,
            "image_too_large",
            "Upload a label image smaller than 8 MB.",
            start=start,
        )

    application = _parse_application_data(application_data)
    if isinstance(application, JSONResponse):
        return _with_latency(application, _latency_ms(start))

    try:
        extracted_label = vision_service.extract_label(
            image_bytes,
            content_type=image.content_type,
        )
        result = verify_label(application, extracted_label)
        result.extracted_label = extracted_label
        result.latency_ms = _latency_ms(start)
        logger.info(
            "verify completed verdict=%s latency_ms=%s",
            result.verdict,
            result.latency_ms,
        )
        return result
    except VisionInvalidImageError:
        return _error_response(
            400,
            "invalid_image",
            "Upload a readable label image.",
            start=start,
        )
    except VisionTimeoutError:
        return _error_response(
            504,
            "vision_timeout",
            "The label image took too long to process. Try a clearer or smaller image.",
            start=start,
        )
    except VisionConfigurationError:
        return _error_response(
            500,
            "vision_not_configured",
            "Vision service is not configured.",
            start=start,
        )
    except VisionParseError:
        return _error_response(
            502,
            "vision_parse_error",
            "The vision service returned an unreadable extraction result.",
            start=start,
        )
    except VisionProviderError:
        return _error_response(
            502,
            "vision_provider_error",
            "The vision service could not process the label image.",
            start=start,
        )
    except Exception:
        logger.exception("verify failed unexpectedly latency_ms=%s", _latency_ms(start))
        return _error_response(
            500,
            "verify_failed",
            "Verification failed unexpectedly.",
            start=start,
            log_error=False,
        )


def _validate_image_metadata(
    image: UploadFile | None,
) -> tuple[int, str, str] | None:
    if image is None:
        return 400, "missing_image", "Upload a label image."

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        return (
            400,
            "invalid_image_type",
            "Upload a JPEG, PNG, or WebP label image.",
        )

    return None


def _parse_application_data(application_data: str | None) -> ApplicationData | JSONResponse:
    if application_data is None:
        return _plain_error_response(
            400,
            "missing_application_data",
            "Include application data for this label.",
        )

    try:
        payload = json.loads(application_data)
    except json.JSONDecodeError:
        return _plain_error_response(
            400,
            "invalid_application_data",
            "Application data must be valid JSON.",
        )

    try:
        application = ApplicationData.model_validate(payload)
    except ValidationError:
        return _plain_error_response(
            400,
            "invalid_application_data",
            "Application data must include exactly the required label fields.",
        )

    empty_fields = [
        field_name
        for field_name, value in application.model_dump().items()
        if isinstance(value, str) and not value.strip()
    ]
    if empty_fields:
        return _plain_error_response(
            400,
            "invalid_application_data",
            f"Application data has empty required fields: {', '.join(empty_fields)}.",
        )

    return application


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    start: float,
    log_error: bool = True,
) -> JSONResponse:
    latency_ms = _latency_ms(start)
    response = _plain_error_response(status_code, code, message)
    response = _with_latency(response, latency_ms)
    if log_error:
        logger.warning(
            "verify failed code=%s status_code=%s latency_ms=%s",
            code,
            status_code,
            latency_ms,
        )
    return response


def _plain_error_response(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def _with_latency(response: JSONResponse, latency_ms: int | float) -> JSONResponse:
    body = json.loads(response.body)
    body["latency_ms"] = int(latency_ms)
    return JSONResponse(status_code=response.status_code, content=body)


def _latency_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))
