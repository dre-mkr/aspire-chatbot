import { useEffect, useRef, useState } from "react";
import {
	ChevronDownIcon,
	DownloadIcon,
	InfoIcon,
	MenuIcon,
} from "#/components/icons";
import type { Phase } from "#/lib/aspire/use-conversation";
import type { VoiceLanguage } from "#/lib/aspire/voice";

interface TopBarProps {
	phase: Phase;
	/** Rail is a drawer, so the bar owns the control that opens it. */
	compact: boolean;
	drawerOpen: boolean;
	onOpenRail: () => void;
	/** Writes the conversation out as a text file. Absent with nothing to save. */
	onSaveChat: (() => void) | null;
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

const SPEEDS = ["0.75", "1", "1.25", "1.5"] as const;
const LANGUAGES: Array<{ code: VoiceLanguage; name: string }> = [
	{ code: "en", name: "English" },
	{ code: "es", name: "Español" },
	{ code: "fr", name: "Français" },
];

export function TopBar({
	phase,
	compact,
	drawerOpen,
	onOpenRail,
	onSaveChat,
	voice,
}: TopBarProps) {
	const inChat = phase === "chat";
	const [menuOpen, setMenuOpen] = useState(false);
	const menuRef = useRef<HTMLDivElement>(null);

	// A menu that outlives a click elsewhere, or Escape, is a trap.
	useEffect(() => {
		if (!menuOpen) return;

		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") setMenuOpen(false);
		};
		const onPointer = (event: PointerEvent) => {
			if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
		};

		window.addEventListener("keydown", onKey);
		window.addEventListener("pointerdown", onPointer);
		return () => {
			window.removeEventListener("keydown", onKey);
			window.removeEventListener("pointerdown", onPointer);
		};
	}, [menuOpen]);

	return (
		<header className="topbar">
			{compact && inChat ? (
				<button
					type="button"
					className="chip-btn chip-btn--square"
					onClick={onOpenRail}
					aria-controls="aspire-rail"
					aria-expanded={drawerOpen}
				>
					<MenuIcon />
					<span className="sr-only">Open conversations</span>
				</button>
			) : null}

			<div className="topbar__model" ref={menuRef}>
				<button
					type="button"
					className="chip-btn chip-btn--model"
					onClick={() => setMenuOpen((open) => !open)}
					aria-expanded={menuOpen}
					aria-controls="aspire-voice-settings"
				>
					<span className="model-dot" aria-hidden="true" />
					ASPIRE AI
					<ChevronDownIcon style={{ opacity: 0.6 }} />
				</button>

				{menuOpen ? (
					/* A plain group, not role="menu". An ARIA menu promises its
					   children are menuitems and that arrow keys move between them;
					   these are a switch, two sets of toggle buttons and a link, and
					   announcing them as a menu describes a structure that is not
					   there. The heading names the group instead. */
					<div
						className="voice-menu"
						id="aspire-voice-settings"
						role="group"
						aria-label="Voice settings"
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
								setMenuOpen(false);
								voice.reviewConsent();
							}}
						>
							<InfoIcon />
							What we do with your voice
						</button>
					</div>
				) : null}
			</div>

			<p className="topbar__caption">
				Financial literacy assistant · St. Kitts and Nevis
			</p>

			<div className="topbar__end">
				{inChat && onSaveChat ? (
					<button type="button" className="chip-btn" onClick={onSaveChat}>
						<DownloadIcon />
						Save chat
					</button>
				) : null}
			</div>
		</header>
	);
}
