"""Evidence classification: what a claim is worth, given its sources."""

from __future__ import annotations

from app.domain.evidence import (
    classify_brand_relationship,
    confidence_for,
    dedupe,
    provenance_for,
    score_evidence,
    strength_for,
)
from app.domain.models import (
    BrandEvidenceClass,
    Evidence,
    EvidenceStrength,
    Provenance,
    RelationshipType,
    SourceType,
)

LONG = "x" * 80


def make(source_type: SourceType, url: str | None = None, excerpt: str = LONG, **kw) -> Evidence:
    return Evidence(
        mission_id="m", vendor_id="v", claim=kw.pop("claim", "a claim"),
        source_type=source_type, source_url=url, evidence_excerpt=excerpt,
        confidence=score_evidence(source_type, excerpt), **kw,
    )


class TestStrength:
    def test_official_site_with_a_quote_is_strong(self):
        assert strength_for(SourceType.OFFICIAL_WEBSITE, LONG) is EvidenceStrength.STRONG

    def test_a_source_with_no_excerpt_is_never_strong(self):
        # No excerpt means nothing was actually read from the page.
        assert strength_for(SourceType.OFFICIAL_WEBSITE, "") is EvidenceStrength.WEAK
        assert strength_for(SourceType.SEARCH_RESULT, "") is EvidenceStrength.NONE

    def test_search_results_stay_weak_even_when_quoted(self):
        assert strength_for(SourceType.SEARCH_RESULT, LONG) is EvidenceStrength.WEAK

    def test_model_downgrades_a_strong_claim_with_no_excerpt(self):
        record = Evidence(
            mission_id="m", claim="c", source_type=SourceType.OFFICIAL_WEBSITE,
            evidence_strength=EvidenceStrength.STRONG, evidence_excerpt="",
        )
        assert record.evidence_strength is EvidenceStrength.MODERATE


class TestProvenance:
    def test_supplier_email_is_a_direct_quote(self):
        assert provenance_for([make(SourceType.SUPPLIER_EMAIL)]) is Provenance.DIRECT_QUOTE

    def test_two_independent_domains_verify(self):
        items = [
            make(SourceType.NEWS, "https://a.example.com/1"),
            make(SourceType.INDUSTRY_PUBLICATION, "https://b.example.com/2"),
        ]
        assert provenance_for(items) is Provenance.VERIFIED

    def test_the_suppliers_own_site_is_only_publicly_listed(self):
        assert (
            provenance_for([make(SourceType.OFFICIAL_WEBSITE, "https://s.example.com")])
            is Provenance.PUBLICLY_LISTED
        )

    def test_no_evidence_is_unknown_not_a_default(self):
        assert provenance_for([]) is Provenance.UNKNOWN


class TestConfidence:
    def test_corroboration_raises_confidence(self):
        one = confidence_for([make(SourceType.NEWS, "https://a.example.com")])
        two = confidence_for(
            [make(SourceType.NEWS, "https://a.example.com"),
             make(SourceType.NEWS, "https://b.example.com")]
        )
        assert two > one

    def test_confidence_never_reaches_certainty(self):
        many = [make(SourceType.DIRECTORY, f"https://d{i}.example.com") for i in range(20)]
        assert confidence_for(many) < 1.0

    def test_no_evidence_is_zero(self):
        assert confidence_for([]) == 0.0


class TestBrandRelationship:
    """The product's core discipline: a supplier's word is not confirmation."""

    def test_supplier_own_site_is_supplier_reported(self):
        classification, relationship, confidence, independent = classify_brand_relationship(
            [make(SourceType.OFFICIAL_WEBSITE, "https://supplier.example.com/clients")]
        )
        assert classification is BrandEvidenceClass.SUPPLIER_REPORTED
        assert relationship is RelationshipType.SUPPLIER_CLAIMED
        assert independent == 0
        assert confidence <= 0.45

    def test_the_brands_own_site_verifies(self):
        classification, relationship, confidence, _ = classify_brand_relationship(
            [make(SourceType.BRAND_WEBSITE, "https://brand.example.com/partners")]
        )
        assert classification is BrandEvidenceClass.VERIFIED
        assert relationship is RelationshipType.BRAND_CONFIRMED
        assert confidence >= 0.9

    def test_two_independent_publications_are_strong_evidence(self):
        classification, _, _, independent = classify_brand_relationship(
            [make(SourceType.NEWS, "https://news.example.com/a"),
             make(SourceType.INDUSTRY_PUBLICATION, "https://trade.example.com/b")]
        )
        assert classification is BrandEvidenceClass.STRONG_EVIDENCE
        assert independent == 2

    def test_nothing_found_says_so(self):
        classification, _, confidence, _ = classify_brand_relationship([])
        assert classification is BrandEvidenceClass.NO_PUBLIC_EVIDENCE
        assert confidence == 0.0


def test_dedupe_drops_the_same_claim_from_the_same_domain():
    items = [
        make(SourceType.NEWS, "https://a.example.com/1", claim="same"),
        make(SourceType.NEWS, "https://www.a.example.com/2", claim="same"),
        make(SourceType.NEWS, "https://b.example.com/3", claim="same"),
    ]
    assert len(dedupe(items)) == 2
