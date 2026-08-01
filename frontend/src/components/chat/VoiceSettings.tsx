import { useEffect, useId, useRef, useState } from "react";
import { InfoIcon, SlidersIcon } from "#/components/icons";
import { useMediaQuery } from "#/lib/use-media-query";
import type { VoiceLanguage } from "#/lib/aspire/voice";

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

		const onPointer = (event: PointerEvent) => {
			if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
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

			{open ? (
				<>
					{/* The sheet needs something to dismiss against on touch, where
					    there is no pointer to click "outside" with as reliably. */}
					{compact ? (
						<button
							type="button"
							className="voice-sheet-scrim"
							onClick={() => setOpen(false)}
						>
							<span className="sr-only">Close voice settings</span>
						</button>
					) : null}

					{/* A plain group, not role="menu". An ARIA menu promises its
					    children are menuitems and that arrow keys move between them;
					    these are a switch, two sets of toggle buttons and a link, and
					    announcing them as a menu describes a structure that is not
					    there. The heading names the group instead. */}
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
				</>
			) : null}
		</div>
	);
}
