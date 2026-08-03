import { createFileRoute, Outlet } from "@tanstack/react-router";
import { AspireChat } from "#/components/chat/AspireChat";

/**
 * The shell that owns the whole product, above both of its URLs.
 *
 * A pathless layout route, deliberately. `/` and `/chat/$chatId` are the empty
 * state and a conversation, and in every product this one is modelled on the
 * page does not blink between them — so they must not be two trees. They are
 * one tree that differs by a parameter.
 *
 * ANIMATION-INVENTORY.md sets out what that buys, and it is not decoration:
 * the empty-state-to-conversation transition is a single attribute flip
 * (`data-phase` on `.app`) driving ten CSS properties for 560ms. There is no
 * element travelling from A to B, so no `layoutId` and no View Transition can
 * reproduce it. `.app`, `.hero`, `.composer` and `.rail` have to be the same
 * DOM nodes on both sides, and a route that remounted the subtree would replace
 * the whole morph with a hard cut.
 *
 * It also settles where state lives. `useVoice` and `useConversation` are both
 * called inside `AspireChat`, so mounting it here — above the params — is what
 * makes speed, language and read-aloud survive a chat change rather than being
 * reconstructed from localStorage on every navigation.
 *
 * The children render nothing on purpose: they exist to name the URLs and carry
 * `chatId`. The <Outlet /> is rendered anyway — they are real matched routes,
 * and a layout that silently drops its children is a trap for whoever gives one
 * of them a component later.
 */
/**
 * What the URL carries besides which conversation is open.
 *
 * `simple` is the plain-words toggle. It was React state inside `AspireChat`,
 * which meant the one setting that changes what the assistant is asked to
 * produce could not be linked to, bookmarked or handed to a teacher — "ask it
 * like this" was unshareable.
 *
 * Optional rather than a boolean with a default, and deliberately so: the
 * validator returns `{}` for the off state instead of `{ simple: false }`, so a
 * plain `/chat/:id` stays byte-identical to the link the product produced
 * before this existed. Only the non-default state is written down.
 */
export interface ShellSearch {
	simple?: true;
}

export const Route = createFileRoute("/_shell")({
	// Hand-written rather than a schema library: one optional flag does not
	// justify a dependency, and this states the contract in fewer lines than
	// configuring one would take. Anything unrecognised is dropped, so a
	// hand-edited or truncated URL degrades to the default rather than throwing.
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
