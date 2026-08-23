import { useEffect, useRef, useState } from "react";
import { MenuIcon } from "#/components/icons";

/** The chat's title bar. */

export interface ChatTitleBarProps {
	title: string;
	/** Renders the drawer trigger here instead of floating it over the thread. */
	showDrawerTrigger: boolean;
	drawerOpen: boolean;
	onOpenRail: () => void;
	onRename: (title: string) => void;
}

export function ChatTitleBar({
	title,
	showDrawerTrigger,
	drawerOpen,
	onOpenRail,
	onRename,
}: ChatTitleBarProps) {
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState(title);
	/** The title as it stood when the editor opened. */
	const openedWith = useRef(title);
	const inputRef = useRef<HTMLInputElement>(null);

	/** The title being replaced, kept only for as long as the crossfade runs. */
	const [outgoing, setOutgoing] = useState<string | null>(null);
	const shown = useRef(title);

	useEffect(() => {
		if (title === shown.current) return;
		setOutgoing(shown.current);
		shown.current = title;
		const timer = setTimeout(() => setOutgoing(null), 320);
		return () => clearTimeout(timer);
	}, [title]);

	useEffect(() => {
		if (!editing) return;
		inputRef.current?.focus();
		inputRef.current?.select();
	}, [editing]);

	function commit() {
		const next = draft.trim();
		setEditing(false);
		if (next && next !== openedWith.current) onRename(next);
	}

	return (
		<header className="titlebar">
			{showDrawerTrigger ? (
				<button
					type="button"
					className="titlebar__menu"
					onClick={onOpenRail}
					aria-controls="aspire-rail"
					aria-expanded={drawerOpen}
				>
					<MenuIcon />
					<span className="sr-only">Open conversations</span>
				</button>
			) : null}

			{editing ? (
				<input
					ref={inputRef}
					className="titlebar__input"
					value={draft}
					maxLength={60}
					aria-label="Rename this chat"
					onChange={(event) => setDraft(event.target.value)}
					onBlur={commit}
					onKeyDown={(event) => {
						if (event.key === "Enter") {
							event.preventDefault();
							commit();
						} else if (event.key === "Escape") {
							event.preventDefault();
							setEditing(false);
							setDraft(title);
						}
					}}
				/>
			) : !title ? (
				/* A new chat has no title until the first answer names it. This
				 * rendered as a full-width, focusable button with no text and no
				 * accessible name — so the first thing a keyboard reader met on
				 * every new conversation was a control announced as "button", with
				 * nothing after it. It is a caption until there is a name to edit. */
				<p className="titlebar__title titlebar__title--empty">New chat</p>
			) : (
				<button
					type="button"
					className="titlebar__title"
					title={title}
					aria-label={`Rename this chat, currently "${title}"`}
					onClick={() => {
						setDraft(title);
						openedWith.current = title;
						setEditing(true);
					}}
				>
					{/* Both layers share one grid cell, so the crossfade cannot shift the bar. */}
					<span className="titlebar__text">{title}</span>
					{outgoing ? (
						<span
							className="titlebar__text titlebar__text--out"
							aria-hidden="true"
						>
							{outgoing}
						</span>
					) : null}
				</button>
			)}
		</header>
	);
}
