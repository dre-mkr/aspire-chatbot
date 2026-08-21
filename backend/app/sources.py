"""What a knowledge-base row's `source_url` becomes by the time a reader sees it.

The corpus stores one field about provenance -- a `source_url` per row -- and it
is not all one kind of thing. Two thirds of it is web pages, on seventeen
different hosts. The other third is `internal:aspire-financial-education` and
three siblings: programme material the ASPIRE team wrote, which has no public
page and never will.

Both are real sources and only one of them is a link. So the job here is to
decide, per row, which of the two it is, and to produce a reference that is
honest either way: a validated URL when there is a page to open, a name on its
own when there is not, and nothing at all when the stored value is unusable.

Three rules run through the whole module.

*Nothing is invented.* Every field is derived from what ingest stored or from
`data/sources.yaml`. A URL that is not in the corpus cannot appear in a
citation, because there is no path by which one could get here.

*A bad value is dropped, never repaired.* `canonical` and `safe_url` return
None rather than a guess. A row whose URL will not parse cites by name; a row
with neither cites by its knowledge-base id. There is no rung below that.

*The link and the dedup key are different strings.* `safe_url` changes as
little as it can, because the reader is going to open it. `canonical` is
allowed to be aggressive, because nobody ever sees it -- it exists so that
`/program`, `/program/` and `/program?utm_source=x` count as one source.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

#: The only schemes a citation may link to. `internal:` is deliberately absent:
#: it is a real source and it is not a link, and `describe` handles it as such.
LINKABLE_SCHEMES: frozenset[str] = frozenset({"https", "http"})

#: The prefix the corpus uses for material with no public page.
DOCUMENT_SCHEME = "internal:"

#: Analytics parameters, which identify the click rather than the page. Dropping
#: one cannot change what a server returns, which is why the href drops them too.
#:
#: `ref` is deliberately NOT here. It is an analytics parameter on some sites
#: and a content selector on many more -- an edition, a revision, a document id
#: -- and dropping it can change what a server returns, which is the one thing
#: this list promises it cannot do. It also made two genuinely different
#: documents share a key AND a link.
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref_src",
        "yclid",
    }
)

#: The same, as prefixes -- `utm_source`, `utm_medium` and everything after.
TRACKING_PREFIXES: tuple[str, ...] = ("utm_", "_hs", "pk_", "mtm_")

#: Longer than any real page, and long enough that a pasted blob is not one.
MAX_URL_CHARS = 2048

#: Hosts that are this machine rather than the public web. A citation pointing
#: at one would be an internal address leaking into a reader's browser.
_PRIVATE_HOSTS = re.compile(
    r"^(?:localhost|.*\.localhost|.*\.local|.*\.internal|.*\.localdomain|.*\.home\.arpa)$",
    re.IGNORECASE,
)

#: A public source's last label is a real top-level domain: letters, at least
#: two of them. This is what refuses an address rather than a name, and it
#: catches the forms a dotted-quad check does not -- `127.1`, `10.0.0.5`,
#: `192.168.1.1` and every shortened variant end in a numeric label.
_TLD = re.compile(r"^[a-z]{2,}$")

#: Anything a URL may not contain. Whitespace and control characters here mean
#: the value was pasted or concatenated, not authored.
_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f<>\"'`\\]")

#: One label of a hostname: letters, digits and inner hyphens, and nothing else.
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

#: RFC 1035's limits. Enforced because they are also what keeps `domain` inside
#: the wire schema's own cap: `a.` five hundred times is every-label-valid, has
#: a letters-only TLD, fits inside `MAX_URL_CHARS`, and yields a 1003-character
#: "domain" that raises from inside the streaming response.
MAX_LABEL_OCTETS = 63
MAX_HOST_OCTETS = 253


def _hostname_ok(host: str) -> bool:
    """Whether every label of this host is one a browser would actually resolve.

    Two things get in without it, and both end up displayed as the reassurance
    a reader checks before tapping.

    Percent-encoding hides the userinfo separator: `parts.hostname` for
    `https://good.example%40evil.example/` is the whole string, the literal `@`
    test above never sees one, and the panel prints
    `good.example%40evil.example` under a link that silently does nothing.

    And non-ASCII hosts are homographs waiting to happen -- a Cyrillic `а` in
    `аspire.gov.kn` is a different host that reads as the real one. Refused
    rather than punycoded: every source the corpus holds is ASCII, and a
    genuine internationalised source is a deliberate addition, not something to
    guess at silently.

    The same rule disposes of `https://.com/x` and `https://-.-/x`, which pass a
    "contains a dot" test and resolve to nothing.

    And the last label has to be a real top-level domain. A dotted-quad test
    only catches `10.0.0.5`; `https://127.1/x` is the same machine written
    shorter, has a dot, and has two perfectly good LDH labels.
    """
    if len(host) > MAX_HOST_OCTETS:
        return False
    labels = host.split(".")
    if len(labels) < 2 or any(len(label) > MAX_LABEL_OCTETS for label in labels):
        return False
    if not all(_LABEL.match(label) for label in labels):
        return False
    return bool(_TLD.match(labels[-1]))


def _folded(text: str) -> str:
    return " ".join(text.casefold().split())


#: What a source's naming may cost on the wire. `CitationRef` caps the same
#: fields, and a value that arrives over-length there raises a `ValidationError`
#: from inside the streaming generator -- which does not degrade the citation,
#: it kills the whole turn. So the clipping happens where the value is BUILT,
#: and the schema's cap becomes a backstop rather than a tripwire.
#:
#: Reachable: `page_name_from_path` de-slugifies a URL's last path segment, and
#: the corpus already holds a 130-character one.
MAX_SITE_CHARS = 160
MAX_PAGE_CHARS = 200
MAX_UPDATED_CHARS = 32


def clip(text: str, limit: int) -> str:
    """`text`, cut at a word boundary where there is one nearby."""
    said = " ".join((text or "").split())
    if len(said) <= limit:
        return said
    cut = said[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return f"{cut.rstrip(' ,;:.-')}…"


class SourceRef(BaseModel):
    """One source, in the words a reader gets rather than the ones ingest stored."""

    model_config = ConfigDict(extra="forbid")

    #: Where to send them. Empty when the source has no public page, which is a
    #: state the UI renders rather than an error: the name still shows.
    url: str = ""
    #: Whose source it is -- "ASPIRE", "Eastern Caribbean Central Bank".
    site: str = ""
    #: Which page of theirs -- "Frequently asked questions".
    page: str = ""
    #: The host, for the second line under the title. Never the full URL.
    domain: str = ""
    #: When the corpus row was last checked against the source, from the CSV's
    #: `as_of` column. Shown as provenance, never as the page's own date.
    updated: str = ""

    @property
    def label(self) -> str:
        """The one line to show when there is only room for one.

        Joining the two is the normal case -- "ASPIRE — Frequently asked
        questions" -- but only when both halves earn their place. Where one
        contains the other the longer one is the whole label, so neither
        "Jump$tart Coalition — Jump$tart Coalition" nor "Instagram — ASPIRE on
        Instagram" can be produced.
        """
        if not (self.site and self.page):
            return self.site or self.page or self.domain
        site, page = _folded(self.site), _folded(self.page)
        if page in site:
            return self.site
        if site in page:
            return self.page
        return f"{self.site} — {self.page}"

    @property
    def key(self) -> str:
        """What makes two references the same source.

        The collapse itself happens in the renderer -- see the note further
        down -- but the rule lives here, so `tools/sources_check` and anything
        that has to reason about "is this the same page" asks one function.
        """
        return canonical(self.url) or self.label.casefold()


# ── the registry ─────────────────────────────────────────────────────────────

#: Where the names live. Data, so that adding a source is an edit and not a deploy.
REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "sources.yaml"


class Registry(BaseModel):
    """`data/sources.yaml`, validated."""

    model_config = ConfigDict(extra="forbid")

    #: host (no `www.`) -> whose site it is.
    sites: dict[str, str] = {}
    #: canonical URL -> what that page is called.
    pages: dict[str, str] = {}
    #: `internal:...` -> what the material is called.
    documents: dict[str, str] = {}


@lru_cache(maxsize=1)
def registry(path: Path | None = None) -> Registry:
    """The source names, read once per process.

    A missing or broken file costs the wording and nothing else: citations fall
    back to their domain, which is still true and still clickable. Losing every
    source because one YAML key was mistyped would be the worse failure.
    """
    import yaml

    where = path or REGISTRY_PATH
    try:
        raw = yaml.safe_load(where.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.warning("No source registry at %s; citations will show domains.", where)
        return Registry()
    except yaml.YAMLError:
        logger.error("%s is not valid YAML; citations will show domains.", where.name)
        return Registry()

    try:
        return Registry.model_validate(raw)
    except Exception:
        logger.error("%s does not match the registry schema.", where.name, exc_info=True)
        return Registry()


def forget_registry() -> None:
    """Drop the cached registry. For tests, and for a reload after an edit."""
    registry.cache_clear()


# ── URLs ─────────────────────────────────────────────────────────────────────


def _split(raw: Any) -> tuple[str, str, int | None, str, str, str] | None:
    """A URL's parts, or None when it is not a URL we may ever link to.

    Returns `(scheme, host, port, path, query, fragment)`. The host is
    lowercased and stripped of any userinfo; the port is None unless the URL
    named one.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > MAX_URL_CHARS or _UNSAFE.search(value):
        return None

    try:
        parts = urlsplit(value)
    except ValueError:
        # A malformed IPv6 literal, chiefly. Unparseable is unusable.
        return None

    scheme = parts.scheme.lower()
    if scheme not in LINKABLE_SCHEMES:
        return None

    # `netloc` carries userinfo and port; the host alone decides whether to link.
    if "@" in parts.netloc:
        # `https://aspire.gov.kn@evil.example` reads as ASPIRE and is not.
        return None
    host = (parts.hostname or "").lower()
    if not host or "." not in host or host.endswith("."):
        return None
    if not _hostname_ok(host) or _PRIVATE_HOSTS.match(host):
        return None

    try:
        port = parts.port
    except ValueError:
        # A non-numeric port. Unparseable is unusable.
        return None
    if port is not None and port not in (80, 443):
        # A public source does not live on a high port; an internal service does.
        return None

    return scheme, host, port, parts.path, parts.query, parts.fragment


