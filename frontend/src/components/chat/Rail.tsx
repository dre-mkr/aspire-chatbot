import { useQuery } from "@tanstack/react-query";
import {
	useEffect,
	useId,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import {
	ClockIcon,
	DownloadIcon,
	MoreIcon,
	PanelLeftIcon,
	PencilIcon,
	PlusIcon,
	RetryIcon,
	TrashIcon,
} from "#/components/icons";
import {
	displayTitle,
	groupByRecency,
	type StoredConversation,
} from "#/lib/aspire/history";
import { conversationsQuery } from "#/lib/aspire/queries";
import { useSession } from "#/lib/aspire/use-session";
import { Crossfade } from "./Crossfade";

interface RailProps {
	/** Desktop: icon-only rail. Compact: drawer is closed. */
	collapsed: boolean;
	/**
	 * The rail is off-screen entirely — collapsed to zero width on the landing
	 * screen, or closed as a drawer. It is only hidden visually, so without this
	 * its controls stay in the tab order and focus vanishes into nothing.
	 */
	unreachable: boolean;
	activeThreadId: string | null;
	onToggle: () => void;
	onNewChat: () => void;
	onOpenPast: (conversation: StoredConversation) => void;
	/** Writes one conversation out as a text file — any of them, not just the open one. */
	onSaveConversation: (conversation: StoredConversation) => void;
	onRenameConversation: (
		conversation: StoredConversation,
		title: string,
	) => void;
	onRegenerateTitle: (conversation: StoredConversation) => void;
	/** Permanent, and confirmed in the row's own menu before it is called. */
	onDeleteConversation: (conversation: StoredConversation) => void;
}

export function Rail({
	collapsed,
	unreachable,
	activeThreadId,
	onToggle,
	onNewChat,
	onOpenPast,
	onSaveConversation,
	onRenameConversation,
	onRegenerateTitle,
	onDeleteConversation,
}: RailProps) {
	/**
	 * The list, subscribed here rather than passed in.
	 *
	 * It used to be read in `use-conversation` — the hook that owns the whole
	 * chat surface — and threaded down as a prop, so every write to the list
	 * re-rendered the transcript as well as the rail. Nothing else draws these
	 * rows, so nothing else needs to hear about them changing.
	 */
	const { session } = useSession();
	const conversations = useQuery(conversationsQuery(session?.userId ?? "anon"));
	const history = useMemo(
		() => groupByRecency(conversations.data ?? []),
		[conversations.data],
	);

	// Anything folded away has to leave the tab order too, or focus lands on
	// controls nobody can see.
	const folded = collapsed || undefined;

	return (
		<aside
			className="rail"
			id="aspire-rail"
			aria-label="Conversations"
			inert={unreachable || undefined}
		>
			<div className="rail__head">
				{/* One logo at a time, but both always mounted.
				    They share a single fixed-height cell and crossfade, so the swap
				    cannot change the header's height while the rail's width is
				    animating — the two would read as separate movements. */}
				<div className="rail__logo">
					{/* The A mark IS the toggle, and only in the collapsed rail: at
					    76px there is no room for a control beside it. Not
					    hover-gated — it is a real button at all times it is shown,
					    so it is reachable by keyboard and takes a focus ring.
					    Inert while expanded, because a control faded to zero opacity
					    is still focusable and would be a tab stop leading nowhere. */}
					<button
						type="button"
						className="rail__mark"
						onClick={onToggle}
						aria-controls="aspire-rail"
						aria-expanded={!collapsed}
						inert={!collapsed || undefined}
					>
						{/* alt="" on purpose: the button's own label says what it does,
						    and the wordmark beside it is what carries the brand name.
						    Naming both would announce ASPIRE twice. */}
						<img src="/brand/aspire-mark.png" alt="" width={40} height={40} />
						<span className="sr-only">Expand sidebar</span>
					</button>

					{/* Opacity alone does not remove a thing from the accessibility
					    tree, so the hidden state is stated rather than implied. */}
					<img
						className="rail__wordmark"
						src="/brand/aspire-wordmark.png"
						alt="ASPIRE"
						width={190}
						height={48}
						aria-hidden={collapsed || undefined}
					/>
				</div>

				<button
					type="button"
					className="icon-btn rail__fold rail__collapse"
					onClick={onToggle}
					inert={folded}
				>
					<PanelLeftIcon />
					<span className="sr-only">Collapse sidebar</span>
				</button>
			</div>

			<div className="rail__new">
				<button type="button" className="btn-new" onClick={onNewChat}>
					<span className="btn-new__glyph">
						<PlusIcon />
					</span>
					<span className="rail__fold">New chat</span>
				</button>
			</div>

			{/* `tabIndex={-1}` while folded, and only while folded.

			    This is the scroll container, and Chrome gives a scrollable element
			    its own tab stop so a keyboard can scroll it. When the rail is
			    collapsed everything inside is `inert` and correctly skipped — but
			    the scroller itself is not inert, so focus landed on it and one Tab
			    press appeared to do nothing at all. Measured as a dead stop at
			    position 3 of the cycle.

			    Not inert, because that would also hide the section label from
			    assistive technology; and not permanently -1, because when the rail
			    IS open this stop is doing its job — a long history needs to be
			    scrollable by keyboard. */}
			<div className="rail__body" tabIndex={folded ? -1 : undefined}>
				{/* Not a heading: the rail is a labelled landmark, and a heading here
				    would sit above the page's own h1 in document order. */}
				<p className="rail__section-label">
					<span className="rail__section-glyph">
						<ClockIcon />
					</span>
					<span className="rail__fold">History</span>
				</p>

				{/* Four states, not two.

				    Every one of these used to render as the settled-empty message.
				    No component read a Query status flag anywhere in the product, so
				    "still loading" and "you have no conversations" were the same
				    screen — on a slow connection the rail asserted there was nothing
				    here and then popped rows in, and a failed load was invisible with
				    no way to ask again.

				    The error case still does not throw anything in the reader's face:
				    history failing to load is not worth a dialog, and the rail showing
				    what it has is the right default. What it now also does is say so
				    quietly and offer the retry. */}
				<div className="rail__groups rail__fold" inert={folded}>
					{conversations.isPending ? (
						<div className="rail__skeleton" aria-hidden="true">
							<i />
							<i />
							<i />
						</div>
					) : history.length === 0 ? (
						conversations.isError ? (
							<p className="rail__empty">
								Your conversations could not be loaded.{" "}
								<button
									type="button"
									className="rail__retry"
									onClick={() => void conversations.refetch()}
								>
									Try again
								</button>
							</p>
						) : (
							<p className="rail__empty">
								Your conversations will appear here once you ask something.
							</p>
						)
					) : (
						history.map((group) => (
							<section key={group.label} aria-label={group.label}>
								<p className="rail__group-title">{group.label}</p>
								{group.items.map((conversation) => (
									<HistoryRow
										key={conversation.threadId}
										conversation={conversation}
										active={conversation.threadId === activeThreadId}
										onOpen={onOpenPast}
										onSave={onSaveConversation}
										onRename={onRenameConversation}
										onRegenerate={onRegenerateTitle}
										onDelete={onDeleteConversation}
									/>
								))}
							</section>
						))
					)}
				</div>
			</div>

			{/* One block, two states: signed out it invites you in, signed in it
			    is the avatar, the name and the address. Same padding, same icon
			    slot, same two lines either way — see `AccountControl`. */}
			<div className="rail__foot">
				<AccountControl variant="rail" />
			</div>
		</aside>
	);
}

/**
 * One conversation in the rail, with its own overflow menu.
 *
 * "Save chat" used to be a button in the top bar that wrote out whichever
 * conversation happened to be open. Attached to a row instead, it can save any
 * conversation on the device — and the action now says which one it means.
 *
 * The trigger is always in the DOM and always focusable, revealed on hover,
 * focus-within, or while its own menu is open. A control that only exists on
 * hover does not exist for a keyboard or a touchscreen.
 */
function HistoryRow({
	conversation,
	active,
	onOpen,
	onSave,
	onRename,
	onRegenerate,
	onDelete,
}: {
	conversation: StoredConversation;
	active: boolean;
	onOpen: (conversation: StoredConversation) => void;
	onSave: (conversation: StoredConversation) => void;
	onRename: (conversation: StoredConversation, title: string) => void;
	onRegenerate: (conversation: StoredConversation) => void;
	onDelete: (conversation: StoredConversation) => void;
}) {
	const [open, setOpen] = useState(false);
	/**
	 * Viewport coordinates for the menu.
	 *
	 * The menu is `position: fixed` rather than absolute, because the rail body
	 * is a scroll container and an absolutely positioned child is clipped by it —
	 * measured at 50px cut off and unreachable on the last row of a scrolled
	 * list. Fixed positioning escapes the clip; these coordinates put it back
	 * against its trigger, flipping above when there is no room below.
	 */
	const [at, setAt] = useState<{ top: number; left: number } | null>(null);
	const [renaming, setRenaming] = useState(false);
	/**
	 * The menu's second face: are you sure?
	 *
	 * A step inside the menu rather than a modal over the page, because the
	 * question is about this row and belongs against it — and because the app
	 * has no dialog anywhere else, so this would be the one thing that dimmed
	 * the whole screen. What it must NOT be is nothing at all: deleting is
	 * permanent, the trigger is a 30px target sitting on top of the row you
	 * click to open a chat, and there is no undo behind it.
	 */
	const [confirming, setConfirming] = useState(false);
	const menuId = useId();
	/** The confirmation's sentence, which is also the menu's accessible name. */
	const askId = `${menuId}-ask`;
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const cancelRef = useRef<HTMLButtonElement>(null);

	// The same stored title the bar reads, with the same fallback applied.
	const label = displayTitle(conversation);

	useEffect(() => {
		if (!renaming) return;
		inputRef.current?.focus();
		inputRef.current?.select();
	}, [renaming]);

	// The question replaces the items, so the item that was clicked unmounts and
	// focus would fall to the body — inside a popover the reader can no longer
	// reach or dismiss. It lands on Cancel rather than on Delete: the confirm
	// exists to catch a mis-tap, and a focused destructive button that a held
	// Enter key can repeat into is not catching anything.
	useEffect(() => {
		if (confirming) cancelRef.current?.focus();
	}, [confirming]);

	// Asking again next time. Closing the menu — by Escape, by clicking away, by
	// scrolling the rail — is a "no", and reopening it must not resume mid-answer.
	useEffect(() => {
		if (!open) setConfirming(false);
	}, [open]);

	const menuRef = useRef<HTMLDivElement>(null);

	/**
	 * A first guess, so the menu has somewhere to be while it is being measured.
	 *
	 * Deliberately not a width calculation any more. It used to subtract a
	 * hardcoded 168 — the menu's old min-width — which is a copy of a number
	 * that lives in the stylesheet, kept in step by hand, and it stopped being
	 * true the moment the confirmation made the menu wider. The layout effect
	 * below measures the real box and re-anchors it before the browser paints,
	 * so nothing here is ever seen and nothing here has to be right.
	 */
	const place = () => {
		const trigger = triggerRef.current;
		if (!trigger) return;
		const r = trigger.getBoundingClientRect();
		setAt({ top: r.bottom + 4, left: r.left });
	};

	/**
	 * Corrects the position against the menu's real height, once it exists.
	 *
	 * `place` used to flip against a hardcoded 56px. The menu carries four items
	 * now, so the estimate was well short: on the last row at 320x568 it
	 * overshot the viewport by 53.8px and the bottom item sat below the fold,
	 * unreachable, because a fixed element cannot be scrolled to. Measuring
	 * removes the constant that has to be remembered.
	 *
	 * The width is corrected here too, and for the same reason: `place` assumes
	 * 168px, which was the menu's min-width and stopped being its real width the
	 * moment the confirmation put a sentence in it. A wider menu placed by that
	 * estimate hangs off the right edge by exactly the difference.
	 *
	 * `confirming` is a dependency because that swap is what changes both
	 * measurements under a menu that is already placed.
	 */
	// biome-ignore lint/correctness/useExhaustiveDependencies: confirming is the trigger, not an input — the effect re-measures the DOM it changed
	useLayoutEffect(() => {
		const menu = menuRef.current;
		const trigger = triggerRef.current;
		if (!open || !menu || !trigger || !at) return;

		const box = menu.getBoundingClientRect();
		const r = trigger.getBoundingClientRect();
		const top =
			r.bottom + 4 + box.height > window.innerHeight - 8
				? Math.max(8, r.top - box.height - 4)
				: r.bottom + 4;
		const left = Math.max(
			8,
			Math.min(r.right - box.width, window.innerWidth - box.width - 8),
		);
		if (Math.abs(top - at.top) > 1 || Math.abs(left - at.left) > 1) {
			setAt({ top, left });
		}
	}, [open, at, confirming]);

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			event.stopPropagation();
			setOpen(false);
			triggerRef.current?.focus();
		};
		const onPointer = (event: PointerEvent) => {
			if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
		};
		// Fixed coordinates stop being true the moment anything moves, so the
		// menu closes rather than drifting away from the row it belongs to.
		const onMove = () => setOpen(false);

		window.addEventListener("keydown", onKey, true);
		window.addEventListener("pointerdown", onPointer);
		window.addEventListener("resize", onMove);
		document
			.querySelector(".rail__body")
			?.addEventListener("scroll", onMove, { passive: true });
		return () => {
			window.removeEventListener("keydown", onKey, true);
			window.removeEventListener("pointerdown", onPointer);
			window.removeEventListener("resize", onMove);
			document
				.querySelector(".rail__body")
				?.removeEventListener("scroll", onMove);
		};
	}, [open]);

	return (
		<div className="history-row" ref={wrapRef} data-open={open || undefined}>
			{renaming ? (
				<input
					ref={inputRef}
					className="history-item history-item--input"
					defaultValue={label}
					maxLength={60}
					aria-label={`Rename ${label}`}
					onBlur={(event) => {
						setRenaming(false);
						const next = event.target.value.trim();
						if (next && next !== label) onRename(conversation, next);
					}}
					onKeyDown={(event) => {
						if (event.key === "Enter") {
							event.preventDefault();
							event.currentTarget.blur();
						} else if (event.key === "Escape") {
							event.preventDefault();
							setRenaming(false);
						}
					}}
				/>
			) : (
				<button
					type="button"
					className="history-item"
					aria-current={active}
					title={label}
					onClick={() => onOpen(conversation)}
				>
					{/* The row is written the moment a chat is sent, carrying the
					    truncated question, and the generated title lands on top of it
					    seconds later. The title bar has always dissolved that swap;
					    the row popped. Same duration, so the two surfaces change
					    together rather than one chasing the other. */}
					<Crossfade text={label} />
				</button>
			)}

			<button
				type="button"
				ref={triggerRef}
				className="history-more"
				aria-expanded={open}
				aria-controls={menuId}
				aria-label={`Actions for ${label}`}
				onClick={() => {
					if (!open) place();
					setOpen((value) => !value);
				}}
			>
				<MoreIcon />
			</button>

			{/* The rule below suggests <fieldset>, which groups form CONTROLS inside
			    a form. This is a positioned popover of actions -- rename, save,
			    regenerate, delete -- with no form anywhere near it, and a fieldset's
			    own box model would land inside a fixed-position menu whose geometry
			    is measured. role="group" with a label is what a screen reader needs. */}
			{open && at ? (
				// biome-ignore lint/a11y/useSemanticElements: a popover of actions, not a form control group
				<div
					className="row-menu"
					ref={menuRef}
					id={menuId}
					role="group"
					// While the question is up the group is named BY the question, so
					// moving focus into it announces what is being confirmed rather
					// than the bare words "Keep this chat" — and so the sentence exists
					// once rather than as visible copy plus a paraphrase of it.
					aria-labelledby={confirming ? askId : undefined}
					aria-label={confirming ? undefined : `Actions for ${label}`}
					style={{ top: at.top, left: at.left }}
				>
					{confirming ? (
						/* The same two-step the account menu uses to confirm a sign-out:
						   one sentence saying what actually happens, then the two
						   answers as plain menu items — no icons, so the pair aligns and
						   neither answer is dressed up as the obvious one. Matching that
						   rather than inventing a second confirmation shape: a product
						   with two ways of asking "are you sure" has taught nobody
						   anything. */
						<>
							{/* Named, not "this chat". The trigger is a 30px target on a
							    row that is itself a button, and the menu is positioned
							    away from the row it belongs to, so the question has to
							    say which conversation it means. */}
							<p className="row-menu__confirm" id={askId}>
								Delete “{label}”? The whole conversation goes, and it cannot be
								brought back.
							</p>
							<button
								type="button"
								className="row-menu__item row-menu__item--danger"
								onClick={() => {
									setOpen(false);
									onDelete(conversation);
								}}
							>
								Yes, delete
							</button>
							<button
								type="button"
								ref={cancelRef}
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									triggerRef.current?.focus();
								}}
							>
								Keep this chat
							</button>
						</>
					) : (
						<>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									setRenaming(true);
								}}
							>
								<PencilIcon />
								Rename
							</button>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									onRegenerate(conversation);
								}}
							>
								<RetryIcon />
								Regenerate title
							</button>
							<button
								type="button"
								className="row-menu__item"
								onClick={() => {
									setOpen(false);
									onSave(conversation);
								}}
							>
								<DownloadIcon />
								Save chat
							</button>
							{/* Last, and separated. Everything above it is reversible
							    or additive; this one is not, and it must not sit a
							    stray pixel away from "Save chat" in a menu people
							    open to save things. */}
							<button
								type="button"
								className="row-menu__item row-menu__item--danger"
								onClick={() => setConfirming(true)}
							>
								<TrashIcon />
								Delete
							</button>
						</>
					)}
				</div>
			) : null}
		</div>
	);
}
