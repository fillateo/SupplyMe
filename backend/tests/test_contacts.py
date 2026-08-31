"""Reading a contact route off a supplier's page.

Written against what a US manufacturer's site actually looks like: a footer with
three addresses, one belonging to the agency that built the site; a phone number
two lines from a minimum-order quantity; a `/contact` page no search result links
to. The live failure this closes was every discovered manufacturer being
rejected for "no email or phone found", which ends a mission before it can ask
anybody anything.
"""

from __future__ import annotations

import pytest

from app.domain.contacts import candidate_urls, emails_in, find_in_page, phones_in

FOOTER = """
Vessel Craft Packaging Inc.
1420 Industrial Parkway, Bell Gardens, CA 90201

Phone: +1 310 555 7788
Email: sales@vesselcraft.com

Minimum order: 500 units per design. Capacity 40,000 units per month.
Website by Studio Eight — hello@studioeight.io
"""


class TestFindingAnAddress:
    def test_an_address_in_a_footer_is_found(self):
        assert "sales@vesselcraft.com" in emails_in(FOOTER)

    def test_the_suppliers_own_domain_outranks_the_agency_that_built_the_site(self):
        assert emails_in(FOOTER, prefer_domain="vesselcraft.com")[0] == (
            "sales@vesselcraft.com"
        )

    def test_the_sales_desk_outranks_the_switchboard(self):
        text = "info@factory.com | sales@factory.com | careers@factory.com"
        assert emails_in(text, prefer_domain="factory.com")[0] == "sales@factory.com"

    def test_a_request_for_quotation_desk_outranks_even_sales(self):
        """A US manufacturer publishing an RFQ address is naming where one is read."""
        text = "sales@factory.com | rfq@factory.com | info@factory.com"
        assert emails_in(text, prefer_domain="factory.com")[0] == "rfq@factory.com"

    def test_a_www_prefix_does_not_hide_the_domain_match(self):
        text = "cs@vendor.com and someone@other.example"
        assert emails_in(text, prefer_domain="www.vendor.com")[0] == "cs@vendor.com"

    @pytest.mark.parametrize(
        "junk",
        ["logo@2x.png", "sprite@3x.webp", "noreply@factory.com",
         "you@yourdomain.com", "abc@sentry.io"],
    )
    def test_things_that_are_not_a_way_to_reach_anyone_are_skipped(self, junk):
        assert emails_in(f"contact us at {junk} today") == []

    def test_a_page_with_no_address_produces_nothing_rather_than_a_guess(self):
        assert emails_in("") == []
        assert emails_in("No contact details on this page at all.") == []


class TestFindingAPhoneNumber:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Phone: 310-555-7788", "+13105557788"),
            ("Phone +1 310 555 7788", "+13105557788"),
            ("Cell: (310) 555-7788", "+13105557788"),
            ("Toll-free 1-800-555-0199", "+18005550199"),
            # A supplier outside the US still has to be readable.
            ("Tel: +62 21 5566 7788", "+622155667788"),
        ],
    )
    def test_published_formats_all_normalize_to_one_dialable_number(self, text, expected):
        assert phones_in(text) == [expected]

    def test_the_country_code_survives_normalization(self):
        """`identity.normalize_phone` truncates for matching; dialling cannot.

        A bare ten-digit number is assumed North American, which is the market
        this defaults to, so what goes on the record is dialable rather than
        merely comparable.
        """
        number = phones_in("Phone: 310-555-7788")[0]
        assert number == "+13105557788"
        assert len(number.lstrip("+")) == 11

    def test_a_minimum_order_quantity_is_not_a_phone_number(self):
        assert phones_in("Minimum order 500 units, capacity 40,000 units per month") == []

    def test_a_price_is_not_a_phone_number(self):
        assert phones_in("Price $8.50 per unit at 1,000 units") == []

    def test_a_ten_digit_figure_with_no_hint_beside_it_is_not_a_number(self):
        """The pattern alone would match this; the hint window is what rejects it."""
        assert phones_in("Part number 3105557788 ships in 14 days") == []

    def test_the_number_beside_the_word_telephone_wins_over_a_stray_figure(self):
        text = "Founded 2009. Capacity 40000 units.\nTelephone: 310 555 9900"
        assert phones_in(text) == ["+13105559900"]