def _query_without_tracking(query: str) -> str:
    """The query string with analytics parameters removed and duplicates collapsed.

    Purely SUBTRACTIVE: the kept pairs are the caller's own bytes, spliced back
    together, never decoded and re-encoded.

    Decoding through `parse_qsl` and rebuilding with `urlencode` looked tidier
    and was wrong twice. It EXPANDS -- `urlencode` percent-encodes everything
    outside the unreserved set, so one accented character becomes six -- which
    means a 448-character stored URL could come back 2148 characters long, past
    the cap `_split` enforces on its input. `safe_url` then would not accept its
    own output, and `describe`, which reads the domain off that output, lost the
    site and the page along with the link: total attribution loss on a row whose
    stored URL was perfectly good. It also rewrote the reader's link into a
    different string from the one the corpus authored, which is the thing
    `safe_url` promises never to do.
    """
    if not query:
        return ""
    kept: list[str] = []
    seen: set[str] = set()
    for pair in query.split("&"):
        if not pair:
            continue
        name = pair.split("=", 1)[0].lower()
        if name in TRACKING_PARAMS or name.startswith(TRACKING_PREFIXES):
            continue
        if pair in seen:
            continue
        seen.add(pair)
        kept.append(pair)
    return "&".join(kept)


def safe_url(raw: Any) -> str | None:
    """The URL to put in an `href`, or None when there is nothing safe to link.

    Deliberately conservative. The reader is going to open this, so the only
    edits are ones that cannot change what a server returns: the scheme and host
    are lowercased (both are case-insensitive by spec) and analytics parameters
    are dropped. The path keeps its case and its trailing slash, because those
    are the server's business and not ours.
    """
    parts = _split(raw)
    if parts is None:
        return None
    scheme, host, port, path, query, fragment = parts
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme, netloc, path, _query_without_tracking(query), fragment))


