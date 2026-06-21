from backend.app.comparison import (
    compare_abv,
    compare_brand_name,
    compare_country,
    compare_government_warning,
    compare_net_contents,
    compare_producer_name,
    compare_product_class,
    verify_label,
)
from backend.app.models import (
    ApplicationData,
    ExtractedLabel,
    FieldStatus,
    VerificationVerdict,
)


WARNING = "GOVERNMENT WARNING: THIS IS THE EXACT WARNING TEXT"


def passing_application() -> ApplicationData:
    return ApplicationData(
        brand_name="Sunset Ridge",
        product_class="Cabernet Sauvignon",
        producer_name="North Valley Estate Winery LLC",
        country_of_origin="United States",
        abv="45%",
        net_contents="750 mL",
        government_warning=WARNING,
    )


def passing_label() -> ExtractedLabel:
    return ExtractedLabel(
        brand_name="SUNSET RIDGE",
        product_class="Sauvignon Cabernet",
        producer_name="North Valley Estate Winery, LLC",
        country_of_origin="USA",
        abv="45% Alc./Vol. (90 Proof)",
        net_contents="750ml",
        government_warning=WARNING,
    )


def assert_pass(result) -> None:
    assert result.status == FieldStatus.PASS


def assert_fail(result) -> None:
    assert result.status == FieldStatus.FAIL


def test_brand_case_only_difference_passes() -> None:
    result = compare_brand_name("Sunset Ridge", "SUNSET RIDGE")

    assert_pass(result)
    assert result.score == 100.0


def test_fuzzy_fields_handle_spacing_punctuation_and_word_order() -> None:
    product_class = compare_product_class("Cabernet Sauvignon", "Sauvignon Cabernet")
    producer = compare_producer_name(
        "North Valley Estate Winery LLC",
        " North Valley Estate Winery, LLC ",
    )

    assert_pass(product_class)
    assert product_class.score == 100.0
    assert_pass(producer)
    assert producer.score == 100.0


def test_fuzzy_field_clearly_different_fails() -> None:
    result = compare_brand_name("Sunset Ridge", "Harbor Point")

    assert_fail(result)
    assert result.actual == "Harbor Point"
    assert result.score is not None
    assert result.score < 90


def test_country_usa_matches_united_states() -> None:
    result = compare_country("United States", "USA")

    assert_pass(result)


def test_country_synonym_with_punctuation_matches() -> None:
    result = compare_country("United States of America", "U.S.A.")

    assert_pass(result)


def test_country_product_of_prefix_matches_country() -> None:
    result = compare_country("USA", "Product of USA")

    assert_pass(result)


def test_country_different_country_fails() -> None:
    result = compare_country("United States", "Canada")

    assert_fail(result)
    assert result.actual == "Canada"


def test_abv_ignores_proof_when_percent_is_present() -> None:
    result = compare_abv("45%", "45% Alc./Vol. (90 Proof)")

    assert_pass(result)


def test_abv_normalizes_percent_text_and_numeric_values() -> None:
    result = compare_abv(13.5, "Alc. 13.5% by Vol.")

    assert_pass(result)


def test_abv_value_inside_tolerance_passes() -> None:
    result = compare_abv("13.5%", "13.6%")

    assert_pass(result)


def test_abv_value_outside_tolerance_fails() -> None:
    result = compare_abv("13.5%", "14.0%")

    assert_fail(result)
    assert result.actual == "14.0%"


def test_abv_proof_without_percent_does_not_match_abv() -> None:
    result = compare_abv("45%", "90 Proof")

    assert_fail(result)


def test_abv_unparseable_value_fails() -> None:
    result = compare_abv("13.5%", "unknown")

    assert_fail(result)
    assert result.actual == "unknown"


def test_net_contents_allows_no_space_between_amount_and_unit() -> None:
    result = compare_net_contents("750 mL", "750ml")

    assert_pass(result)


def test_net_contents_normalizes_liters_and_centiliters() -> None:
    liters = compare_net_contents("750 mL", "0.75 L")
    centiliters = compare_net_contents("750 mL", "75 cl")

    assert_pass(liters)
    assert_pass(centiliters)


def test_net_contents_different_volume_fails() -> None:
    result = compare_net_contents("750 mL", "700 mL")

    assert_fail(result)
    assert result.actual == "700 mL"


def test_net_contents_unparseable_value_fails() -> None:
    result = compare_net_contents("750 mL", "one bottle")

    assert_fail(result)
    assert result.actual == "one bottle"


def test_government_warning_title_case_fails() -> None:
    result = compare_government_warning(
        WARNING,
        "Government Warning: This Is The Exact Warning Text",
    )

    assert_fail(result)


def test_government_warning_missing_colon_fails() -> None:
    result = compare_government_warning(
        WARNING,
        "GOVERNMENT WARNING THIS IS THE EXACT WARNING TEXT",
    )

    assert_fail(result)


def test_government_warning_missing_value_fails() -> None:
    result = compare_government_warning(WARNING, None)

    assert_fail(result)
    assert result.actual is None


def test_government_warning_exact_all_caps_passes() -> None:
    result = compare_government_warning(WARNING, WARNING)

    assert_pass(result)


def test_government_warning_line_breaks_and_indentation_pass() -> None:
    actual = "  GOVERNMENT WARNING:\n    THIS IS THE EXACT\n  WARNING TEXT  "

    result = compare_government_warning(WARNING, actual)

    assert_pass(result)
    assert result.actual == actual


def test_government_warning_failure_preserves_extracted_text() -> None:
    misread_warning = "GOVERNMENT WARNlNG: THIS IS THE EXACT WARNING TEXT"

    result = compare_government_warning(WARNING, misread_warning)

    assert_fail(result)
    assert result.actual == misread_warning


def test_verify_label_all_fields_pass() -> None:
    result = verify_label(passing_application(), passing_label())

    assert result.verdict == VerificationVerdict.PASS
    assert len(result.fields) == 7
    assert all(field.status == FieldStatus.PASS for field in result.fields)


def test_verify_label_any_failure_needs_review() -> None:
    label = passing_label().model_copy(update={"government_warning": WARNING.lower()})

    result = verify_label(passing_application(), label)

    assert result.verdict == VerificationVerdict.NEEDS_REVIEW
    assert any(
        field.field == "government_warning" and field.status == FieldStatus.FAIL
        for field in result.fields
    )
