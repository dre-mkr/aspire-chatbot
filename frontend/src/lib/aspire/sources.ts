/**
 * Turning a turn's cited rows into the sources a reader sees.
 *
 * The server sends one ref per knowledge-base row it cited, each carrying the
 * page it came from. Four rows off the same page are four refs and one source,
 * so the collapse happens here — in the renderer, on both the live path and the
 * reload path, which is why neither has to remember what the other did.
 */

import type { Source, SourceOrigin } from "./api";
import { safeHref } from "./knowledge";

/** One cited knowledge-base row, under whichever source it came from. */
export interface SourceExtract {
	kbId: string;
	/** The question the row was written to answer. */
	question: string;
	/** The row's own words. Empty when the server sent no snippet. */
	snippet: string;
}

/** One source, with everything cited from it. */
export interface GroupedSource {
	/** Stable within a turn; used as the React key. */
	key: string;
	/** Safe to put in `href`, or null when there is nothing to open. */
	href: string | null;
	/** What to call it: "ASPIRE — Frequently asked questions". */
	label: string;
	/** The host, shown beneath the label. Empty for material with no page. */
	domain: string;
	/**
	 * When the corpus row was last checked against its source.
	 *
	 * Carried and deliberately NOT rendered. The product's global prompt rules
	 * forbid surfacing the knowledge base's `as_of` date — it is bookkeeping
	 * about the corpus, not a fact about the programme, and a "last updated"
	 * line would read as the page's date rather than ours. It is here so the
	 * decision to show it is a one-line change rather than a re-plumbing.
	 */
	updated: string;
	extracts: Array<SourceExtract>;
}

/**
 * Where this row came from, or null when nothing attributed it.
 *
 * There is no fallback to flat `metadata` keys. A transcript written before
 * provenance existed has no `url`/`site`/`page` under any name — the fields did
 * not exist to be stored — so a compatibility branch here would be code that
 * reads keys nothing ever wrote. Those rows cite by their id and their own
 * words, which is what they always did.
 */
function originOf(source: Source): SourceOrigin | null {
	return source.origin ?? null;
}

/** Analytics parameters, which identify the click rather than the page. */
const TRACKING =
	/^(?:utm_|_hs|pk_|mtm_)|^(?:fbclid|gclid|igshid|mc_cid|mc_eid|msclkid|ref|ref_src|yclid)$/i;

/**
 * What makes two links the same page.
 *
 * The server sends each cited row with the URL it was actually authored with,
 * because that is the address a reader opens — so `https://www.gov.kn/` and
 * `https://gov.kn/` can both arrive in one turn and are one source. This
 * mirrors `app/sources.canonical` on the server; that one is authoritative for
 * VALIDATION, this one only decides what groups with what, so a drift between
 * them shows up as an extra heading and never as a bad link.
 *
 * A fragment is kept: `/#faqs` is a section of a page the corpus also cites
 * whole, and folding them together would lose the more precise of the two.
 */
function groupKey(href: string): string {
	try {
		const url = new URL(href);
		url.protocol = "https:";
		url.hostname = url.hostname.replace(/^www\./, "").toLowerCase();
		url.port = "";
		for (const name of [...url.searchParams.keys()]) {
			if (TRACKING.test(name)) url.searchParams.delete(name);
		}
		if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/+$/, "");
		return url.toString();
	} catch {
		// Not parseable is not groupable; it is still its own source.
		return href;
	}
}

/**
 * The one line to show for a source.
 *
 * Mirrors the server's own rule rather than trusting it blindly, because a
 * stored transcript can carry a `site`/`page` pair written before the naming
 * changed: where one contains the other, the longer one is the whole label, so
 * "Instagram — ASPIRE on Instagram" cannot be produced.
 */
export function sourceLabel(origin: SourceOrigin): string {
	const site = origin.site.trim();
	const page = origin.page.trim();
	if (!(site && page)) return site || page || origin.domain;
	const a = site.toLowerCase();
	const b = page.toLowerCase();
	if (b.includes(a)) return page;
	if (a.includes(b)) return site;
	return `${site} — ${page}`;
}

/**
 * The turn's sources, one entry per page, in the order they were first cited.
 *
 * Rows the server could not attribute are not dropped: they collect under a
 * single unnamed entry so their evidence still shows. Nothing invents a source
 * for them — that entry has no label, no domain and no link.
 */
export function groupSources(sources: Array<Source>): Array<GroupedSource> {
	const groups = new Map<string, GroupedSource>();

	for (const source of sources) {
		const meta = source.metadata ?? {};
		const kbId = typeof meta.kb_id === "string" ? meta.kb_id : "";
		const question =
			typeof meta.question === "string"
				? meta.question
				: typeof meta.title === "string"
					? meta.title
					: "";
		// `content` on the live path, `metadata.snippet` on the reload path.
		const snippet =
			source.content || (typeof meta.snippet === "string" ? meta.snippet : "");

		const origin = originOf(source);
		// `safeHref` is the app's own sanitiser and the last gate before an
		// `href`. The server validated this URL already; a stored transcript is
		// the case it does not cover.
		const href = origin?.url ? safeHref(origin.url) : null;
		const label = origin ? sourceLabel(origin) : "";
		// Grouped on the canonical form of the link where there is one, so a
		// page cited four times — however its URL was spelled — is one heading;
		// on the name otherwise, so the programme's teaching material also
		// collapses instead of repeating.
		const key = href
			? groupKey(href)
			: label
				? `name:${label}`
				: "unattributed";

		const existing = groups.get(key);
		const extract: SourceExtract = {
			kbId,
			// The snippet is the evidence; repeating it as the question too
			// would print the same sentence twice.
			question: question === snippet ? "" : question,
			snippet,
		};
		if (existing) {
			existing.extracts.push(extract);
			continue;
		}
		groups.set(key, {
			key,
			href,
			label,
			domain: origin?.domain ?? "",
			updated: origin?.updated ?? "",
			extracts: [extract],
		});
	}

	return [...groups.values()];
}
