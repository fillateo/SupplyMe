"""Spend guards. These protect a finite credit balance, so they are not advisory."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.cost import (
    PRICING,
    UNKNOWN_PRICE,
    BudgetExceeded,
    CostMeter,
    Usage,
    price_for,
    usd_for,
)


class TestPricing:
    def test_a_versioned_model_prices_as_its_family(self):
        assert price_for("gemini-2.5-flash-002") == PRICING["gemini-2.5-flash"]

    def test_longest_prefix_wins(self):
        # flash-lite must not price as flash.
        assert price_for("gemini-2.5-flash-lite") == PRICING["gemini-2.5-flash-lite"]
        assert price_for("gemini-2.5-flash-lite") != PRICING["gemini-2.5-flash"]

    def test_an_unknown_model_over_reports_rather_than_under(self):
        # Under-reporting an unknown model would let it slip past the cap.
        unknown = price_for("gemini-99-experimental")
        assert unknown == UNKNOWN_PRICE
        assert unknown[0] >= max(p[0] for p in PRICING.values())
        assert unknown[1] >= max(p[1] for p in PRICING.values())

    def test_cost_scales_with_tokens(self):
        assert usd_for("gemini-2.5-flash", 2000, 400) == pytest.approx(
            2 * usd_for("gemini-2.5-flash", 1000, 200)
        )

    def test_zero_tokens_costs_nothing(self):
        assert usd_for("gemini-2.5-pro", 0, 0) == 0.0


class TestMeter:
    def test_usage_is_attributed_per_mission(self):
        meter = CostMeter()
        meter.record("a", "gemini-2.5-flash", 1000, 100)
        meter.record("b", "gemini-2.5-flash", 5000, 500)
        assert meter.usage("a").calls == 1
        assert meter.usage("b").input_tokens == 5000
        assert meter.total.calls == 2

    def test_an_unseen_mission_has_spent_nothing(self):
        assert CostMeter().usage("never-run").calls == 0

    def test_the_call_cap_stops_a_mission(self):
        meter = CostMeter(max_calls_per_mission=2)
        meter.record("m", "gemini-2.5-flash", 100, 10)
        meter.check("m")                      # still within
        meter.record("m", "gemini-2.5-flash", 100, 10)
        with pytest.raises(BudgetExceeded, match="model-call cap"):
            meter.check("m")

    def test_the_spend_cap_stops_a_mission(self):
        meter = CostMeter(max_calls_per_mission=10_000, max_usd_per_mission=0.001)
        meter.record("m", "gemini-2.5-pro", 100_000, 10_000)
        with pytest.raises(BudgetExceeded, match=r"\$0\.00 cap"):
            meter.check("m")

    def test_one_mission_hitting_its_cap_does_not_stop_another(self):
        meter = CostMeter(max_calls_per_mission=1)
        meter.record("a", "gemini-2.5-flash", 100, 10)
        with pytest.raises(BudgetExceeded):
            meter.check("a")
        meter.check("b")                      # unaffected

    def test_unattributed_calls_are_never_capped_but_are_counted(self):
        # A call with no mission (model resolution, health probes) must not be
        # able to fail a mission, but must still show up in the total.
        meter = CostMeter(max_calls_per_mission=1)
        meter.record("", "gemini-2.5-flash", 100, 10)
        meter.check("")
        assert meter.total.calls == 1

    def test_totals_survive_a_restart_when_seeded(self):
        meter = CostMeter(max_calls_per_mission=5)
        meter.seed("m", Usage(calls=5, input_tokens=1, output_tokens=1, usd=0.01))
        with pytest.raises(BudgetExceeded):
            meter.check("m")


class TestDefaults:
    """The shipped defaults have to be safe on a small credit balance."""

    def test_a_single_mission_cannot_spend_much(self):
        settings = Settings()
        assert settings.max_usd_per_mission <= 1.0
        assert settings.max_model_calls_per_mission <= 200

    def test_the_research_loop_is_bounded_far_below_the_adk_default(self):
        from google.adk.agents.run_config import RunConfig

        assert Settings().max_research_llm_calls < RunConfig().max_llm_calls / 10

    def test_outreach_and_calls_are_capped(self):
        settings = Settings()
        assert settings.max_outreach_per_mission <= 20
        assert settings.max_calls_per_mission <= 5
