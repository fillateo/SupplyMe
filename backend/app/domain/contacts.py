"""Finding a way to reach a supplier.

A supplier the system cannot contact is worth nothing to a buyer, however well
researched: the whole second half of a mission — the quotation, the disagreement,
the confirmed MOQ — begins with an email address. In practice that address is
almost never in a search snippet and almost always in a page footer or on a page
called `/kontak`, which no search result links to.

So this module does not ask a model. Reading an address off a page is pattern
matching, and pattern matching is cheaper, faster and more reliable here than a
model call that can invent a plausible address. Judging what a supplier claims
is the model's job; finding where to write to them is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .identity import name_tokens

#: Where a contact route lives, in the two languages this market publishes in.
#: Ordered by how often they pay off, because the caller stops at the first hit.
CONTACT_PATHS: tuple[str, ...] = (
    "",                       # the homepage footer answers more often than not
    "/contact",
    "/kontak",
    "/hubungi-kami",
    "/contact-us",
    "/kontak-kami",
    "/about",
    "/tentang-kami",
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")

#: An `@` in running text is not always an address. These are the shapes that
#: turn up on real supplier sites and are never someone you can write to.
_EMAIL_NOISE = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
    "@2x", "@3x", "sentry.io", "wixpress.com", "godaddy", "@example.org",
    "@sentry", "@domain.com", "@youremail", "@email.com", "@yourdomain",
)

#: Which address to prefer when a page lists several. `sales` before `info`
#: because a sourcing enquiry sent to the sales desk gets a quotation, and one
#: sent to the switchboard gets forwarded, eventually.
_ROLE_PRIORITY = (
    "sales", "penjualan", "order", "marketing", "inquiry", "enquiry",
    "info", "contact", "kontak", "cs", "customerservice", "hello", "halo",
)

#: Addresses that exist in order not to be replied to.
_UNREACHABLE_LOCAL_PARTS = ("noreply", "no-reply", "donotreply", "postmaster", "abuse")

#: Real addresses at the right company that will not answer a sourcing enquiry.
#: Kept as a last resort rather than discarded — a privacy desk is still a way
#: in when a supplier publishes nothing else — but never preferred over sales.
_LOW_VALUE_LOCAL_PARTS = (
    "privacy", "legal", "dpo", "gdpr", "career", "careers", "karir", "rekrutmen",
    "recruitment", "hrd", "webmaster", "press", "media", "investor",
)

#: Indonesian landlines and mobiles, and anything already in E.164.
_PHONE_RE = re.compile(
    r"(?:\+?62|0)(?:[\s.\-()]{0,2}\d){8,13}"
    r"|\+\d{1,3}(?:[\s.\-()]{0,2}\d){7,14}"
)

#: Text near a number that says it really is a phone number.
_PHONE_HINTS = (
    "telp", "telepon", "tlp", "phone", "hp", "wa", "whatsapp", "fax",
    "hubungi", "call", "mobile", "kontak", "contact", "tel",
)


@dataclass(frozen=True)
class ContactFinding:
    """One reachable route, carrying the line it was read from."""

    value: str
    kind: str                 # "email" | "phone"
    source_url: str
    excerpt: str


def own_site_from(source_url: str | None, vendor_name: str) -> str | None:
    """The supplier's own site, when the page they were found on *is* it.

    Discovery often returns a company without a website — the model read a
    listing and copied the name. The URL it read is right there, but adopting it
    blindly is how a mission ends up writing to a B2B directory's contact form
    instead of the factory. So the domain is only taken when it carries the
    company's own name: `indesso.com` for Indesso Aroma, never `alibaba.com`.
    """
    host = _registrable_host(source_url)
    if host is None:
        return None
    label = host.split(".")[0]
    if len(label) < 4:
        return None
    tokens = {t for t in name_tokens(vendor_name) if len(t) >= 4}
    if not tokens:
        return None
    flat = label.replace("-", "")
    if any(token in flat or flat in token for token in tokens):
        return f"https://{host}"
    return None


def _registrable_host(url: str | None) -> str | None:
    raw = (url or "").strip().lower()
    if not raw:
        return None
    host = raw.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].removeprefix("www.")
    return host if host and "." in host else None


def candidate_urls(website: str | None, domain: str | None) -> list[str]:
    """Where to look for a contact route on the supplier's own site.

    Only ever the supplier's own domain. A contact page found on a directory is
    the directory's contact page, and writing to it reaches the directory.
    """
    base = _base_url(website, domain)
    if base is None:
        return []
    return [f"{base}{path}" for path in CONTACT_PATHS]


def _base_url(website: str | None, domain: str | None) -> str | None:
    """`https://host` for a value that actually names a host.

    Every candidate is built from this, so a malformed field has to produce
    nothing rather than a URL like `https://https:` that will be fetched, fail,
    and look like the supplier simply has no contact page.
    """
    raw = (website or "").strip()
    if raw:
        match = re.match(r"^(https?://[^/\s]+)", raw)
        host = match.group(1).split("://", 1)[1] if match else raw.split("/")[0].strip()
        if _is_hostname(host):
            return f"https://{host.rstrip('.')}"
    host = (domain or "").strip().lower().split("/")[0]
    return f"https://{host}" if _is_hostname(host) else None


def _is_hostname(value: str) -> bool:
    host = (value or "").strip().lower().split(":")[0]
    return bool(host) and "." in host and not host.startswith(".") and not host.endswith(".")


def emails_in(text: str, *, prefer_domain: str | None = None) -> list[str]:
    """Every address in `text`, best first.

    Best means: on the supplier's own domain, then the desk that answers
    quotations, then everything else. A page listing both `sales@factory.co.id`
    and the web agency that built the site must not produce the agency's.
    """
    seen: dict[str, None] = {}
    for raw in _EMAIL_RE.findall(text or ""):
        address = raw.strip().strip(".,;:").lower()
        if _is_noise(address):
            continue
        seen.setdefault(address, None)

    wanted = (prefer_domain or "").lower().removeprefix("www.")
    return sorted(seen, key=lambda address: _email_rank(address, wanted))


def _is_noise(address: str) -> bool:
    if any(marker in address for marker in _EMAIL_NOISE):
        return True
    local, _, host = address.partition("@")
    if not local or not host or "." not in host:
        return True
    if local in _UNREACHABLE_LOCAL_PARTS:
        return True
    # A trailing file extension means this was a filename, not an address.
    return bool(re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", host))


def _email_rank(address: str, prefer_domain: str) -> tuple[int, int, int, str]:
    local, _, host = address.partition("@")
    host = host.removeprefix("www.")
    own = (
        0
        if prefer_domain and (host == prefer_domain or host.endswith(f".{prefer_domain}"))
        else 1
    )
    low_value = 1 if any(marker in local for marker in _LOW_VALUE_LOCAL_PARTS) else 0
    role = next(
        (i for i, marker in enumerate(_ROLE_PRIORITY) if marker in local), len(_ROLE_PRIORITY)
    )
    return (own, low_value, role, address)


def phones_in(text: str) -> list[str]:
    """Phone numbers in `text`, normalized, in the order they appear.

    A number is taken only when something nearby says it is one. Supplier pages
    are full of digits — prices, minimum quantities, years, postcodes — and a
    "phone number" that is actually an MOQ produces a call to nobody.
    """
    body = text or ""
    lowered = body.lower()
    found: dict[str, int] = {}
    for match in _PHONE_RE.finditer(body):
        digits = re.sub(r"[^\d+]", "", match.group(0))
        if not _plausible_phone(digits):
            continue
        window = lowered[max(match.start() - 40, 0) : match.end() + 20]
        if not any(hint in window for hint in _PHONE_HINTS):
            continue
        found.setdefault(_display_phone(digits), match.start())
    return sorted(found, key=lambda number: found[number])


def _plausible_phone(digits: str) -> bool:
    return 9 <= len(re.sub(r"\D", "", digits)) <= 15


def _display_phone(raw: str) -> str:
    """E.164 for storage.

    Deliberately not `identity.normalize_phone`, which keeps only the last
    eleven digits so that `021-...` and `+62 21 ...` compare equal. That is the
    right key for matching two records and the wrong string to dial: it drops
    the country code it just added.
    """
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return f"+{digits}"
    if digits.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("0"):
        return f"+62{digits[1:]}"
    if digits.startswith("62"):
        return f"+{digits}"
    return f"+{digits}"


def find_in_page(
    text: str, url: str, *, prefer_domain: str | None = None
) -> list[ContactFinding]:
    """The best route of each kind on one page, each quoting its own line."""
    findings: list[ContactFinding] = []
    for address in emails_in(text, prefer_domain=prefer_domain)[:1]:
        findings.append(
            ContactFinding(address, "email", url, _line_containing(text, address))
        )
    for number in phones_in(text)[:1]:
        findings.append(ContactFinding(number, "phone", url, _line_containing(text, number)))
    return findings


def _line_containing(text: str, needle: str) -> str:
    """The line the value was read from, so the record can quote its source."""
    digits = re.sub(r"\D", "", needle)
    for line in (text or "").splitlines():
        if needle.lower() in line.lower():
            return line.strip()[:280]
        if len(digits) >= 9 and digits[-8:] in re.sub(r"\D", "", line):
            return line.strip()[:280]
    return (text or "").strip()[:280]
