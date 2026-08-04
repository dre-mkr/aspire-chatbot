import { TanStackDevtools } from "@tanstack/react-devtools";
import type { QueryClient } from "@tanstack/react-query";
import {
	createRootRouteWithContext,
	HeadContent,
	Scripts,
	useRouterState,
} from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import TanStackQueryDevtools from "../integrations/tanstack-query/devtools";
import appCss from "../styles.css?url";

interface MyRouterContext {
	queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<MyRouterContext>()({
	head: () => ({
		meta: [
			{ charSet: "utf-8" },
			{ name: "viewport", content: "width=device-width, initial-scale=1" },
			{ title: "ASPIRE AI · Financial literacy assistant" },
			{
				name: "description",
				content:
					"Ask ASPIRE AI about investing, your learning modules, or the ASPIRE programme in St. Kitts and Nevis.",
			},
			{ name: "color-scheme", content: "light" },
			{ name: "theme-color", content: "#33165c" },
		],
		links: [
			{ rel: "stylesheet", href: appCss },
			/*
			 * The two families in the first paint, fetched alongside the CSS
			 * rather than after it.
			 *
			 * A `@font-face` is only discovered once the stylesheet has been
			 * downloaded and parsed, which puts the font one hop behind the thing
			 * that names it. Preloading collapses that: Sora carries every word of
			 * chrome and prose, Instrument Serif carries the hero, and both are
			 * wanted at the same moment the CSS is.
			 *
			 * JetBrains Mono is deliberately NOT preloaded -- it appears in code
			 * spans inside answers, which do not exist yet at first paint, and
			 * preloading it would compete for bandwidth with the two that do.
			 *
			 * `crossOrigin` is required even same-origin: fonts are fetched in
			 * CORS mode, and a preload without it is a second, unused download.
			 */
			{
				rel: "preload",
				as: "font",
				type: "font/woff2",
				href: "/fonts/sora-var-latin.woff2",
				crossOrigin: "anonymous",
			},
			{
				rel: "preload",
				as: "font",
				type: "font/woff2",
				href: "/fonts/instrument-serif-400-latin.woff2",
				crossOrigin: "anonymous",
			},
			{ rel: "icon", href: "/favicon.ico", sizes: "32x32" },
			{
				rel: "icon",
				href: "/favicon-16x16.png",
				type: "image/png",
				sizes: "16x16",
			},
			{
				rel: "icon",
				href: "/favicon-32x32.png",
				type: "image/png",
				sizes: "32x32",
			},
			{
				rel: "apple-touch-icon",
				href: "/apple-touch-icon.png",
				sizes: "180x180",
			},
			{ rel: "manifest", href: "/site.webmanifest" },
		],
	}),
	shellComponent: RootDocument,
});

/**
 * The document's language, from the address.
 *
 * `<html lang="en">` was hardcoded. Confirmed at runtime during the audit: after
 * switching to ES or FR and reloading, `document.documentElement.lang` was still
 * `"en"` — so a screen reader pronounced Spanish and French answers with English
 * phonetics. WCAG 3.1.1 (A) and 3.1.2 (AA), and combined with the missing live
 * regions it made the assistive-technology experience in ES and FR broken twice
 * over.
 *
 * Read from the router's location rather than from the voice hook, because this
 * renders above every provider and must work during SSR — which is the whole
 * reason `lang` is a search param (P3-004) rather than device state.
 *
 * Read defensively: this is the document shell, and it renders for the
 * not-found and error routes too, where the search may not have been validated
 * by `_shell` at all.
 */
const LANGUAGES = new Set(["en", "es", "fr"]);

function useDocumentLanguage() {
	const raw = useRouterState({
		select: (state) => (state.location.search as { lang?: unknown }).lang,
	});
	return typeof raw === "string" && LANGUAGES.has(raw) ? raw : "en";
}

function RootDocument({ children }: { children: React.ReactNode }) {
	const lang = useDocumentLanguage();
	return (
		<html lang={lang}>
			<head>
				<HeadContent />
			</head>
			{/* The shell owns its own height and scrolling, so the document does not. */}
			<body style={{ overflow: "hidden" }}>
				{children}
				<TanStackDevtools
					config={{ position: "bottom-right" }}
					plugins={[
						{
							name: "TanStack Router",
							render: <TanStackRouterDevtoolsPanel />,
						},
						TanStackQueryDevtools,
					]}
				/>
				<Scripts />
			</body>
		</html>
	);
}
