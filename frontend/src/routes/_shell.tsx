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
}

export const Route = createFileRoute("/_shell")({
	validateSearch: (search: Record<string, unknown>): ShellSearch => {
		// The search string is user-editable, so `?persona=nonsense` must land on
		// "not chosen" rather than being forwarded to the service as a persona it
		// has never heard of.
		const persona = asPersonaId(search.persona);
		return {
			...(search.simple === true || search.simple === "true"
				? { simple: true as const }
				: {}),
			...(persona ? { persona } : {}),
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
