import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { InfoIcon, SlidersIcon } from "#/components/icons";
import type { VoiceLanguage } from "#/lib/aspire/voice";
import { useMediaQuery } from "#/lib/use-media-query";

/** Voice and language settings, and the control that opens them. */

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
		autoLanguage: boolean;
		gameSound: boolean;
		overlay: string;
		toggleAutoSpeak: () => void;
		setSpeed: (value: string) => void;
		setLanguage: (value: VoiceLanguage) => void;
		enableAutoLanguage: () => void;
		toggleGameSound: () => void;
		setOverlay: (value: string) => void;
		reviewConsent: () => void;
	};
}

/** The personality overlays a reader may choose. "" is the guide as written. */
const OVERLAYS: ReadonlyArray<{ key: string; label: string }> = [
	{ key: "", label: "Classic" },
	{ key: "coach", label: "🏆 The Coach" },
	{ key: "limer", label: "😎 The Limer" },
	{ key: "professor", label: "🤓 The Professor" },
	{ key: "storyteller", label: "📖 The Storyteller" },
	{ key: "hype", label: "🎉 The Party Animal" },
	{ key: "quiet", label: "🌙 The Lowkey" },
	{ key: "hustler", label: "💼 The Hustler" },
];

export function VoiceSettings({ voice }: VoiceSettingsProps) {
	const [open, setOpen] = useState(false);
	const panelId = useId();
	const wrapRef = useRef<HTMLDivElement>(null);
	const triggerRef = useRef<HTMLButtonElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	const compact = useMediaQuery(COMPACT);

	// The portal is client-only: during SSR there is no document to look for.
	const [mounted, setMounted] = useState(false);
	useEffect(() => setMounted(true), []);

	const close = () => setOpen(false);

	// Escape closes and hands focus back; a pointer outside closes without stealing it.
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

			// Focus stays inside while it is open.
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

		// The sheet is portalled out, so "inside" means the trigger's wrapper or the panel.
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

	// Move focus in on open, so the trap has something to hold.
	useEffect(() => {
		if (!open) return;
		panelRef.current?.querySelector<HTMLElement>("button")?.focus();
	}, [open]);

	/* A plain group, not role="menu". */
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

			{/* Not gated on `voice.available`: the games make their own sound in
			    the browser and do not go anywhere near the speech service, so a
			    deployment with voice switched off still has this to turn down. */}
			<div className="voice-menu__row">
				<span className="voice-menu__copy">
					<span className="voice-menu__title">Game sounds</span>
					<span className="voice-menu__sub">
						Coins and cheers while you play.
					</span>
				</span>
				<button
					type="button"
					className="voice-switch"
					role="switch"
					aria-checked={voice.gameSound}
					aria-label="Game sounds"
					onClick={voice.toggleGameSound}
				>
					<span className="voice-switch__knob" />
				</button>
			</div>

			<hr className="voice-menu__rule" />

			<p className="voice-menu__label">Personality</p>
			<div className="voice-menu__choices voice-menu__choices--wrap">
				{OVERLAYS.map((option) => (
					<button
						key={option.key || "none"}
						type="button"
						className="voice-choice"
						aria-pressed={voice.overlay === option.key}
						onClick={() => voice.setOverlay(option.key)}
					>
						{option.label}
					</button>
				))}
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
				{/*
				  Automatic first, and it is the default. Detection ran on every
				  turn long before there was a control for it; this names the
				  behaviour rather than adding one.

				  It is pressed only when nothing else is. Choosing a language
				  leaves Automatic, because picking Espanol and then being
				  answered in English is the control not working, whatever the
				  menu shows as selected.
				*/}
				<button
					type="button"
					className="voice-choice voice-choice--lang voice-choice--auto"
					aria-pressed={voice.autoLanguage}
					onClick={voice.enableAutoLanguage}
				>
					<span className="voice-choice__code">AUTO</span>
					<span className="voice-choice__name">Automatic</span>
				</button>
				{LANGUAGES.map((option) => (
					<button
						key={option.code}
						type="button"
						className="voice-choice voice-choice--lang"
						aria-pressed={!voice.autoLanguage && voice.language === option.code}
						onClick={() => voice.setLanguage(option.code)}
					>
						<span className="voice-choice__code">
							{option.code.toUpperCase()}
						</span>
						<span className="voice-choice__name">{option.name}</span>
					</button>
				))}
			</div>
			{voice.autoLanguage ? (
				<p className="voice-menu__hint">
					Answers follow the language you write in. Currently{" "}
					{LANGUAGES.find((l) => l.code === voice.language)?.name ?? "English"}.
				</p>
			) : null}

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

			{/* Sheet: portalled to the body. */}
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
