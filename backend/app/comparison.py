from difflib import SequenceMatcher
import re

from backend.app.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    FieldStatus,
    VerificationResult,
    VerificationVerdict,
)


FUZZY_THRESHOLD = 90.0
ABV_TOLERANCE_PERCENTAGE_POINTS = 0.1
NET_CONTENTS_TOLERANCE_ML = 1.0

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ModuleNotFoundError:
    _rapidfuzz_fuzz = None


def _sort_tokens(value: str) -> str:
    return " ".join(sorted(value.split()))


def _fallback_token_sort_ratio(expected: str, actual: str) -> float:
    expected_sorted = _sort_tokens(expected)
    actual_sorted = _sort_tokens(actual)
    return SequenceMatcher(None, expected_sorted, actual_sorted).ratio() * 100


def _token_sort_ratio(expected: str, actual: str) -> float:
    if _rapidfuzz_fuzz is not None:
        return float(_rapidfuzz_fuzz.token_sort_ratio(expected, actual))
    return _fallback_token_sort_ratio(expected, actual)


def _stringify(value: str | float | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _normalize_text(value: str) -> str:
    no_punctuation = re.sub(r"[^\w\s]", " ", value.casefold())
    return re.sub(r"\s+", " ", no_punctuation).strip()


def _field_result(
    *,
    field: str,
    status: FieldStatus,
    expected: str | float,
    actual: str | float | None,
    strategy: str,
    score: float | None,
    message: str,
) -> FieldResult:
    return FieldResult(
        field=field,
        status=status,
        expected=str(expected),
        actual=_stringify(actual),
        strategy=strategy,
        score=score,
        message=message,
    )


def _missing_actual_result(
    *,
    field: str,
    expected: str | float,
    strategy: str,
) -> FieldResult:
    return _field_result(
        field=field,
        status=FieldStatus.FAIL,
        expected=expected,
        actual=None,
        strategy=strategy,
        score=None,
        message="Extracted value is missing.",
    )


def _compare_fuzzy(field: str, expected: str, actual: str | None) -> FieldResult:
    strategy = f"fuzzy_token_sort_ratio>={FUZZY_THRESHOLD:.0f}"
    if actual is None:
        return _missing_actual_result(field=field, expected=expected, strategy=strategy)

    normalized_expected = _normalize_text(expected)
    normalized_actual = _normalize_text(actual)
    score = round(_token_sort_ratio(normalized_expected, normalized_actual), 2)
    status = FieldStatus.PASS if score >= FUZZY_THRESHOLD else FieldStatus.FAIL

    return _field_result(
        field=field,
        status=status,
        expected=expected,
        actual=actual,
        strategy=strategy,
        score=score,
        message=(
            "Fuzzy normalized values matched."
            if status == FieldStatus.PASS
            else "Fuzzy normalized values did not meet the threshold."
        ),
    )


def compare_brand_name(expected: str, actual: str | None) -> FieldResult:
    return _compare_fuzzy("brand_name", expected, actual)


def compare_product_class(expected: str, actual: str | None) -> FieldResult:
    return _compare_fuzzy("product_class", expected, actual)


def compare_producer_name(expected: str, actual: str | None) -> FieldResult:
    return _compare_fuzzy("producer_name", expected, actual)


_COUNTRY_SYNONYMS = {
    "usa": "united states",
    "u s a": "united states",
    "us": "united states",
    "u s": "united states",
    "united states": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "u k": "united kingdom",
    "united kingdom": "united kingdom",
    "great britain": "united kingdom",
}


def _canonical_country(value: str) -> str:
    normalized = _normalize_text(value)
    return _COUNTRY_SYNONYMS.get(normalized, normalized)


def compare_country(expected: str, actual: str | None) -> FieldResult:
    strategy = "country_synonym_exact"
    if actual is None:
        return _missing_actual_result(
            field="country_of_origin",
            expected=expected,
            strategy=strategy,
        )

    expected_country = _canonical_country(expected)
    actual_country = _canonical_country(actual)
    status = (
        FieldStatus.PASS
        if expected_country == actual_country
        else FieldStatus.FAIL
    )

    return _field_result(
        field="country_of_origin",
        status=status,
        expected=expected,
        actual=actual,
        strategy=strategy,
        score=None,
        message=(
            "Canonical country values matched."
            if status == FieldStatus.PASS
            else "Canonical country values did not match."
        ),
    )


_PERCENT_ABV_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:%|percent\b)",
    re.IGNORECASE,
)
_LABELED_ABV_AFTER_RE = re.compile(
    r"(?:abv|alc\.?\s*/?\s*vol\.?|alcohol\s+by\s+volume)\D{0,20}"
    r"(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LABELED_ABV_BEFORE_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*"
    r"(?:abv|alc\.?\s*/?\s*vol\.?|alcohol\s+by\s+volume)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)")


