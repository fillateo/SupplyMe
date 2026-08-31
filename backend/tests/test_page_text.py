"""Turning a real web page into something the agents can read.

Every test here is a shape that appears on essentially every page on the web and
on none of the demo pages, which are plain text. That gap hid a total failure:
`<head>` contains `<meta>` and `<link>`, which never close, so `</head>` never
popped `head` off the tag stack and the parser treated the entire body as being
inside the head. Live research read empty documents from every site it opened,
and every supplier was then rejected for having no contact details.
"""

from __future__ import annotations

from app.adapters.google_providers import _TextExtractor

REAL_PAGE = """<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width">
  <link rel="stylesheet" href="/style.css">
  <title>Kontak — PT Contoh Kemasan</title>
</head>
<body>
  <h1>Hubungi Kami</h1>
  <p>Telp: 021-5566 7788<br>Email: <a href="mailto:sales@contoh.co.id">Email us</a></p>
  <p>Minimum order 500 pcs per desain.</p>
  <script>var tracking = "noreply@analytics.example";</script>
  <style>.a { color: red; }</style>
</body>
</html>"""


def extract(html: str) -> _TextExtractor:
    parser = _TextExtractor()
    parser.feed(html)
    return parser


class TestReadingAPage:
    def test_the_body_of_a_normal_page_is_not_empty(self):
        assert "Hubungi Kami" in extract(REAL_PAGE).text

    def test_void_elements_in_the_head_do_not_swallow_the_document(self):
        """The regression: <meta> and <link> never close."""
        text = extract(REAL_PAGE).text
        assert "Minimum order 500 pcs per desain." in text

    def test_the_title_is_read(self):
        assert extract(REAL_PAGE).title == "Kontak — PT Contoh Kemasan"

    def test_script_and_style_contents_are_not_text(self):
        text = extract(REAL_PAGE).text
        assert "noreply@analytics.example" not in text
        assert "color: red" not in text

    def test_an_address_hidden_in_a_mailto_is_recovered(self):
        """Supplier sites label the link "Email us" and put the address in href."""
        assert "sales@contoh.co.id" in extract(REAL_PAGE).text

    def test_a_phone_number_in_a_tel_link_is_recovered(self):
        html = '<html><body><a href="tel:+622155667788">Call</a></body></html>'
        assert "+622155667788" in extract(html).text

    def test_a_self_closing_break_still_separates_lines(self):
        html = "<html><body><p>Telp: 021 1234 5678<br/>Fax: 021 1234 5679</p></body></html>"
        text = extract(html).text
        assert "021 1234 5678" in text and "021 1234 5679" in text

    def test_an_unclosed_paragraph_does_not_strand_the_rest_of_the_page(self):
        html = "<html><body><p>first<div>second</div><p>third</body></html>"
        text = extract(html).text
        assert "first" in text and "second" in text and "third" in text

    def test_a_mailto_inside_a_script_is_not_taken(self):
        html = '<html><body><script><a href="mailto:bad@evil.example">x</a></script>ok</body></html>'
        assert "bad@evil.example" not in extract(html).text


