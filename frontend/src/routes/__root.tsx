import { TanStackDevtools } from "@tanstack/react-devtools";
import type { QueryClient } from "@tanstack/react-query";
import {
	createRootRouteWithContext,
	HeadContent,
	Scripts,
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

function RootDocument({ children }: { children: React.ReactNode }) {
	return (
		<html lang="en">
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
