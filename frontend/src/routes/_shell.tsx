import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AspireChat } from "#/components/chat/AspireChat";
import { asPersonaId, type PersonaId } from "#/lib/aspire/personas";

export interface ShellSearch {
	simple?: true;
	/**
	 * Who the assistant is answering for.
	 *
	 * In the URL rather than in storage, and for the same reason `simple` is: it
	 * changes what comes back, so a link to a conversation should carry it. A
	 * teacher sending a class a link, or a parent handing the tablet over, gets
	 * the right assistant without a second instruction.
	 *
	 * Absent means not chosen, which is a real state the service understands as
	 * permissive rather than as any particular persona.
	 */
	persona?: PersonaId;
	/**
	 * Which language the conversation is being held in.
	 *
	 * It lived in `useState` plus localStorage, which had two costs. A
	 * conversation held in French reopened in whatever the device was set to,
	 * and a shared link could not carry its language at all. Worse, the
	 * SSR-safe deferral to a mount effect meant every page load painted in
	 * English and then swapped — a visible flash on every load for every ES and
	 * FR user, because the server cannot read localStorage.
	 *
	 * In the URL, the server knows before it renders. Absent means "whatever
	 * this device last chose", which is the old behaviour and the right default
	 * for someone arriving without a link.
	 */
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
	// Full-document SSR: this is the app shell and the first paint of every
	// conversation. Stated rather than inherited from a generated file.
	ssr: true,
	validateSearch: (search: Record<string, unknown>): ShellSearch => {
		// The search string is user-editable, so `?persona=nonsense` must land on
		// "not chosen" rather than being forwarded to the service as a persona it
		// has never heard of.
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
