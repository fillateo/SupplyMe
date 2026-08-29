"""Reading numbers out of real supplier and model output."""

from __future__ import annotations

import pytest

from app.domain.conflicts import detect
from app.domain.models import Evidence, SourceType
from app.domain.numbers import as_number, normalize_field, parse_decimal


class TestParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("8.500", 8500.0),      # Indonesian thousands separator
            ("8,500", 8500.0),      # English thousands separator
            ("8.5", 8.5),           # a genuine decimal
            ("12.345,67", 12345.67),
            ("1,234.56", 1234.56),
            ("1.000.000", 1_000_000.0),
        ],
    )
    def test_both_thousands_conventions(self, text, expected):
        assert parse_decimal(text) == expected

    @pytest.mark.parametrize(
        "value,unit,expected",
        [
            (21, "days", 21.0),
            ("21", "days", 21.0),
            ("21 hari kerja", "days", 21.0),
            ("10-14", "days", 14.0),          # a range plans to its upper bound
            ("3-4 weeks", "days", 28.0),
            ("2 months", "days", 60.0),
            ("Rp 8.500", "", 8500.0),
            ("minimum 500 pcs", "", 500.0),
        ],
    )
    def test_values_suppliers_actually_write(self, value, unit, expected):
        assert as_number(value, unit=unit) == expected

    @pytest.mark.parametrize("value", [None, "", "unknown", "call us", "TBD", True, False, {}])
    def test_a_non_number_is_none_not_a_guess(self, value):
        assert as_number(value) is None

    def test_a_range_takes_the_conservative_end(self):
        # Planning a launch against the optimistic end of a range is a slipped
        # schedule waiting to happen.
        assert as_number("10-14", unit="days") == 14.0
        assert as_number("500-1000") == 1000.0

    def test_text_fields_pass_through_untouched(self):
        assert normalize_field("customization", "hot stamping") == "hot stamping"
        assert normalize_field("payment_terms", "50% DP") == "50% DP"

    def test_numeric_fields_are_coerced(self):
        assert normalize_field("lead_time_days", "10-14") == 14.0
        assert normalize_field("moq", "1.000 pcs") == 1000.0


class TestComparisonUsesNumbers:
    def test_a_number_written_as_text_agrees_with_the_same_number(self):
        items = [
            Evidence(mission_id="m", claim="c", field="moq", value="500 pcs",
                     source_type=SourceType.OFFICIAL_WEBSITE, evidence_excerpt="x" * 70),
            Evidence(mission_id="m", claim="c", field="moq", value=500,
                     source_type=SourceType.SUPPLIER_EMAIL, evidence_excerpt="x" * 70),
        ]
        assert detect("moq", items) is None

    def test_a_genuine_disagreement_still_surfaces(self):
        items = [
            Evidence(mission_id="m", claim="c", field="moq", value="500 pcs",
                     source_type=SourceType.OFFICIAL_WEBSITE, evidence_excerpt="x" * 70),
            Evidence(mission_id="m", claim="c", field="moq", value=1000,
                     source_type=SourceType.SUPPLIER_EMAIL, evidence_excerpt="x" * 70),
        ]
        assert detect("moq", items) is not None
