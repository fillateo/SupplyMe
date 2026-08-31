"""The deterministic engines: identity, quotes, conflicts, trust, scoring."""

from __future__ import annotations

import pytest

from app.domain import identity
from app.domain.conflicts import detect
from app.domain.models import (
    Conflict,
    Evidence,
    Fact,
    Provenance,
    Quote,
    ScoringWeights,
    SourceType,
    SupplyChainNode,
    Vendor,
)
from app.domain.quotes import ComponentVocabulary, comparable_set, normalize
from app.domain.scoring import apply_priorities, score_vendor
from app.domain.trust import profile


def vendor(**kw) -> Vendor:
    kw.setdefault("mission_id", "m")
    kw.setdefault("name", "PT Test")
    return Vendor(**kw)


def evidence(field: str, value, source_type: SourceType, url: str | None = None) -> Evidence:
    return Evidence(
        mission_id="m", vendor_id="v", claim=f"{field}={value}", field=field, value=value,
        source_type=source_type, source_url=url, evidence_excerpt="quoted text " * 8,
    )


# --------------------------------------------------------------------------
# Identity resolution
# --------------------------------------------------------------------------


class TestIdentity:
    def test_same_domain_merges(self):
        a = vendor(name="PT Kemasan Wangi", website="https://kw.example.com/")
        b = vendor(name="Kemasan Wangi Nusantara", domain="www.kw.example.com")
        assert identity.compare(a, b).is_same

    def test_same_phone_merges_across_formats(self):
        a = vendor(name="Alpha", phone="(310) 555-7788")
        b = vendor(name="Beta", phone="+1 310 555 7788")
        assert identity.compare(a, b).is_same

    def test_a_non_us_number_still_merges_across_its_own_formats(self):
        """The default market is the US; the matcher is not limited to it."""
        a = vendor(name="Alpha", phone="+62 21 5566 778")
        b = vendor(name="Beta", phone="62 21 5566 778")
        assert identity.compare(a, b).is_same

    def test_same_name_different_city_is_not_the_same_business(self):
        a = vendor(name="PT Botol Prima", city="Surabaya")
        b = vendor(name="PT Botol Prima", city="Tangerang")
        assert not identity.compare(a, b).is_same

    def test_different_place_ids_prove_different_businesses(self):
        a = vendor(name="PT Botol Prima", place_id="A")
        b = vendor(name="PT Botol Prima", place_id="B")
        assert not identity.compare(a, b).is_same

    def test_legal_form_noise_is_ignored(self):
        assert identity.normalize_name("PT Aroma Nusantara Tbk") == "aroma nusantara"

    def test_merge_keeps_the_better_sourced_fact(self):
        primary = vendor(name="A")
        primary.moq = Fact(value=1000, provenance=Provenance.PUBLICLY_LISTED, confidence=0.6)
        other = vendor(name="A", domain="a.example.com")
        other.moq = Fact(value=500, provenance=Provenance.DIRECT_QUOTE, confidence=0.9)
        merged = identity.merge(primary, other)
        assert merged.moq.value == 500
        assert merged.domain == "a.example.com"

    def test_merge_does_not_downgrade_a_known_fact_to_unknown(self):
        primary = vendor(name="A")
        primary.moq = Fact(value=500, provenance=Provenance.DIRECT_QUOTE, confidence=0.9)
        merged = identity.merge(primary, vendor(name="A"))
        assert merged.moq.value == 500

    def test_resolve_returns_the_candidate_when_nothing_matches(self):
        candidate = vendor(name="Totally New Co")
        resolved, match = identity.resolve(candidate, [vendor(name="Other", place_id="X")])
        assert match is None and resolved is candidate


# --------------------------------------------------------------------------
# Quote normalization
# --------------------------------------------------------------------------


def _nodes(*specs: tuple[str, str, list[str]]) -> list[SupplyChainNode]:
    return [
        SupplyChainNode(mission_id="m", key=key, name=name, aliases=aliases)
        for key, name, aliases in specs
    ]


