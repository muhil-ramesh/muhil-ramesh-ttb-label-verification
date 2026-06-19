from enum import Enum

from pydantic import BaseModel, ConfigDict


class FieldStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VerificationVerdict(str, Enum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


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
