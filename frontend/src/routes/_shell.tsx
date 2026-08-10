import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AspireChat } from "#/components/chat/AspireChat";
import { asPersonaId, type PersonaId } from "#/lib/aspire/personas";

export interface ShellSearch {
	simple?: true;
	/** Who the assistant is answering for. */
	persona?: PersonaId;
	/** Which language the conversation is being held in. */
	lang?: "en" | "es" | "fr";
}

const LANGUAGES = ["en", "es", "fr"] as const;

function asLanguage(value: unknown): "en" | "es" | "fr" | undefined {
	return typeof value === "string" &&
		(LANGUAGES as ReadonlyArray<string>).includes(value)
		? (value as "en" | "es" | "fr")
		: undefined;
}

export const Route = createFileRoute("/_shell")({
	// Full-document SSR: this is the app shell and the first paint of every conversation.
	ssr: true,
	validateSearch: (search: Record<string, unknown>): ShellSearch => {
		// The search string is user-editable, so `?persona=nonsense` must land on "not chosen" rather than being forwar…
		const persona = asPersonaId(search.persona);
		const lang = asLanguage(search.lang);
		return {
			...(search.simple === true || search.simple === "true"
				? { simple: true as const }
				: {}),
			...(persona ? { persona } : {}),
			...(lang ? { lang } : {}),
		};
	},
	component: Shell,
});

function Shell() {
	return (
		<>
			<AspireChat />
			<Outlet />
		</>
	);
}
