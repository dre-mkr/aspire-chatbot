/**
 * A rail button that opens one of the landing page's section views in place.
 *
 * The section views -- Journey, Parents, Educators -- are rendered from exactly
 * one place, `LandingScreen`, behind local `activeView` state. None of them is
 * a route, so from inside a conversation they were written, reachable from the
 * landing, and unreachable from the chat where most readers actually are.
 *
 * A panel rather than a navigation, for the reason `VideoLauncher` is one:
 * leaving chat to read a page costs the reader the conversation they are in. A
 * parent halfway through asking about eligibility should be able to check the
 * guardians page and come back to their own thread, not to a fresh one.
 *
 * GENERIC BECAUSE THE THIRD COPY IS WHERE THIS GOES WRONG. Journey, Parents and
 * Educators need identical dialog behaviour -- portal, scrim, focus trap,
 * Escape, focus returned to the trigger -- and three hand-written copies drift:
 * one grows a focus trap the others lack, one forgets to restore focus, and the
 * rail ends up with buttons that behave differently for no reason a reader
 * could name. `VideoLauncher` stays separate on purpose: it fetches a catalog
 * and pauses playing media on close, neither of which belongs here.
 *
 * `children` is a render prop rather than an element so the view is not
 * constructed until the panel opens -- these are whole pages, and building
 * three of them on every chat render to keep them hidden is work nobody asked
 * for.
 */

import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ViewLauncherProps {
	/** What the rail shows, folded and unfolded. */
	label: string;
	/** A phosphor class, e.g. `ph-duotone ph-medal`. */
	icon: string;
	/** Spoken instead of the label, where the label alone is not a whole sentence. */
	ariaLabel?: string;
	/** Names the dialog for a screen reader. */
	dialogLabel: string;
	/** Extra class on the trigger, for anything that needs its own hook. */
	triggerClassName?: string;
	/** The view, given the function that closes the panel. */
	children: (close: () => void) => ReactNode;
}

export function ViewLauncher({
	label,
	icon,
	ariaLabel,
	dialogLabel,
	triggerClassName = "",
	children,
}: ViewLauncherProps) {
	const [open, setOpen] = useState(false);
	const [mounted, setMounted] = useState(false);
	const dialogId = useId();
	const triggerRef = useRef<HTMLButtonElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	const returnFocusTo = useRef<HTMLElement | null>(null);

	// The portal is client-only: during SSR there is no document to look for.
	useEffect(() => setMounted(true), []);

	useEffect(() => {
		if (!open) return;

		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.stopPropagation();
				setOpen(false);
				return;
			}
			if (event.key !== "Tab") return;

			const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
				'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
			);
			if (!focusable || focusable.length === 0) return;
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (event.shiftKey && document.activeElement === first) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		};

		window.addEventListener("keydown", onKey, true);
		return () => window.removeEventListener("keydown", onKey, true);
	}, [open]);

	// Focus in on open, and back where it came from on close.
	useEffect(() => {
		if (open) {
			returnFocusTo.current = document.activeElement as HTMLElement | null;
			panelRef.current?.querySelector<HTMLElement>("button")?.focus();
			return;
		}
		returnFocusTo.current?.focus?.();
		returnFocusTo.current = null;
	}, [open]);

	return (
		<>
			<button
				ref={triggerRef}
				type="button"
				className={`btn-help ${triggerClassName}`.trim()}
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? dialogId : undefined}
				aria-label={ariaLabel}
				onClick={() => setOpen(true)}
			>
				<span className="btn-help__glyph" aria-hidden="true">
					<i className={icon} />
				</span>
				<span className="rail__fold">{label}</span>
			</button>

			{open && mounted
				? createPortal(
						<div className="help view-panel">
							<button
								type="button"
								className="help__scrim"
								onClick={() => setOpen(false)}
								tabIndex={-1}
							>
								<span className="sr-only">Close</span>
							</button>

							<div
								className="view-panel__surface"
								id={dialogId}
								ref={panelRef}
								role="dialog"
								aria-modal="true"
								aria-label={dialogLabel}
							>
								{children(() => setOpen(false))}
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}
