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
import { DEFAULT_DOCUMENT_TITLE } from "../lib/aspire/title";
import appCss from "../styles.css?url";

interface MyRouterContext {
	queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<MyRouterContext>()({
	head: () => ({
		meta: [
			{ charSet: "utf-8" },
			{ name: "viewport", content: "width=device-width, initial-scale=1" },
			{ title: DEFAULT_DOCUMENT_TITLE },
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
			/* The two families in the first paint, fetched alongside the CSS rather than after it. */
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

/** The document's language, from the address. */
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
