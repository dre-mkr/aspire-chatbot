import { createFileRoute } from "@tanstack/react-router";
import { AspireChat } from "#/components/chat/AspireChat";

export const Route = createFileRoute("/")({ component: AspireChat });
