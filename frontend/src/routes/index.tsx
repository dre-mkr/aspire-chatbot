import { createFileRoute } from "@tanstack/react-router";
import { LandingScreen } from "#/components/landing/LandingScreen";
import { validateAnswerSearch } from "#/lib/aspire/search";

export const Route = createFileRoute("/")({
	// Full-document SSR: this is the first paint of the product.
	ssr: true,
	validateSearch: validateAnswerSearch,
	component: LandingScreen,
});