class TestWhereToLook:
    def test_candidates_cover_the_pages_that_carry_contact_details(self):
        urls = candidate_urls("https://vesselcraft.com/products/bottles", None)
        assert urls[0] == "https://vesselcraft.com"
        for path in ("/contact", "/contact-us", "/request-a-quote"):
            assert f"https://vesselcraft.com{path}" in urls

    def test_a_bare_domain_is_enough_to_start_from(self):
        assert candidate_urls(None, "vesselcraft.com")[0] == "https://vesselcraft.com"

    def test_only_the_suppliers_own_domain_is_ever_opened(self):
        """A contact page found on a directory reaches the directory."""
        urls = candidate_urls("https://vendor.com/about", "vendor.com")
        assert all(url.startswith("https://vendor.com") for url in urls)

    def test_nothing_to_go_on_produces_no_candidates(self):
        assert candidate_urls(None, None) == []
        assert candidate_urls("", "") == []


class TestWhatGoesOnTheRecord:
    def test_each_finding_quotes_the_line_it_came_from(self):
        findings = find_in_page(
            FOOTER, "https://vesselcraft.com/contact", prefer_domain="vesselcraft.com"
        )
        by_kind = {f.kind: f for f in findings}
        assert by_kind["email"].value == "sales@vesselcraft.com"
        assert "sales@vesselcraft.com" in by_kind["email"].excerpt
        assert by_kind["phone"].value == "+13105557788"
        assert "5557788" in by_kind["phone"].excerpt.replace(" ", "")
        assert all(f.source_url.endswith("/contact") for f in findings)

    def test_at_most_one_route_of_each_kind(self):
        findings = find_in_page(FOOTER, "https://x.example", prefer_domain="vesselcraft.com")
        assert len([f for f in findings if f.kind == "email"]) == 1
        assert len([f for f in findings if f.kind == "phone"]) == 1


class TestAdoptingTheSiteAVendorWasFoundOn:
    """Half of what live discovery returns has no website field at all.

    The URL the model read is right there, but taking it blindly is how a
    mission writes to a B2B directory's contact form instead of the factory.
    """

    @pytest.mark.parametrize(
        ("url", "name", "expected"),
        [
            ("https://indesso.com/products/aroma", "Indesso Aroma", "https://indesso.com"),
            ("https://www.molindo.co.id/about", "Molindo Group", "https://molindo.co.id"),
            (
                "https://kemasan-wangi.co.id/produk/botol",
                "PT Kemasan Wangi Nusantara",
                "https://kemasan-wangi.co.id",
            ),
        ],
    )
    def test_a_domain_carrying_the_company_name_is_their_own_site(self, url, name, expected):
        from app.domain.contacts import own_site_from

        assert own_site_from(url, name) == expected

    @pytest.mark.parametrize(
        ("url", "name"),
        [
            ("https://www.alibaba.com/showroom/perfume.html", "PT Sinar Pump Indonesia"),
            ("https://indotrading.com/company/kemasan", "PT Kemasan Wangi Nusantara"),
            ("https://id.linkedin.com/company/aroma", "Aroma Nusantara"),
            ("https://packagingasiareview.example.com/2024/verel", "PT Botol Prima"),
        ],
    )
    def test_a_directory_or_marketplace_is_never_adopted(self, url, name):
        from app.domain.contacts import own_site_from

        assert own_site_from(url, name) is None

    def test_nothing_to_go_on_is_not_a_guess(self):
        from app.domain.contacts import own_site_from

        assert own_site_from(None, "PT Example") is None
        assert own_site_from("https://x.co/page", "PT Example") is None
        assert own_site_from("not a url", "PT Example") is None


class TestAddressesThatWillNotAnswerASourcingEnquiry:
    """Real addresses at the right company, wrong desk."""

    @pytest.mark.parametrize(
        "low_value",
        ["data.privacy@iberchem.com", "legal@factory.co.id", "careers@factory.co.id",
         "hrd@factory.co.id", "webmaster@factory.co.id"],
    )
    def test_the_sales_desk_is_preferred_over_them(self, low_value):
        text = f"{low_value} | sales@factory.co.id"
        assert emails_in(text)[0] == "sales@factory.co.id"

    def test_but_they_are_still_a_way_in_when_nothing_else_is_published(self):
        """A privacy desk beats no contact route at all."""
        assert emails_in("data.privacy@iberchem.com") == ["data.privacy@iberchem.com"]
