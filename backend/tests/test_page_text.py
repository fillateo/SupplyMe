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