def canonical(raw: Any) -> str | None:
    """The form two URLs share when they are the same page, or None.

    Never rendered and never opened -- it is a dedup key and the key the page
    registry is written against. That is what lets it drop `www.`, normalise the
    scheme and strip a trailing slash, none of which is safe to do to a link.

    A fragment is KEPT. `https://aspire.gov.kn/#faqs` is a section of the
    homepage and the corpus cites both; folding them together would throw away
    the more precise of the two, which is the opposite of the point.
    """
    parts = _split(raw)
    if parts is None:
        return None
    scheme, host, _port, path, query, fragment = parts

    if host.startswith("www."):
        host = host[4:]
    # Both schemes address the same page; https is the one written down.
    scheme = "https"
    path = path.rstrip("/") if path not in ("", "/") else "/"
    return urlunsplit((scheme, host, path, _query_without_tracking(query), fragment))


def domain_of(raw: Any) -> str:
    """The host as a reader would read it: no scheme, no `www.`, no path."""
    parts = _split(raw)
    if parts is None:
        return ""
    host = parts[1]
    return host.removeprefix("www.")


# ── naming ───────────────────────────────────────────────────────────────────

#: Words a de-slugified path should not have capitalised in the middle of a title.
_MINOR_WORDS = frozenset(
    {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to"}
)

#: A path segment that names nothing: a date, an id, a file extension.
_EMPTY_SEGMENT = re.compile(r"^(?:\d+|index|home|default)(?:\.\w{1,5})?$", re.IGNORECASE)


def page_name_from_path(url: str) -> str:
    """A page's name read off its own path, when the registry does not name it.

    `/national-accomplishments/aspire_info` becomes "Aspire info". Crude, and
    better than showing somebody a path: it is the fallback under the fallback,
    and every URL the corpus actually holds is named in the registry.
    """
    parts = _split(url)
    if parts is None:
        return ""
    path = parts[3]
    segments = [s for s in path.split("/") if s and not _EMPTY_SEGMENT.match(s)]
    if not segments:
        return ""

    words = re.split(r"[-_+]+", re.sub(r"\.\w{1,5}$", "", segments[-1]))
    words = [w for w in words if w]
    if not words:
        return ""

    titled = [
        word if word.isupper() else (word.lower() if word.lower() in _MINOR_WORDS else word)
        for word in words
    ]
    name = " ".join(titled)
    return name[:1].upper() + name[1:]


#: The metadata keys ingest may have written a per-row title under. First wins,
#: so a knowledge base that grows a `source_title` column overrides the registry
#: without any code change.
TITLE_KEYS: tuple[str, ...] = ("source_title", "page_title", "source_name", "source_document")

#: Where the stored URL lives. `source_url` is the column; `url` and `link` are
#: the aliases ingest already accepts on the way in.
URL_KEYS: tuple[str, ...] = ("source_url", "url", "link")

#: When the row was last checked against its source.
UPDATED_KEYS: tuple[str, ...] = ("as_of", "updated", "retrieved_at")


def _first(metadata: dict[str, Any], keys: Iterable[str]) -> str:
    """The first non-empty value among these keys, matched case-insensitively."""
    lowered = {str(key).strip().lower(): value for key, value in (metadata or {}).items()}
    for key in keys:
        value = lowered.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


#: Values already complained about, so a defective corpus row is reported once
#: rather than on every turn that retrieves it. Bounded, because an attacker who
#: could write the corpus could otherwise grow it without limit.
_REPORTED: set[str] = set()
_REPORT_CAP = 256


def _report_unusable(raw: str) -> None:
    """Say once, loudly, that a corpus row's URL cannot be linked.

    Not silent, because §19's rule is that missing provenance is a data defect
    somebody has to fix and it is invisible otherwise. Not repeated, because the
    same row comes back on every turn that retrieves it.
    """
    if raw in _REPORTED:
        return
    if len(_REPORTED) >= _REPORT_CAP:
        # Cleared rather than left full. Refusing to record past the cap would
        # have turned the de-duplication off for every value after the 256th --
        # each one warning on every turn that retrieved it, which is the flood
        # this set exists to stop. Emptying it costs one repeated warning per
        # value per cycle and keeps the memory bound.
        _REPORTED.clear()
    _REPORTED.add(raw)
    logger.warning(
        "A corpus row stored an unusable source_url (%d chars, starts %r); the "
        "citation will carry no link. Fix the row rather than the renderer.",
        len(raw),
        raw[:32],
    )


def describe(metadata: dict[str, Any] | None, *, stored_url: str | None = None) -> SourceRef | None:
    """The reference for one retrieved chunk, or None when it has no source.

    `stored_url` is the `documents.source_url` column, which is the authority;
    `metadata` is the row's stored JSON, which is where a `source_title` and the
    `as_of` date live. Passing only one of the two is normal and supported.
    """
    metadata = metadata or {}
    raw = (stored_url or "").strip() or _first(metadata, URL_KEYS)
    if not raw:
        return None

    updated = _first(metadata, UPDATED_KEYS)
    authored = _first(metadata, TITLE_KEYS)
    names = registry()

    # ── material with no public page ────────────────────────────────────────
    if raw.lower().startswith(DOCUMENT_SCHEME):
        page = authored or names.documents.get(raw) or names.documents.get(raw.lower())
        if not page:
            # An unregistered `internal:` value: name it from its own slug rather
            # than showing the reader a scheme they have no use for.
            page = page_name_from_path(f"https://internal.invalid/{raw[len(DOCUMENT_SCHEME):]}")
        if not page:
            return None
        return SourceRef(
            page=clip(page, MAX_PAGE_CHARS), updated=clip(updated, MAX_UPDATED_CHARS)
        )

    # ── a web page ──────────────────────────────────────────────────────────
    href = safe_url(raw)
    if href is None:
        _report_unusable(raw)
        return None

    key = canonical(href) or ""
    domain = domain_of(href)
    if not domain:
        # `safe_url` accepted this and `domain_of` did not, which cannot happen
        # while both read the same `_split`. Said out loud rather than shipped:
        # the citation would go out with no site, no page and no domain -- fully
        # un-attributed -- on a row whose stored URL was perfectly good.
        logger.error(
            "safe_url and domain_of disagree about %r; citing row without a source.",
            raw[:64],
        )
        return None
    # An unregistered host is named by its own domain rather than left blank:
    # "sknis.gov.kn — VAT returns to 17%" still says whose page it is, and a
    # domain is the last thing above showing somebody a raw URL.
    site = names.sites.get(domain) or domain
    page = authored or names.pages.get(key) or page_name_from_path(href)

    return SourceRef(
        url=href,
        site=clip(site, MAX_SITE_CHARS),
        page=clip(page, MAX_PAGE_CHARS),
        domain=domain,
        updated=clip(updated, MAX_UPDATED_CHARS),
    )


# ── keeping provenance out of the prompt ─────────────────────────────────────

#: The scaffolding columns `ingest.row_to_document` appends to a row's text.
#: None of it is knowledge, and one line of it is a URL.
_SCAFFOLD_KEYS = frozenset(
    {"id", "row", "source", "source_url", "url", "link", "as_of", "keywords", "audience"}
)

_SCAFFOLD_LINE = re.compile(
    r"^\s*(" + "|".join(sorted(_SCAFFOLD_KEYS)) + r")\s*:\s.*$",
    re.IGNORECASE | re.MULTILINE,
)


def without_provenance(text: str) -> str:
    """A corpus row's text with its bookkeeping columns removed.

    `ingest` writes every unrecognised CSV column into the row's text, so an
    extract reaches the model reading `... as_of: 2026-07-30` and, three lines
    up, `source_url: https://aspire.gov.kn/`. That is a URL, in the model's
    context, in a product whose whole citation rule is that the model never
    supplies one -- and `safety_out.strip_links` only gates the personas that
    get no links at all, so for everybody else a copied URL goes straight out.

    Removing it here rather than at ingest is deliberate: the stored text is
    what was embedded, and rewriting it would mean re-embedding the corpus to
    fix a prompt-time problem. The metadata is untouched, so the citation still
    has the URL the model no longer sees.
    """
    if not text:
        return ""
    stripped = _SCAFFOLD_LINE.sub("", text)
    # The substitution leaves the blank lines behind; collapse runs of them.
    return re.sub(r"\n{2,}", "\n", stripped).strip()


# ── on collapsing several rows into one source ───────────────────────────────
#
# There is no `dedupe` here, deliberately.
#
# The wire carries one ref per CITED ROW, each with the URL that row was
# actually authored with, because a row's evidence -- its question and its own
# words -- is per-row and worth showing. Collapsing four rows off one page into
# one heading is a rendering decision, and it is made once, in
# `frontend/src/lib/aspire/sources.ts::groupSources`.
#
# Putting a second collapse on this side would mean two implementations of the
# same rule that could disagree, and it would have to throw away three rows'
# evidence to do it. `canonical` above is what both sides key on; that is the
# shared part, and it is the only part that needs to be shared.
