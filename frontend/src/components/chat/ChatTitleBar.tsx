import { useEffect, useRef, useState } from "react";
import { MenuIcon } from "#/components/icons";

/**
 * The chat's title bar.
 *
 * Deliberately not a revival of the old model-pill bar: it carries the title
 * and, on small screens, the drawer trigger. Voice settings and Save chat stay
 * where they were moved to.
 *
 * Translucent and blurred rather than solid, so the transcript scrolls under it
 * and the thread's existing top fade still has something to dissolve into —
 * a fade sitting under an opaque bar would be doing nothing.
 */

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
	/**
	 * The title as it stood when the editor opened.
	 *
	 * `commit` used to diff the draft against the *current* title -- which moves
	 * when the generated name lands. Opening the box during generation and then
	 * pressing Enter without typing therefore looked like an edit, wrote the
	 * stale truncated question back, and locked it `manual` so regeneration
	 * could never fix it. Diffing against the value the user actually saw makes
	 * "changed nothing" a no-op however the title moved underneath.
	 */
	const openedWith = useRef(title);
	const inputRef = useRef<HTMLInputElement>(null);

	/**
	 * The title being replaced, kept only for as long as the crossfade runs.
	 *
	 * The first message stands in until the generated title lands, and the swap
	 * has to dissolve rather than pop. Both sit in the same grid cell so the
	 * outgoing one cannot change the bar's height on its way out.
	 */
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
			) : (
				<button
					type="button"
					className="titlebar__title"
					title={title}
					onClick={() => {
						setDraft(title);
						openedWith.current = title;
						setEditing(true);
					}}
				>
					{/* Both layers occupy one grid cell, so the crossfade cannot
					    shift the bar or the thread beneath it. */}
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
