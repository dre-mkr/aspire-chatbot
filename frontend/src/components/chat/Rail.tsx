import { useEffect, useId, useRef, useState } from "react";
import {
	ClockIcon,
	DeviceIcon,
	DownloadIcon,
	MoreIcon,
	PanelLeftIcon,
	PlusIcon,
} from "#/components/icons";
import type { HistoryGroup, StoredConversation } from "#/lib/aspire/history";

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
				<button
					type="button"
					className="rail__mark"
					onClick={onToggle}
					aria-controls="aspire-rail"
					aria-expanded={!collapsed}
				>
					<img src="/brand/aspire-mark.png" alt="" width={40} height={40} />
					<span className="sr-only">
						{collapsed ? "Expand sidebar" : "Collapse sidebar"}
					</span>
				</button>

				<img
					className="rail__wordmark rail__fold"
					src="/brand/aspire-wordmark.png"
					alt="ASPIRE"
					width={190}
					height={48}
				/>

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
									/>
								))}
							</section>
						))
					)}
				</div>
			</div>

			{/* There is no account yet, so the foot says where the transcript
			    actually lives rather than dressing up a signed-in user. */}
			<div className="rail__foot">
				<span className="rail__device" aria-hidden="true">
					<DeviceIcon />
				</span>
				<span className="rail__identity rail__fold">
					<span className="rail__name">Not signed in</span>
					<span className="rail__note">Chats are saved on this device</span>
				</span>
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
}: {
	conversation: StoredConversation;
	active: boolean;
	onOpen: (conversation: StoredConversation) => void;
	onSave: (conversation: StoredConversation) => void;
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
	const menuId = useId();
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);

	const place = () => {
		const trigger = triggerRef.current;
		if (!trigger) return;
		const r = trigger.getBoundingClientRect();
		const MENU_H = 56;
		const below = window.innerHeight - r.bottom;
		setAt({
			top: below < MENU_H + 12 ? r.top - MENU_H - 4 : r.bottom + 4,
			left: Math.min(r.right - 168, window.innerWidth - 176),
		});
	};

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
			<button
				type="button"
				className="history-item"
				aria-current={active}
				onClick={() => onOpen(conversation)}
			>
				{conversation.title}
			</button>

			<button
				type="button"
				ref={triggerRef}
				className="history-more"
				aria-expanded={open}
				aria-controls={menuId}
				aria-label={`Actions for ${conversation.title}`}
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
					id={menuId}
					role="group"
					aria-label={`Actions for ${conversation.title}`}
					style={{ top: at.top, left: at.left }}
				>
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