#: A perfume packer's plan, as the supply-chain agent would emit it.
PERFUME = ComponentVocabulary.from_nodes(
    _nodes(
        ("bottle", "Glass bottle", ["botol", "flacon", "glass bottle"]),
        ("pump", "Atomizer pump", ["sprayer", "atomizer", "spray"]),
        ("cap", "Cap", ["tutup", "closure", "lid"]),
        ("label", "Label", ["stiker", "sticker"]),
    )
)

#: An entirely different industry, to prove the engine holds no vocabulary of
#: its own. Nothing about these words appears anywhere in app/.
POWER_BANK = ComponentVocabulary.from_nodes(
    _nodes(
        ("lithium_cell", "Lithium cell", ["cell", "18650", "battery cell"]),
        ("pcba", "Charge controller PCBA", ["pcb", "board", "pcba"]),
        ("enclosure", "Injection-moulded enclosure", ["housing", "shell", "casing"]),
    )
)

TRIO = ("bottle", "pump", "cap")


class TestQuotes:
    def test_bundle_and_itemized_compare_equal(self):
        bundled = Quote(
            mission_id="m", vendor_id="A", line_items={"set": 12000.0},
            bundle_covers=["botol", "sprayer", "tutup"],
        )
        itemized = Quote(
            mission_id="m", vendor_id="B",
            line_items={"Botol": 8000.0, "sprayer": 2500.0, "tutup": 1500.0},
        )
        comparable, _ = comparable_set([bundled, itemized], TRIO, vocabulary=PERFUME)
        assert {q.unit_price for q in comparable} == {12000.0}

    def test_a_partial_quote_is_not_comparable(self):
        partial = Quote(mission_id="m", vendor_id="C", line_items={"bottle": 7000.0})
        comparable, incomparable = comparable_set([partial], TRIO, vocabulary=PERFUME)
        assert not comparable
        assert incomparable[0].missing == ("pump", "cap")

    def test_no_price_is_invented_for_a_missing_component(self):
        result = normalize(
            Quote(mission_id="m", vendor_id="C", line_items={"bottle": 7000.0}),
            TRIO, vocabulary=PERFUME,
        )
        assert result.unit_price is None

    def test_currencies_are_never_converted(self):
        idr = Quote(mission_id="m", vendor_id="A", currency="IDR",
                    line_items={"bottle": 8000.0, "pump": 2500.0, "cap": 1500.0})
        usd = Quote(mission_id="m", vendor_id="B", currency="USD",
                    line_items={"bottle": 0.5, "pump": 0.2, "cap": 0.1})
        comparable, incomparable = comparable_set([idr, usd], TRIO, vocabulary=PERFUME)
        assert [q.vendor_id for q in comparable] == ["A"]
        assert "FX" in " ".join(incomparable[0].notes)

    def test_superseded_quotes_are_excluded(self):
        old = Quote(mission_id="m", vendor_id="A", line_items={"package": 9999.0},
                    superseded_by="q2")
        comparable, incomparable = comparable_set([old], TRIO, vocabulary=PERFUME)
        assert not comparable and not incomparable

    def test_bundle_still_needs_components_it_does_not_cover(self):
        bundled = Quote(
            mission_id="m", vendor_id="A", line_items={"package": 12000.0},
            bundle_covers=["bottle", "pump", "cap"],
        )
        result = normalize(bundled, ("bottle", "label"), vocabulary=PERFUME)
        assert result.unit_price is None and result.missing == ("label",)