class TestSearchResultsCarryRealUrls:
    """Grounding hands back links to Google's redirector, not to the page.

    Every downstream judgement is made on a URL — is this the supplier's own
    site, is this source independent of them, which domain does this evidence
    cite — and all of them are meaningless against a redirect. A live mission
    discovered eight suppliers, recorded a website for none of them, and
    rejected all eight for having no contact route, because every URL it held
    pointed at `vertexaisearch.cloud.google.com`.
    """

    async def test_a_redirect_is_resolved_to_where_it_points(self, monkeypatch):

        from app.adapters.google_providers import (
            GROUNDING_REDIRECT_HOST,
            GoogleSearchProvider,
        )
        from app.config import Settings
        from app.ports.base import SearchHit

        provider = GoogleSearchProvider(Settings())
        real = "https://papaso.co.id/kontak"

        class _Response:
            url = real

        async def head(url, **kwargs):
            assert GROUNDING_REDIRECT_HOST in url
            return _Response()

        monkeypatch.setattr(provider._client, "head", head)
        hits = await provider._resolve_redirects(
            [SearchHit(title="Papaso", url=f"https://{GROUNDING_REDIRECT_HOST}/x/AUZ", snippet="s")]
        )
        assert hits[0].url == real
        assert hits[0].title == "Papaso", "resolving a URL must not lose the rest of the hit"

    async def test_an_ordinary_url_is_left_alone(self, monkeypatch):
        from app.adapters.google_providers import GoogleSearchProvider
        from app.config import Settings
        from app.ports.base import SearchHit

        provider = GoogleSearchProvider(Settings())

        async def head(url, **kwargs):
            raise AssertionError("a direct URL should never be resolved")

        monkeypatch.setattr(provider._client, "head", head)
        hits = await provider._resolve_redirects(
            [SearchHit(title="t", url="https://papaso.co.id/", snippet="s")]
        )
        assert hits[0].url == "https://papaso.co.id/"

    async def test_a_redirector_that_hangs_costs_one_url_not_the_search(self, monkeypatch):
        from app.adapters.google_providers import (
            GROUNDING_REDIRECT_HOST,
            GoogleSearchProvider,
        )
        from app.config import Settings
        from app.ports.base import SearchHit

        provider = GoogleSearchProvider(Settings())
        redirect = f"https://{GROUNDING_REDIRECT_HOST}/x/AUZ"

        async def head(url, **kwargs):
            raise TimeoutError("redirector is slow")

        monkeypatch.setattr(provider._client, "head", head)
        hits = await provider._resolve_redirects(
            [SearchHit(title="t", url=redirect, snippet="s"),
             SearchHit(title="u", url="https://direct.example/", snippet="s")]
        )
        assert len(hits) == 2, "a failed resolution dropped a search result"
        assert hits[0].url == redirect

class TestGroundedSearchIsBilledAndGated:
    """Search is a Gemini call, and on the default configuration it is most of them.

    With no Programmable Search engine — which is what the deployment runs — every
    web search goes through Gemini with search grounding. That call sat outside the
    throttle, so a mission's fan-out opened a dozen at once and Vertex answered 429
    to most of it; and outside the meter, so the spend a mission reported excluded
    the majority of what it spent.
    """

    def _provider(self, monkeypatch, meter, *, gate: int = 1):
        from app.adapters.gemini_llm import configure_throttle
        from app.adapters.google_providers import GoogleSearchProvider
        from app.config import Settings

        settings = Settings(project_id="p", max_concurrent_model_calls=gate)
        configure_throttle(settings)

        class _Usage:
            prompt_token_count = 4000
            candidates_token_count = 120
            thoughts_token_count = 30

        class _Web:
            title, uri = "Papaso", "https://papaso.co.id/"

        class _Chunk:
            web = _Web()

        class _Meta:
            grounding_chunks = [_Chunk()]

        class _Candidate:
            grounding_metadata = _Meta()

        class _Response:
            usage_metadata = _Usage()
            candidates = [_Candidate()]
            text = "found one supplier"

        class _Models:
            async def generate_content(self, **kwargs):
                return _Response()

        class _Client:
            class aio:
                models = _Models()

        async def _resolve(_settings, prefer_fast=False):
            return "gemini-3.5-flash"

        # `_grounded` imports these from gemini_llm at call time.
        monkeypatch.setattr("app.adapters.gemini_llm._client", lambda _s: _Client())
        monkeypatch.setattr("app.adapters.gemini_llm.resolve_model", _resolve)
        return GoogleSearchProvider(settings, meter=meter)

    async def test_a_grounded_search_is_recorded_against_the_mission(self, monkeypatch):
        from app.adapters.gemini_llm import current_mission
        from app.domain.cost import CostMeter

        meter = CostMeter()
        provider = self._provider(monkeypatch, meter)
        token = current_mission.set("msn_probe")
        try:
            hits = await provider.search("pabrik botol parfum", limit=5)
        finally:
            current_mission.reset(token)

        assert [h.url for h in hits] == ["https://papaso.co.id/"]
        usage = meter.usage("msn_probe")
        assert usage.calls == 1, "a grounded search was not counted as a model call"
        assert usage.input_tokens == 4000
        # Thinking bills as output and must not be dropped.
        assert usage.output_tokens == 150
        assert usage.usd > 0

    async def test_the_mission_comes_from_the_context_not_the_caller(self, monkeypatch):
        """The Search port has no mission to pass down; the orchestrator sets one."""
        from app.domain.cost import CostMeter

        meter = CostMeter()
        provider = self._provider(monkeypatch, meter)
        await provider.search("no mission set")
        # No mission on the context: booked to "unattributed" so it can never fail
        # somebody else's mission, but still counted in the process total.
        assert meter.usage("unattributed").calls == 1
        assert meter.total.calls == 1

    async def test_grounded_searches_cannot_outrun_the_process_wide_gate(self, monkeypatch):
        import asyncio

        from app.domain.cost import CostMeter

        peak = {"now": 0, "max": 0}
        provider = self._provider(monkeypatch, CostMeter(), gate=2)

        async def counted(**kwargs):
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            try:
                await asyncio.sleep(0.01)
                return _Empty()
            finally:
                peak["now"] -= 1

        class _Empty:
            usage_metadata = None
            candidates = []
            text = ""

        monkeypatch.setattr(
            "app.adapters.gemini_llm._client",
            lambda _s: type("C", (), {"aio": type("A", (), {"models": type("M", (), {"generate_content": staticmethod(counted)})()})()})(),
        )
        await asyncio.gather(*[provider.search(f"q{i}") for i in range(8)])
        assert peak["max"] <= 2, f"{peak['max']} grounded searches ran at once through a gate of 2"
        assert peak["max"] > 1, "the gate serialized everything instead of bounding it"


