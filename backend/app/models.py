from enum import Enum

from pydantic import BaseModel, ConfigDict


class FieldStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VerificationVerdict(str, Enum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class BatchItemStatus(str, Enum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"


class ApplicationData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str
    product_class: str
    producer_name: str
    country_of_origin: str
    abv: str | float
    net_contents: str
    government_warning: str


class ExtractedLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = None
    product_class: str | None = None
    producer_name: str | None = None
    country_of_origin: str | None = None
    abv: str | float | None = None
    net_contents: str | None = None
    government_warning: str | None = None


class FieldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    status: FieldStatus
    expected: str
    actual: str | None
    strategy: str
    score: float | None = None
    message: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: VerificationVerdict
    fields: list[FieldResult]
    extracted_label: ExtractedLabel | None = None
    latency_ms: int | None = None


class BatchItemError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class BatchItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str | None = None
    status: BatchItemStatus
    result: VerificationResult | None = None
    error: BatchItemError | None = None
    latency_ms: int


class BatchVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    passed: int
    needs_review: int
    errors: int
    latency_ms: int
    items: list[BatchItemResult]