class TestAPriceRungTheBuyerCannotReach:
    """Suppliers quote a ladder, and each reply becomes its own Quote.

    The demo turns on settling a MOQ disagreement: published 500, sales desk
    1,000, follow-up confirms 500 as a pilot at a higher unit price. Both replies
    leave a quote behind, and the scorer takes the cheapest — so the mission did
    the whole job of establishing what the buyer could have, then ranked the
    vendor on the price it had just been told it could not.
    """

    def _ladder(self):
        volume = Quote(id="qte_volume", mission_id="m", vendor_id="v",
                       quantity=1000, moq=1000, line_items={"botol": 8500.0})
        pilot = Quote(id="qte_pilot", mission_id="m", vendor_id="v",
                      quantity=500, moq=500, line_items={"botol": 11000.0})
        return volume, pilot

    def test_a_rung_above_the_order_quantity_is_not_comparable(self):
        volume, pilot = self._ladder()
        comparable, incomparable = comparable_set(
            [volume, pilot], ("bottle",), vocabulary=PERFUME, order_quantity=500
        )
        assert [q.quote_id for q in comparable] == ["qte_pilot"]
        assert [q.quote_id for q in incomparable] == ["qte_volume"]
        assert "not available" in " ".join(incomparable[0].notes)

    def test_the_reachable_rung_is_what_gets_priced(self):
        volume, pilot = self._ladder()
        comparable, _ = comparable_set(
            [volume, pilot], ("bottle",), vocabulary=PERFUME, order_quantity=500
        )
        assert comparable[0].unit_price == 11000.0, (
            "the vendor was scored on a price it only offers at a larger order"
        )

    def test_buying_the_larger_quantity_makes_the_cheaper_rung_available(self):
        volume, pilot = self._ladder()
        comparable, _ = comparable_set(
            [volume, pilot], ("bottle",), vocabulary=PERFUME, order_quantity=1000
        )
        assert comparable[0].quote_id == "qte_volume"
        assert comparable[0].unit_price == 8500.0

    def test_a_quote_that_names_no_quantity_is_still_comparable(self):
        """An unstated rung is not grounds to throw a price away."""
        unstated = Quote(mission_id="m", vendor_id="v", line_items={"botol": 9000.0})
        comparable, _ = comparable_set(
            [unstated], ("bottle",), vocabulary=PERFUME, order_quantity=500
        )
        assert comparable and comparable[0].unit_price == 9000.0

    def test_without_an_order_quantity_nothing_is_held_back(self):
        volume, pilot = self._ladder()
        comparable, _ = comparable_set([volume, pilot], ("bottle",), vocabulary=PERFUME)
        assert len(comparable) == 2


class TestQuotesAreVerticalAgnostic:
    """The engine holds no industry's vocabulary. The mission supplies it."""

    def test_another_industry_compares_bundle_against_itemized(self):
        wanted = ("lithium_cell", "pcba", "enclosure")
        bundled = Quote(
            mission_id="m", vendor_id="A", line_items={"kit": 41000.0},
            bundle_covers=["cell", "board", "housing"],
        )
        itemized = Quote(
            mission_id="m", vendor_id="B",
            line_items={"18650": 26000.0, "PCBA": 9000.0, "Shell": 6000.0},
        )
        comparable, incomparable = comparable_set(
            [bundled, itemized], wanted, vocabulary=POWER_BANK
        )
        assert not incomparable
        assert {q.unit_price for q in comparable} == {41000.0}

    def test_a_local_language_line_item_resolves_to_its_node(self):
        vocab = ComponentVocabulary.from_nodes(
            _nodes(("oak_panel", "Oak panel", ["papan kayu jati", "tabletop blank"]))
        )
        quote = Quote(mission_id="m", vendor_id="A", line_items={"Papan kayu jati": 480000.0})
        result = normalize(quote, ("oak_panel",), vocabulary=vocab)
        assert result.comparable and result.unit_price == 480000.0

    def test_an_unexplained_bundle_is_never_assumed_to_cover_anything(self):
        quote = Quote(mission_id="m", vendor_id="A", line_items={"set": 12000.0})
        result = normalize(quote, TRIO, vocabulary=PERFUME)
        assert not result.comparable
        assert result.missing == TRIO
        assert "without saying what it covers" in " ".join(result.notes)

    def test_a_bundle_covering_more_than_was_asked_says_so(self):
        quote = Quote(
            mission_id="m", vendor_id="A", line_items={"paket": 12000.0},
            bundle_covers=["bottle", "pump", "cap"],
        )
        result = normalize(quote, ("bottle",), vocabulary=PERFUME)
        assert result.comparable and result.extras == ("pump", "cap")
        assert "not asked for here" in " ".join(result.notes)

    def test_with_no_plan_a_component_still_stands_for_itself(self):
        quote = Quote(mission_id="m", vendor_id="A", line_items={"Widget": 5.0})
        result = normalize(quote, ("widget",))
        assert result.comparable and result.unit_price == 5.0

    def test_a_node_key_is_never_shadowed_by_another_nodes_alias(self):
        vocab = ComponentVocabulary.from_nodes(
            _nodes(
                ("cap", "Cap", []),
                ("closure_set", "Closure set", ["cap", "closure"]),
            )
        )
        assert vocab.canonical("cap") == "cap"
        assert vocab.canonical("closure") == "closure_set"