class TestARedirectCannotWalkPastTheAddressCheck:
    """`read_page` opens whatever URL the tool loop chose, steered by a page an
    attacker may control. The host is checked before the request — but redirects
    are followed, so the host that answers need not be the host that was checked.
    """

    def _provider(self, monkeypatch):
        from app.adapters import google_providers as gp
        from app.config import Settings

        provider = gp.GoogleSearchProvider(Settings())
        provider._robots["https://redirector.example.com"] = None   # no robots.txt

        # Only the metadata address is internal. Without this the outbound host
        # fails to resolve and is refused for that reason instead, which would
        # let the redirect assertion pass without the redirect being checked.
        monkeypatch.setattr(
            gp, "_resolves_to_internal_address", lambda host: host.startswith("169.254.")
        )
        return provider

    def _answer(self, monkeypatch, provider, final_url: str, body: str):
        class _Response:
            status_code = 200
            url = final_url
            content = body.encode()
            text = body

        async def get(url, **kwargs):
            return _Response()

        monkeypatch.setattr(provider._client, "get", get)

    async def test_a_redirect_to_an_internal_address_is_blocked(self, monkeypatch):
        provider = self._provider(monkeypatch)
        self._answer(
            monkeypatch, provider,
            "http://169.254.169.254/computeMetadata/v1/", "token=secret",
        )
        page = await provider.fetch("https://redirector.example.com/look-here")
        assert page.fetched is False
        assert "internal" in (page.blocked_reason or "")
        assert "secret" not in page.text

    async def test_an_ordinary_redirect_is_still_followed_and_cited(self, monkeypatch):
        provider = self._provider(monkeypatch)
        self._answer(
            monkeypatch, provider, "https://papaso.co.id/kontak",
            "<html><body>Email: sales@papaso.co.id</body></html>",
        )
        page = await provider.fetch("https://redirector.example.com/look-here")
        assert page.fetched is True
        assert page.url == "https://papaso.co.id/kontak", (
            "the URL that answered is what the evidence should cite"
        )
        assert "sales@papaso.co.id" in page.text
