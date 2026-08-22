/**
 * "My Journey" in the rail, opening the journey rather than asking about it.
 *
 * The button said My Journey and seeded the message "How am I doing so far?".
 * That is a reasonable turn to take and it is not what the label promises: the
 * Journey page exists, it is written, and from inside a conversation there was
 * no way to reach it. `JourneyView` was rendered from exactly one place --
 * `LandingScreen`, behind local `activeView` state -- so it is not a route and
 * the rail had nothing to link to.
 *
 * A panel rather than a navigation, for the same reason `VideoLauncher` is one:
 * leaving chat to look at a page costs the reader the conversation they are in.
 * The dialog mechanics here are `VideoLauncher`'s, deliberately -- portal,
 * scrim, focus trap, Escape, and focus returned to the trigger -- because two
 * dialogs in one rail that behave differently is worse than the duplication.
 *
 * `JourneyView` takes `onBack` and nothing else, so it drops in unchanged. It
 * is its own dark full-height surface with its own header, which is why this
 * does not wrap it in `help__panel` the way the video library is wrapped.
 */

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { JourneyView } from "#/components/landing/JourneyView";

export function JourneyLauncher() {
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
				className="btn-help btn-journey"
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? dialogId : undefined}
				onClick={() => setOpen(true)}
			>
				<span className="btn-help__glyph" aria-hidden="true">
					<i className="ph-duotone ph-medal" />
				</span>
				<span className="rail__fold">My Journey</span>
			</button>

			{open && mounted
				? createPortal(
						<div className="help journey-panel">
							<button
								type="button"
								className="help__scrim"
								onClick={() => setOpen(false)}
								tabIndex={-1}
							>
								<span className="sr-only">Close</span>
							</button>

							<div
								className="journey-panel__surface"
								id={dialogId}
								ref={panelRef}
								role="dialog"
								aria-modal="true"
								aria-label="Your financial journey"
							>
								{/* `onBack` closes the panel. On the landing page the same
								    prop returns to the landing, which is the right thing
								    there and would be a dead end here. */}
								<JourneyView onBack={() => setOpen(false)} backLabel="Back to chat" />
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}
