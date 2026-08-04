import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { InfoIcon, SlidersIcon } from "#/components/icons";
import type { VoiceLanguage } from "#/lib/aspire/voice";
import { useMediaQuery } from "#/lib/use-media-query";

/**
 * Voice and language settings, and the control that opens them.
 *
 * Lifted out of the top bar unchanged. It used to hang off a pill labelled
 * "ASPIRE AI" — the product's own name — which is the last place anyone looks
 * for read-aloud, speed and language. It now opens from the composer, beside
 * the tools it belongs with.
 *
 * The panel's contents are the originals: same sections, same order, same
 * copy, same controls. Only the anchor changed, so it opens upward from the
 * composer instead of downward from a bar that no longer exists.
 *
 * The trigger is deliberately a sliders glyph and never a microphone. The mic
 * is two controls to the right and does something else entirely; two
 * microphone-ish buttons in one row would leave neither meaning anything.
 */

const SPEEDS = ["0.75", "1", "1.25", "1.5"] as const;
const LANGUAGES: Array<{ code: VoiceLanguage; name: string }> = [
	{ code: "en", name: "English" },
	{ code: "es", name: "Español" },
	{ code: "fr", name: "Français" },
];

/** Matches the rail's drawer breakpoint, so the sheet and the drawer agree. */
const COMPACT = "(max-width: 860px)";

export interface VoiceSettingsProps {
	voice: {
		available: boolean;
		autoSpeak: boolean;
		speed: string;
		language: VoiceLanguage;
		toggleAutoSpeak: () => void;
		setSpeed: (value: string) => void;
		setLanguage: (value: VoiceLanguage) => void;
		reviewConsent: () => void;
	};
}

export function VoiceSettings({ voice }: VoiceSettingsProps) {
	const [open, setOpen] = useState(false);
	const panelId = useId();
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	const compact = useMediaQuery(COMPACT);

	// The portal only exists on the client; rendering it during SSR would look
	// for a document that is not there.
	const [mounted, setMounted] = useState(false);
	useEffect(() => setMounted(true), []);

	const close = () => setOpen(false);

	// Escape closes and hands focus back; a pointer outside closes without
	// stealing it. Both were true in the top bar and both still have to be.
	useEffect(() => {
		if (!open) return;

		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.stopPropagation();
				setOpen(false);
				triggerRef.current?.focus();
				return;
			}

			if (event.key !== "Tab") return;

			// Focus stays inside while it is open. Without this, Tab walks out of
			// the panel and into the composer underneath it.
			const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
				'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
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

		// The sheet is portalled out of this subtree, so "inside" has to mean
		// either the trigger's wrapper or the panel itself.
		const onPointer = (event: PointerEvent) => {
			const target = event.target as Node;
			if (wrapRef.current?.contains(target)) return;
			if (panelRef.current?.contains(target)) return;
			setOpen(false);
		};

		window.addEventListener("keydown", onKey, true);
		window.addEventListener("pointerdown", onPointer);
		return () => {
			window.removeEventListener("keydown", onKey, true);
			window.removeEventListener("pointerdown", onPointer);
		};
	}, [open]);

	// Move focus in when it opens, so the trap has something to hold and a
	// keyboard user is not left behind on the trigger.
	useEffect(() => {
		if (!open) return;
		panelRef.current?.querySelector<HTMLElement>("button")?.focus();
	}, [open]);

	/*
	 * A plain group, not role="menu". An ARIA menu promises its children are
	 * menuitems and that arrow keys move between them; these are a switch, two
	 * sets of toggle buttons and a link, and announcing them as a menu describes
	 * a structure that is not there. The heading names the group instead.
	 *
	 * Defined once and rendered in one of two places, so the desktop popover and
	 * the mobile sheet can never drift apart.
	 */
	const panel = (
		// biome-ignore lint/a11y/useSemanticElements: a positioned panel, not a form control group (see Rail.tsx)
		<div
			className="voice-menu voice-menu--up"
			id={panelId}
			ref={panelRef}
			role="group"
			aria-label="Voice settings"
			data-sheet={compact || undefined}
		>
			<p className="voice-menu__label">Voice</p>

			<div className="voice-menu__row">
				<span className="voice-menu__copy">
					<span className="voice-menu__title">Read answers aloud</span>
					<span className="voice-menu__sub">
						Starts as each answer arrives.
					</span>
				</span>
				<button
					type="button"
					className="voice-switch"
					role="switch"
					aria-checked={voice.autoSpeak}
					aria-label="Read answers aloud"
					disabled={!voice.available}
					onClick={voice.toggleAutoSpeak}
				>
					<span className="voice-switch__knob" />
				</button>
			</div>

			<hr className="voice-menu__rule" />

			<p className="voice-menu__label">Speed</p>
			<div className="voice-menu__choices">
				{SPEEDS.map((option) => (
					<button
						key={option}
						type="button"
						className="voice-choice"
						aria-pressed={voice.speed === option}
						onClick={() => voice.setSpeed(option)}
					>
						{option}×
					</button>
				))}
			</div>

			<p className="voice-menu__label">Language</p>
			<div className="voice-menu__choices">
				{LANGUAGES.map((option) => (
					<button
						key={option.code}
						type="button"
						className="voice-choice voice-choice--lang"
						aria-pressed={voice.language === option.code}
						onClick={() => voice.setLanguage(option.code)}
					>
						<span className="voice-choice__code">
							{option.code.toUpperCase()}
						</span>
						<span className="voice-choice__name">{option.name}</span>
					</button>
				))}
			</div>

			<button
				type="button"
				className="voice-menu__link"
				onClick={() => {
					setOpen(false);
					voice.reviewConsent();
				}}
			>
				<InfoIcon />
				What we do with your voice
			</button>
		</div>
	);

	return (
		<div className="voice-settings" ref={wrapRef}>
			<button
				type="button"
				ref={triggerRef}
				className="tool-btn tool-btn--icon"
				aria-expanded={open}
				aria-controls={panelId}
				aria-label="Voice and language settings"
				title="Voice and language settings"
				onClick={() => setOpen((value) => !value)}
			>
				<SlidersIcon />
			</button>

			{/* Desktop: anchored to the trigger, so it stays in the subtree. */}
			{open && !compact ? panel : null}

			{/* Sheet: portalled to the body.
			    `.composer` carries `backdrop-filter: blur(20px)`, which makes it
			    the containing block for every `position: fixed` descendant — so a
			    sheet declaring `inset: auto 0 0 0` resolved against the composer's
			    366px box instead of the viewport. It floated 47px above the bottom
			    edge, 26px narrow, with square unbordered corners in mid-air, and
			    its scrim covered 14.4% of the screen instead of all of it. The
			    composer is also the backdrop root, so the sheet's own blur did
			    nothing and the transcript ghosted through it sharp. Leaving the
			    subtree fixes all of that at once. */}
			{open && compact && mounted
				? createPortal(
						<>
							<button
								type="button"
								className="voice-sheet-scrim"
								onClick={close}
							>
								<span className="sr-only">Close voice settings</span>
							</button>
							{panel}
						</>,
						document.body,
					)
				: null}
		</div>
	);
}