# --------------------------------------------------------------------------
# Conflict detection
# --------------------------------------------------------------------------


class TestConflicts:
    def test_website_and_email_moq_disagreement_is_detected(self):
        found = detect("moq", [
            evidence("moq", 500, SourceType.OFFICIAL_WEBSITE, "https://s.example.com"),
            evidence("moq", 1000, SourceType.SUPPLIER_EMAIL),
        ])
        assert found is not None
        assert found.preferred_value == 1000        # direct supplier statement wins
        assert found.action == "email"              # writing is the only way to ask
        assert "500" in found.question

    def test_small_numeric_variation_is_not_a_conflict(self):
        assert detect("moq", [
            evidence("moq", 500, SourceType.OFFICIAL_WEBSITE),
            evidence("moq", 505, SourceType.DIRECTORY),
        ]) is None

    def test_lead_times_tolerate_a_quoted_range(self):
        # "25-30 working days" on the site and 28 in the email agree.
        assert detect("lead_time_days", [
            evidence("lead_time_days", 25, SourceType.OFFICIAL_WEBSITE),
            evidence("lead_time_days", 28, SourceType.SUPPLIER_EMAIL),
        ]) is None

    def test_a_large_lead_time_gap_is_still_a_conflict(self):
        assert detect("lead_time_days", [
            evidence("lead_time_days", 21, SourceType.OFFICIAL_WEBSITE),
            evidence("lead_time_days", 60, SourceType.SUPPLIER_EMAIL),
        ]) is not None

    def test_a_single_source_cannot_conflict(self):
        assert detect("moq", [evidence("moq", 500, SourceType.OFFICIAL_WEBSITE)]) is None

    def test_published_only_disagreement_routes_to_email(self):
        found = detect("moq", [
            evidence("moq", 500, SourceType.OFFICIAL_WEBSITE, "https://a.example.com"),
            evidence("moq", 2000, SourceType.DIRECTORY, "https://b.example.com"),
        ])
        assert found is not None and found.action == "email"

    def test_a_disagreement_between_text_values_still_asks_a_question(self):
        """Evidence keeps values as the source wrote them, so an MOQ can be
        "500 pcs" rather than 500. Building the question used to take min()
        over only the numeric values — an empty sequence when both sides are
        text — which turned a detected conflict into a ValueError inside the
        handler and cost the vendor its branch."""
        found = detect("moq", [
            evidence("moq", "500 pcs", SourceType.OFFICIAL_WEBSITE),
            evidence("moq", "1.000 pcs", SourceType.SUPPLIER_EMAIL),
        ])
        assert found is not None
        assert found.question
        assert "500" in found.question and "1000" in found.question

    def test_a_disagreement_with_no_numeric_reading_gets_the_generic_question(self):
        found = detect("payment_terms", [
            evidence("payment_terms", "50% DP", SourceType.OFFICIAL_WEBSITE),
            evidence("payment_terms", "full prepayment", SourceType.SUPPLIER_EMAIL),
        ])
        assert found is not None
        assert "disagree on payment terms" in found.question


