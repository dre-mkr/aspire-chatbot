import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { AccountControl } from "#/components/auth/AccountControl";
import {
	ClockIcon,
	DownloadIcon,
	MoreIcon,
	PanelLeftIcon,
	PencilIcon,
	PlusIcon,
	RetryIcon,
} from "#/components/icons";
import {
	displayTitle,
	type HistoryGroup,
	type StoredConversation,
} from "#/lib/aspire/history";
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
	history: Array<HistoryGroup>;
	activeThreadId: string | null;
	onToggle: () => void;
	onNewChat: () => void;
	onOpenPast: (conversation: StoredConversation) => void;
	/** Writes one conversation out as a text file — any of them, not just the open one. */
	onSaveConversation: (conversation: StoredConversation) => void;
	onRenameConversation: (conversation: StoredConversation, title: string) => void;
	onRegenerateTitle: (conversation: StoredConversation) => void;
}

export function Rail({
	collapsed,
	unreachable,
	history,
	activeThreadId,
	onToggle,
	onNewChat,
	onOpenPast,
	onSaveConversation,
	onRenameConversation,
	onRegenerateTitle,
}: RailProps) {
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

			<div className="rail__body">
				{/* Not a heading: the rail is a labelled landmark, and a heading here
				    would sit above the page's own h1 in document order. */}
				<p className="rail__section-label">
					<span className="rail__section-glyph">
						<ClockIcon />
					</span>
					<span className="rail__fold">History</span>
				</p>

				<div className="rail__groups rail__fold" inert={folded}>
					{history.length === 0 ? (
						<p className="rail__empty">
							Your conversations will appear here once you ask something.
						</p>
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
}: {
	conversation: StoredConversation;
	active: boolean;
	onOpen: (conversation: StoredConversation) => void;
	onSave: (conversation: StoredConversation) => void;
	onRename: (conversation: StoredConversation, title: string) => void;
	onRegenerate: (conversation: StoredConversation) => void;
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
	const menuId = useId();
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);

	// The same stored title the bar reads, with the same fallback applied.
	const label = displayTitle(conversation);

	useEffect(() => {
		if (!renaming) return;
		inputRef.current?.focus();
		inputRef.current?.select();
	}, [renaming]);

	const menuRef = useRef<HTMLDivElement>(null);

	const place = () => {
		const trigger = triggerRef.current;
		if (!trigger) return;
		const r = trigger.getBoundingClientRect();
		setAt({
			top: r.bottom + 4,
			left: Math.min(r.right - 168, window.innerWidth - 176),
		});
	};

	/**
	 * Corrects the position against the menu's real height, once it exists.
	 *
	 * `place` used to flip against a hardcoded 56px. The menu carries three
	 * items now and measures ~134px, so the estimate was 78px short: on the last
	 * row at 320x568 it overshot the viewport by 53.8px and "Save chat" sat
	 * below the fold, unreachable, because a fixed element cannot be scrolled
	 * to. Measuring removes the constant that has to be remembered.
	 */
	useLayoutEffect(() => {
		const menu = menuRef.current;
		const trigger = triggerRef.current;
		if (!open || !menu || !trigger || !at) return;

		const h = menu.getBoundingClientRect().height;
		const r = trigger.getBoundingClientRect();
		const wanted =
			r.bottom + 4 + h > window.innerHeight - 8
				? Math.max(8, r.top - h - 4)
				: r.bottom + 4;
		if (Math.abs(wanted - at.top) > 1) setAt({ ...at, top: wanted });
	}, [open, at]);

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

			{open && at ? (
				<div
					className="row-menu"
					ref={menuRef}
					id={menuId}
					role="group"
					aria-label={`Actions for ${label}`}
					style={{ top: at.top, left: at.left }}
				>
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
				</div>
			) : null}
		</div>
	);
}
