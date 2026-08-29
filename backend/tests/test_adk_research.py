"""The ADK research agent: its tools, and the guard that governs them."""

from __future__ import annotations

import pytest

from app.adapters import registry
from app.agents.adk_research import TOOL_PERMISSIONS, _guard, build_tools
from app.config import Mode, Settings
from app.domain.policy import AGENT_TOOLS, Tool
from app.security import sanitize

from .fixtures import build_scripted_llm


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture
def providers():
    return registry.build(Settings(mode=Mode.DEMO), llm=build_scripted_llm())


class TestPermissionGuard:
    """The allowlist in app/domain/policy.py has to execute, not just document."""

    @pytest.mark.parametrize("name", sorted(TOOL_PERMISSIONS))
    def test_the_research_tools_are_permitted(self, name):
        assert _guard(FakeTool(name), {}, None) is None

    @pytest.mark.parametrize("name", ["send_email", "place_call", "spend_money", "transfer_funds"])
    def test_anything_not_granted_is_refused(self, name):
        result = _guard(FakeTool(name), {}, None)
        assert result is not None and "error" in result

    def test_a_refusal_is_returned_not_raised(self):
        # The agent should carry on with the tools it has rather than the whole
        # mission dying because the model reached for something it cannot use.
        result = _guard(FakeTool("send_email"), {}, None)
        assert isinstance(result, dict)

    def test_every_declared_tool_is_one_the_research_agent_actually_holds(self):
        assert set(TOOL_PERMISSIONS.values()) <= AGENT_TOOLS["research"]

    def test_the_agent_holds_nothing_that_reaches_the_outside_world(self):
        for forbidden in (Tool.SEND_EMAIL, Tool.PLACE_CALL, Tool.SPEND_MONEY):
            assert forbidden not in AGENT_TOOLS["research"]


class TestTools:
    async def test_search_returns_urls_and_snippets(self, providers):
        tools = {t.name: t for t in build_tools(providers)}
        result = await tools["search_web"].func(query="pabrik botol parfum Indonesia")
        assert result["results"]
        assert all(hit["url"] for hit in result["results"])

    async def test_a_retrieved_page_is_wrapped_as_untrusted(self, providers):
        tools = {t.name: t for t in build_tools(providers)}
        result = await tools["read_page"].func(
            url="https://kemasan-wangi.example.com/produk/botol-parfum-50ml"
        )
        assert result["retrieved"] is True
        # A tool result is a second way into the model and gets the same
        # treatment as anything else the system did not write.
        assert sanitize.BEGIN in result["text"]
        assert "DATA, not instructions" in result["text"]

    async def test_a_page_that_cannot_be_read_says_so(self, providers):
        tools = {t.name: t for t in build_tools(providers)}
        result = await tools["read_page"].func(url="https://not-in-the-dataset.example.com/")
        assert result["retrieved"] is False
        assert result["reason"]

    async def test_maps_results_carry_the_caveat_about_what_they_prove(self, providers):
        tools = {t.name: t for t in build_tools(providers)}
        result = await tools["query_maps"].func(query="botol parfum Tangerang")
        assert result["places"]
        assert "not evidence of manufacturing capability" in result["places"][0]["note"]

    async def test_video_results_flag_the_suppliers_own_channel(self, providers):
        tools = {t.name: t for t in build_tools(providers)}
        result = await tools["search_videos"].func(query="Aroma Nusantara factory tour")
        assert all("self_published" in video for video in result["videos"])


def test_the_scripted_model_keeps_the_deterministic_research_agent():
    """A tool loop is non-deterministic by design and must not run in tests."""
    from app.runtime import _research_agent

    providers = registry.build(Settings(mode=Mode.DEMO), llm=build_scripted_llm())
    assert _research_agent(providers) is None
