"""Reading a contact route off a supplier's page.

Written against what Indonesian supplier sites actually look like: a footer with
three addresses, one belonging to the agency that built the site; a phone number
two lines from a minimum-order quantity; a `/kontak` page no search result links
to. The live failure this closes was every discovered manufacturer being
rejected for "no email or phone found", which ends a mission before it can ask
anybody anything.
"""

from __future__ import annotations

import pytest

from app.domain.contacts import candidate_urls, emails_in, find_in_page, phones_in

FOOTER = """
PT Kemasan Wangi Nusantara
Kawasan Industri Jatake Blok F2, Tangerang

Telp: +62 21 5566 7788
Email: sales@kemasan-wangi.co.id

Minimum order: 500 pcs per desain. Kapasitas 40.000 pcs per bulan.
Website by Studio Delapan — hello@studiodelapan.id
"""


class TestFindingAnAddress:
    def test_an_address_in_a_footer_is_found(self):
        assert "sales@kemasan-wangi.co.id" in emails_in(FOOTER)

    def test_the_suppliers_own_domain_outranks_the_agency_that_built_the_site(self):
        assert emails_in(FOOTER, prefer_domain="kemasan-wangi.co.id")[0] == (
            "sales@kemasan-wangi.co.id"
        )

    def test_the_sales_desk_outranks_the_switchboard(self):
        text = "info@factory.co.id | sales@factory.co.id | hrd@factory.co.id"
        assert emails_in(text, prefer_domain="factory.co.id")[0] == "sales@factory.co.id"

    def test_a_www_prefix_does_not_hide_the_domain_match(self):
        text = "cs@vendor.co.id and someone@other.example"
        assert emails_in(text, prefer_domain="www.vendor.co.id")[0] == "cs@vendor.co.id"

    @pytest.mark.parametrize(
        "junk",
        ["logo@2x.png", "sprite@3x.webp", "noreply@factory.co.id",
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
            ("Telp: 021-5566 7788", "+622155667788"),
            ("Phone +62 21 5566 7788", "+622155667788"),
            ("WA: 0812-3456-7890", "+6281234567890"),
            ("Hubungi (021) 4455 9900", "+622144559900"),
        ],
    )
    def test_published_formats_all_normalize_to_one_dialable_number(self, text, expected):
        assert phones_in(text) == [expected]

    def test_the_country_code_survives_normalization(self):
        """`identity.normalize_phone` truncates for matching; dialling cannot."""
        number = phones_in("Telp: 021-5566 7788")[0]
        assert number.startswith("+62")
        assert len(number.lstrip("+")) == 12

    def test_a_minimum_order_quantity_is_not_a_phone_number(self):
        assert phones_in("Minimum order 500 pcs, kapasitas 40.000 pcs per bulan") == []

    def test_a_price_is_not_a_phone_number(self):
        assert phones_in("Harga Rp 8.500 per pcs untuk 1.000 pcs") == []

    def test_the_number_beside_the_word_telephone_wins_over_a_stray_figure(self):
        text = "Berdiri 2009. Kapasitas 40000 pcs.\nTelepon: 021 4455 9900"
        assert phones_in(text) == ["+622144559900"]


class TestWhereToLook:
    def test_candidates_cover_the_pages_that_carry_contact_details(self):
        urls = candidate_urls("https://kemasan-wangi.co.id/produk/botol", None)
        assert urls[0] == "https://kemasan-wangi.co.id"
        assert "https://kemasan-wangi.co.id/kontak" in urls
        assert "https://kemasan-wangi.co.id/contact" in urls

    def test_a_bare_domain_is_enough_to_start_from(self):
        assert candidate_urls(None, "botolprima.co.id")[0] == "https://botolprima.co.id"

    def test_only_the_suppliers_own_domain_is_ever_opened(self):
        """A contact page found on a directory reaches the directory."""
        urls = candidate_urls("https://vendor.co.id/about", "vendor.co.id")
        assert all(url.startswith("https://vendor.co.id") for url in urls)

    def test_nothing_to_go_on_produces_no_candidates(self):
        assert candidate_urls(None, None) == []
        assert candidate_urls("", "") == []


class TestWhatGoesOnTheRecord:
    def test_each_finding_quotes_the_line_it_came_from(self):
        findings = find_in_page(
            FOOTER, "https://kemasan-wangi.co.id/kontak", prefer_domain="kemasan-wangi.co.id"
        )
        by_kind = {f.kind: f for f in findings}
        assert by_kind["email"].value == "sales@kemasan-wangi.co.id"
        assert "sales@kemasan-wangi.co.id" in by_kind["email"].excerpt
        assert by_kind["phone"].value == "+622155667788"
        assert "5566" in by_kind["phone"].excerpt
        assert all(f.source_url.endswith("/kontak") for f in findings)

    def test_at_most_one_route_of_each_kind(self):
        findings = find_in_page(FOOTER, "https://x.example", prefer_domain="kemasan-wangi.co.id")
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
