import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/_shell/")({
	// Inherits the shell's mode, stated so a reader of this file does not have
	// to go and look.
	ssr: true, component: () => null });