# --------------------------------------------------------------------------
# Trust and scoring
# --------------------------------------------------------------------------


class TestTrust:
    def test_every_dimension_carries_an_explanation(self):
        result = profile(vendor(website="https://a.example.com", email="a@a.example.com"), [])
        assert all(d.explanation for d in result.dimensions)

    def test_an_unknown_field_scores_zero_not_a_guess(self):
        assert profile(vendor(), []).get("pricing").score == 0.0

    def test_an_open_conflict_caps_the_dimension(self):
        subject = vendor()
        subject.moq = Fact(value=500, provenance=Provenance.DIRECT_QUOTE, confidence=0.95)
        clean = profile(subject, []).get("moq").score
        conflicted = profile(
            subject, [], (), [Conflict(mission_id="m", vendor_id="v", field="moq")]
        ).get("moq")
        assert conflicted.score < clean
        assert "disagree" in conflicted.explanation


class TestScoring:
    def _scored(self, **overrides):
        subject = vendor(
            website="https://a.example.com", email="a@a.example.com",
            country="Indonesia", city="Tangerang", node_keys=["bottle"],
            capabilities=["50ml bottles"],
        )
        subject.moq = Fact(value=overrides.pop("moq", 500),
                           provenance=Provenance.DIRECT_QUOTE, confidence=0.9)
        subject.lead_time_days = Fact(value=21, provenance=Provenance.DIRECT_QUOTE, confidence=0.9)
        return subject

    def test_score_is_the_sum_of_its_explained_parts(self):
        subject = self._scored()
        result = score_vendor(
            subject, weights=ScoringWeights(), trust=profile(subject, []),
            quantity=500, required_nodes=["bottle"], market="Indonesia",
        )
        total = sum(c.contribution for c in result.components) * 100
        assert result.total == pytest.approx(total, abs=0.01)
        assert all(c.explanation for c in result.components)

    def test_an_unpriced_vendor_scores_zero_on_price_and_says_why(self):
        subject = self._scored()
        result = score_vendor(subject, weights=ScoringWeights(), trust=profile(subject, []),
                              quantity=500)
        price = next(c for c in result.components if c.name == "price")
        assert price.raw == 0.0 and "no comparable quote" in price.explanation

    def test_a_far_too_large_moq_disqualifies_with_a_reason(self):
        subject = self._scored(moq=5000)
        result = score_vendor(subject, weights=ScoringWeights(), trust=profile(subject, []),
                              quantity=500)
        assert result.disqualified
        assert "good supplier at scale" in " ".join(result.rejection_reasons)

    def test_no_contact_route_disqualifies(self):
        subject = vendor(country="Indonesia")
        result = score_vendor(subject, weights=ScoringWeights(), trust=profile(subject, []),
                              quantity=500)
        assert result.disqualified

    def test_scoring_is_reproducible(self):
        subject = self._scored()
        args = dict(weights=ScoringWeights(), trust=profile(subject, []), quantity=500)
        assert score_vendor(subject, **args).total == score_vendor(subject, **args).total

    def test_priorities_move_weight_off_price(self):
        base = ScoringWeights().as_dict()
        shifted = apply_priorities(ScoringWeights(), ["I care more about quality than price"])
        assert shifted.as_dict()["price"] < base["price"]
        assert shifted.as_dict()["evidence"] > base["evidence"]

    def test_weights_always_normalize_to_one(self):
        shifted = apply_priorities(ScoringWeights(), ["cheap", "fast", "quality", "local"])
        assert sum(shifted.as_dict().values()) == pytest.approx(1.0)
