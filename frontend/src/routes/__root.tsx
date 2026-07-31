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
			// The brand gradient is the product; a dark UA theme would fight it.
			{ name: "color-scheme", content: "light" },
			{ name: "theme-color", content: "#33165c" },
		],
		// Order matters. The preconnects come first so the TLS handshakes to both
		// font hosts start before anything needs them, and the font stylesheet is a
		// real link rather than an @import inside styles.css — a remote @import is
		// only discovered after that file is fetched and parsed, which serialises
		// the font CSS and the font files behind it.
		links: [
			{ rel: "preconnect", href: "https://fonts.googleapis.com" },
			{
				rel: "preconnect",
				href: "https://fonts.gstatic.com",
				crossOrigin: "anonymous",
			},
			// Only the faces the design actually uses:
			//   Instrument Serif regular — .hero__title (the italic face is unused)
			//   JetBrains Mono 400       — the recorder's clock and the language codes,
			//                              where the glyphs are measurement
			//   Sora 300-700             — 300 .hero__sub, 700 <strong>, rest are UI
			// display=swap paints text in the fallback immediately and swaps on load.
			{
				rel: "stylesheet",
				href: "https://fonts.googleapis.com/css2?family=Instrument+Serif&family=JetBrains+Mono:wght@400&family=Sora:wght@300;400;500;600;700&display=swap",
			},
			{ rel: "stylesheet", href: appCss },

			// Favicons. The .ico carries 16/32/48 and is what Windows uses for
			// taskbar and bookmark surfaces; the PNGs are what modern browsers
			// actually pick, and naming both sizes saves them downscaling one.
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

			// iOS home screen. Opaque on purpose — iOS composites any
			// transparency onto black, which would put the plum mark in a box.
			{
				rel: "apple-touch-icon",
				href: "/apple-touch-icon.png",
				sizes: "180x180",
			},

			// Android install prompt and the standalone launch colours. The
			// 192/512 icons are referenced from here rather than as <link>s.
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
