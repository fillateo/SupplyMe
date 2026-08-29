"""The deterministic demo environment.

Everything in this file is synthetic. Companies, people, brands, domains and
quotes are invented; all domains sit under the reserved `example.com` so nothing
here can be mistaken for, or resolve to, a real business.

It exists because §44 requires a demo that proves the workflow rather than
animating it. The mock providers below return this data through the same ports
the live Google adapters implement, so a demo run executes the real discovery,
research, adjudication, conflict and outreach code paths — including the two
cases the product is really about:

* `kemasan-wangi` publishes "MOQ 500" but quotes 1,000 by email. The workflow has
  to notice, decide email will not settle it, and call.
* `aroma-nusantara` and `botol-prima` both claim a major-brand customer. One is
  corroborated by the brand's own site and trade press; the other is the
  supplier's word and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DISCLAIMER = "SYNTHETIC DEMO DATA — companies, brands and quotes are invented."


@dataclass
class DemoPage:
    url: str
    title: str
    text: str


@dataclass
class DemoVideo:
    video_id: str
    title: str
    channel: str
    description: str
    self_published: bool = False


@dataclass
class DemoVendor:
    key: str
    name: str
    domain: str
    city: str
    country: str = "Indonesia"
    phone: str | None = None
    email: str | None = None
    address: str = ""
    lat: float | None = None
    lng: float | None = None
    place_id: str | None = None
    rating: float | None = None
    reviews: int | None = None
    node_keys: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    pages: list[DemoPage] = field(default_factory=list)
    videos: list[DemoVideo] = field(default_factory=list)
    #: Reply template keyed by outreach round: 0 = first request, 1 = follow-up.
    replies: dict[int, str] = field(default_factory=dict)
    reply_delay_seconds: float = 6.0
    #: Answers the voice agent gets, keyed by a substring of the question.
    call_answers: dict[str, str] = field(default_factory=dict)
    call_outcome: str = "completed"


VENDORS: list[DemoVendor] = [
    DemoVendor(
        key="kemasan-wangi",
        name="PT Kemasan Wangi Nusantara",
        domain="kemasan-wangi.example.com",
        city="Tangerang",
        phone="+62 21 5566 7788",
        email="sales@kemasan-wangi.example.com",
        address="Kawasan Industri Jatake Blok F2, Tangerang, Banten",
        lat=-6.2088, lng=106.6100,
        place_id="ChIJdemo0001KemasanWangi",
        rating=4.3, reviews=61,
        node_keys=("bottle", "pump", "cap"),
        keywords=("botol parfum", "perfume bottle", "glass bottle", "flacon", "pump", "cap"),
        pages=[
            DemoPage(
                url="https://kemasan-wangi.example.com/produk/botol-parfum-50ml",
                title="Botol Parfum Kaca 50ml — PT Kemasan Wangi Nusantara",
                text=(
                    "PT Kemasan Wangi Nusantara memproduksi botol kaca parfum sejak 2009 di "
                    "Kawasan Industri Jatake, Tangerang. Lini 50ml tersedia dalam bentuk "
                    "rectangular dan cylindrical, dengan finishing frosted, spray coating, "
                    "dan hot stamping.\n\n"
                    "Minimum order: 500 pcs per desain.\n"
                    "Kapasitas produksi: 40.000 pcs per bulan.\n"
                    "Sample: tersedia, 5-7 hari kerja.\n"
                    "Kustomisasi: warna, coating, hot stamping logo, dan cetak silkscreen.\n"
                    "Kami juga menyediakan pump sprayer dan tutup (cap) aluminium "
                    "sebagai satu paket.\n\n"
                    "Hubungi: sales@kemasan-wangi.example.com | +62 21 5566 7788"
                ),
            ),
            DemoPage(
                url="https://kemasan-wangi.example.com/tentang-kami",
                title="Tentang Kami — PT Kemasan Wangi Nusantara",
                text=(
                    "Berdiri tahun 2009, kami melayani lebih dari 200 brand parfum lokal. "
                    "Pabrik kami memiliki 3 lini produksi dan tim desain in-house. "
                    "Kami memegang sertifikasi ISO 9001:2015."
                ),
            ),
        ],
        replies={
            # The published MOQ is 500; the sales desk quotes 1,000. This is the
            # conflict the whole demo turns on.
            0: (
                "Selamat siang,\n\n"
                "Terima kasih atas ketertarikannya pada produk kami.\n\n"
                "Untuk botol 50ml rectangular, minimum order kami 1.000 pcs per desain. "
                "Harga di 1.000 pcs adalah Rp 8.500/pcs untuk botol, pump sprayer Rp 2.500/pcs, "
                "dan cap aluminium Rp 1.500/pcs.\n\n"
                "Sample bisa kami kirim dalam 7 hari kerja, biaya Rp 250.000 termasuk ongkir. "
                "Pembayaran 50% DP, 50% sebelum pengiriman.\n\n"
                "Salam,\nRina — Sales\nPT Kemasan Wangi Nusantara"
            ),
        },
        call_answers={
            "500": "Untuk pilot order 500 pcs bisa kami kerjakan, harganya Rp 11.000 per botol. "
                   "Kalau ambil 1.000 baru turun ke Rp 8.500.",
            "pilot": "Bisa, 500 pcs untuk pilot kami terima.",
            "lead time": "Produksi 21 hari kerja setelah sample disetujui.",
            "produksi": "21 hari kerja.",
            "customization": "Hot stamping logo bisa, tambahan Rp 900 per pcs.",
        },
    ),
    DemoVendor(
        key="aroma-nusantara",
        name="PT Aroma Nusantara Manufaktur",
        domain="aroma-nusantara.example.com",
        city="Bekasi",
        phone="+62 21 8899 1122",
        email="inquiry@aroma-nusantara.example.com",
        address="Jl. Raya Narogong KM 12, Bekasi, Jawa Barat",
        lat=-6.2650, lng=107.0300,
        place_id="ChIJdemo0002AromaNusantara",
        rating=4.6, reviews=134,
        node_keys=("filling", "fragrance", "manufacturing"),
        keywords=(
            "maklon parfum", "contract filling", "perfume manufacturer",
            "fragrance", "filling",
        ),
        pages=[
            DemoPage(
                url="https://aroma-nusantara.example.com/layanan/maklon-parfum",
                title="Maklon Parfum & Filling — PT Aroma Nusantara Manufaktur",
                text=(
                    "Kami adalah pabrik maklon parfum dengan izin BPOM dan sertifikat CPKB. "
                    "Layanan kami mencakup formulasi, sourcing bibit parfum, filling, "
                    "crimping, dan packaging akhir.\n\n"
                    "Minimum order maklon: 300 pcs.\n"
                    "Lead time produksi: 25-30 hari kerja setelah formula disetujui.\n"
                    "Kami dapat menangani pengadaan botol dan kemasan sekaligus, sehingga klien "
                    "cukup berhubungan dengan satu vendor.\n\n"
                    "Klien kami termasuk Maison Verel, salah satu rumah parfum premium.\n\n"
                    "Hubungi: inquiry@aroma-nusantara.example.com | +62 21 8899 1122"
                ),
            )
        ],
        videos=[
            DemoVideo(
                video_id="demo_tour_aroma",
                title="Factory tour: inside an Indonesian perfume filling plant",
                channel="Aroma Nusantara Official",
                description="A walkthrough of our filling and crimping lines in Bekasi.",
                self_published=True,
            )
        ],
        replies={
            0: (
                "Dear Sir/Madam,\n\n"
                "Thank you for your enquiry.\n\n"
                "For a 50ml EDP maklon project our minimum is 300 pieces. At 500 pieces the "
                "all-in price is Rp 46,000 per unit including juice, filling, bottle, pump and "
                "cap — the complete package. Outer box is quoted separately.\n\n"
                "Production lead time is 28 working days after formula approval. Samples: "
                "10 working days, Rp 1,500,000 for three formula directions.\n"
                "Payment: 40% down payment, balance before shipment.\n\n"
                "Best regards,\nAgus Prasetyo\nPT Aroma Nusantara Manufaktur"
            ),
        },
        call_answers={},
    ),
    DemoVendor(
        key="botol-prima",
        name="PT Botol Prima Sejahtera",
        domain="botolprima.example.com",
        city="Surabaya",
        phone="+62 31 7788 3344",
        email="sales@botolprima.example.com",
        address="Jl. Rungkut Industri III No. 45, Surabaya, Jawa Timur",
        lat=-7.3300, lng=112.7600,
        place_id="ChIJdemo0003BotolPrima",
        rating=4.1, reviews=28,
        node_keys=("bottle", "cap"),
        keywords=("botol kaca", "glass bottle", "perfume bottle", "cap"),
        pages=[
            DemoPage(
                url="https://botolprima.example.com/products/perfume-bottles",
                title="Perfume Bottles — PT Botol Prima Sejahtera",
                text=(
                    "PT Botol Prima Sejahtera operates two glass furnaces in Rungkut, Surabaya, "
                    "producing cosmetic and fragrance glassware.\n\n"
                    "Minimum order quantity: 5,000 pcs per mould.\n"
                    "Standard 50ml fragrance flacons available from stock moulds; custom moulds "
                    "from 20,000 pcs.\n"
                    "Lead time: 35 days.\n\n"
                    "Our glassware has been supplied to Maison Verel and other premium houses.\n\n"
                    "Contact: sales@botolprima.example.com | +62 31 7788 3344"
                ),
            )
        ],
        replies={
            0: (
                "Hello,\n\n"
                "Our MOQ for stock-mould 50ml flacons is 5,000 pieces at Rp 6,200 each. "
                "We cannot produce 500 units — below 5,000 the furnace changeover is not "
                "economical for us.\n\n"
                "Regards,\nSales — PT Botol Prima Sejahtera"
            ),
        },
    ),
    DemoVendor(
        key="cetak-label",
        name="CV Cetak Label Mandiri",
        domain="cetaklabel.example.com",
        city="Jakarta",
        phone="+62 21 4455 9900",
        email="order@cetaklabel.example.com",
        address="Jl. Pramuka Raya No. 88, Jakarta Timur",
        lat=-6.1900, lng=106.8600,
        place_id="ChIJdemo0004CetakLabel",
        rating=4.4, reviews=95,
        node_keys=("label", "box"),
        keywords=("cetak label", "label printing", "rigid box", "kemasan", "dus"),
        pages=[
            DemoPage(
                url="https://cetaklabel.example.com/label-parfum",
                title="Cetak Label & Dus Parfum — CV Cetak Label Mandiri",
                text=(
                    "Kami mencetak label botol, dus lipat, dan rigid box untuk produk parfum "
                    "dan kosmetik.\n\n"
                    "Minimum order label: 250 pcs. Minimum rigid box: 300 pcs.\n"
                    "Finishing: hot foil emas/perak, emboss, spot UV, soft touch lamination.\n"
                    "Lead time: 10-14 hari kerja.\n"
                    "Sample cetak: 3 hari kerja, gratis untuk order di atas 1.000 pcs.\n\n"
                    "Order: order@cetaklabel.example.com | +62 21 4455 9900"
                ),
            )
        ],
        replies={
            0: (
                "Halo, terima kasih sudah menghubungi kami.\n\n"
                "Untuk 500 set label + rigid box 50ml:\n"
                "- Label art paper hot foil emas: Rp 1.850/pcs\n"
                "- Rigid box soft touch: Rp 7.400/pcs\n"
                "MOQ kami 250 pcs untuk label dan 300 pcs untuk box, jadi 500 aman.\n"
                "Lead time 12 hari kerja. Sample 3 hari.\n\n"
                "Salam, Dwi — CV Cetak Label Mandiri"
            ),
        },
    ),
    DemoVendor(
        key="sinar-pump",
        name="PT Sinar Pump Indonesia",
        domain="sinarpump.example.com",
        city="Tangerang",
        phone="+62 21 2233 4455",
        email=None,  # no email on file: this vendor forces the phone route
        address="Kawasan Industri Cikupa Blok C9, Tangerang",
        lat=-6.2200, lng=106.5100,
        place_id="ChIJdemo0005SinarPump",
        rating=3.9, reviews=17,
        node_keys=("pump", "cap"),
        keywords=("pump sprayer", "sprayer parfum", "atomizer", "cap"),
        pages=[
            DemoPage(
                url="https://sinarpump.example.com/",
                title="PT Sinar Pump Indonesia — Sprayer & Closures",
                text=(
                    "Importir dan distributor pump sprayer, atomizer, dan closure untuk industri "
                    "parfum dan kosmetik. Stok tersedia di gudang Cikupa.\n"
                    "Hubungi kami di +62 21 2233 4455."
                ),
            )
        ],
        call_answers={
            "minimum": "Minimum 1.000 pcs untuk sprayer standar, ada stok.",
            "price": "Rp 2.200 per pcs untuk sprayer aluminium.",
            "lead time": "Kalau stok ada, kirim 3 hari.",
        },
    ),
]


#: Independent sources. These are what separate a supported brand claim from a
#: supplier's own marketing.
INDEPENDENT_PAGES: list[DemoPage] = [
    DemoPage(
        url="https://maisonverel.example.com/en/craft/our-partners",
        title="Our Partners — Maison Verel",
        text=(
            "Maison Verel works with a small number of production partners in Asia. "
            "Since 2021, filling and assembly for our Southeast Asian editions has been "
            "carried out by PT Aroma Nusantara Manufaktur in Bekasi, Indonesia."
        ),
    ),
    DemoPage(
        url="https://packagingasiareview.example.com/2024/aroma-nusantara-verel",
        title="Maison Verel confirms Indonesian filling partner — Packaging Asia Review",
        text=(
            "Speaking at Cosmoprof Asia, Maison Verel's operations director confirmed that "
            "PT Aroma Nusantara Manufaktur handles filling for the house's regional editions. "
            "The Bekasi plant holds CPKB certification and has run Verel's 50ml line since 2021."
        ),
    ),
    DemoPage(
        url="https://industriparfum.example.com/direktori/kemasan-wangi",
        title="PT Kemasan Wangi Nusantara — Direktori Industri Parfum",
        text=(
            "PT Kemasan Wangi Nusantara. Kategori: kemasan primer, botol kaca. "
            "Lokasi: Tangerang, Banten. Berdiri 2009. Minimum order dilaporkan 500 pcs."
        ),
    ),
]

#: Brand claims a supplier makes, and whether the world corroborates them.
#: `botol-prima`'s claim has no independent source anywhere in this dataset —
#: that is the point.
BRAND_CLAIMS: dict[str, list[str]] = {
    "aroma-nusantara": ["Maison Verel"],
    "botol-prima": ["Maison Verel"],
}


def vendor_by_key(key: str) -> DemoVendor | None:
    return next((v for v in VENDORS if v.key == key), None)


def vendor_by_name(name: str) -> DemoVendor | None:
    needle = name.lower()
    for vendor in VENDORS:
        if vendor.name.lower() in needle or needle in vendor.name.lower():
            return vendor
    return None


def vendor_by_email(address: str) -> DemoVendor | None:
    return next((v for v in VENDORS if v.email and v.email.lower() == address.lower()), None)


def vendor_by_domain(domain: str) -> DemoVendor | None:
    host = (domain or "").lower().split("://")[-1].split("/")[0]
    return next((v for v in VENDORS if v.domain in host or host in v.domain), None)
