import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AspireChat } from "#/components/chat/AspireChat";

export interface ShellSearch {
	simple?: true;
}

export const Route = createFileRoute("/_shell")({
	validateSearch: (search: Record<string, unknown>): ShellSearch =>
		search.simple === true || search.simple === "true" ? { simple: true } : {},
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
