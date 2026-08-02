import { createFileRoute } from "@tanstack/react-router";

/**
 * The empty state, at `/`.
 *
 * Renders nothing itself — the shell above it is the entire UI, and this route
 * exists so that "no chat is open" is a real address rather than a component
 * flag. Landing here writes nothing to storage and mints no chat.
 */
export const Route = createFileRoute("/_shell/")({ component: () => null });