def _parse_abv(value: str | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)

    text = value.strip()
    for pattern in (_PERCENT_ABV_RE, _LABELED_ABV_AFTER_RE, _LABELED_ABV_BEFORE_RE):
        match = pattern.search(text)
        if match:
            return float(match.group(1))

    if "proof" in text.casefold():
        return None

    match = _NUMBER_RE.search(text)
    if match:
        return float(match.group(1))
    return None


def compare_abv(expected: str | float, actual: str | float | None) -> FieldResult:
    strategy = (
        "abv_numeric_normalize"
        f"+/-{ABV_TOLERANCE_PERCENTAGE_POINTS:g}_percentage_points"
    )
    expected_abv = _parse_abv(expected)
    actual_abv = _parse_abv(actual)
    if expected_abv is None or actual_abv is None:
        return _field_result(
            field="abv",
            status=FieldStatus.FAIL,
            expected=expected,
            actual=actual,
            strategy=strategy,
            score=None,
            message="ABV value could not be parsed.",
        )

    difference = abs(expected_abv - actual_abv)
    status = (
        FieldStatus.PASS
        if difference <= ABV_TOLERANCE_PERCENTAGE_POINTS + 1e-9
        else FieldStatus.FAIL
    )

    return _field_result(
        field="abv",
        status=status,
        expected=expected,
        actual=actual,
        strategy=strategy,
        score=round(difference, 3),
        message=(
            "Parsed ABV values matched within tolerance."
            if status == FieldStatus.PASS
            else "Parsed ABV values were outside tolerance."
        ),
    )


_UNIT_TO_ML = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "millilitre": 1.0,
    "millilitres": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "cl": 10.0,
    "centiliter": 10.0,
    "centiliters": 10.0,
    "centilitre": 10.0,
    "centilitres": 10.0,
}
_UNIT_PATTERN = "|".join(
    re.escape(unit) for unit in sorted(_UNIT_TO_ML, key=len, reverse=True)
)
_NET_CONTENTS_RE = re.compile(
    rf"(?<!\d)(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})\b",
    re.IGNORECASE,
)


def _parse_net_contents_ml(value: str | None) -> float | None:
    if value is None:
        return None
    match = _NET_CONTENTS_RE.search(value)
    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2).casefold()
    return amount * _UNIT_TO_ML[unit]


def compare_net_contents(expected: str, actual: str | None) -> FieldResult:
    strategy = f"net_contents_unit_normalize+/-{NET_CONTENTS_TOLERANCE_ML:g}_ml"
    expected_ml = _parse_net_contents_ml(expected)
    actual_ml = _parse_net_contents_ml(actual)
    if expected_ml is None or actual_ml is None:
        return _field_result(
            field="net_contents",
            status=FieldStatus.FAIL,
            expected=expected,
            actual=actual,
            strategy=strategy,
            score=None,
            message="Net contents value could not be parsed.",
        )

    difference = abs(expected_ml - actual_ml)
    status = (
        FieldStatus.PASS
        if difference <= NET_CONTENTS_TOLERANCE_ML + 1e-9
        else FieldStatus.FAIL
    )

    return _field_result(
        field="net_contents",
        status=status,
        expected=expected,
        actual=actual,
        strategy=strategy,
        score=round(difference, 3),
        message=(
            "Normalized net contents matched within tolerance."
            if status == FieldStatus.PASS
            else "Normalized net contents were outside tolerance."
        ),
    )


def compare_government_warning(expected: str, actual: str | None) -> FieldResult:
    strategy = "exact_case_sensitive_whitespace_normalized"
    if actual is None:
        return _missing_actual_result(
            field="government_warning",
            expected=expected,
            strategy=strategy,
        )

    status = (
        FieldStatus.PASS
        if _normalize_warning_layout(expected) == _normalize_warning_layout(actual)
        else FieldStatus.FAIL
    )
    return _field_result(
        field="government_warning",
        status=status,
        expected=expected,
        actual=actual,
        strategy=strategy,
        score=None,
        message=(
            "Government warning matched exactly."
            if status == FieldStatus.PASS
            else "Government warning did not match exactly."
        ),
    )


def _normalize_warning_layout(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def verify_label(
    application: ApplicationData,
    label: ExtractedLabel,
) -> VerificationResult:
    fields = [
        compare_brand_name(application.brand_name, label.brand_name),
        compare_product_class(application.product_class, label.product_class),
        compare_producer_name(application.producer_name, label.producer_name),
        compare_country(application.country_of_origin, label.country_of_origin),
        compare_abv(application.abv, label.abv),
        compare_net_contents(application.net_contents, label.net_contents),
        compare_government_warning(
            application.government_warning,
            label.government_warning,
        ),
    ]
    verdict = (
        VerificationVerdict.PASS
        if all(field.status == FieldStatus.PASS for field in fields)
        else VerificationVerdict.NEEDS_REVIEW
    )
    return VerificationResult(verdict=verdict, fields=fields)
