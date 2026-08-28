import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
	CloseIcon,
	InfoIcon,
	MicIcon,
	PersonIcon,
	ShuffleIcon,
	SparkIcon,
} from "#/components/icons";
import { type HelpSection, helpCopy } from "#/lib/aspire/help-copy";
import { currentLocale, say, useLocale } from "#/lib/aspire/i18n";
import { GUIDES } from "#/lib/aspire/personas";

/**
 * "How to use ASPIRE AI" — the launcher and the panel it opens.
 *
 * Self-contained on purpose. Both the landing screen and the chat screen render
 * the rail, so threading `open` state through two pages to reach one button
 * would be two props and a piece of state in each of them; the dialog is
 * portalled to the body and does not care where its trigger sits.
 *
 * The a11y behaviour is the project's existing modal recipe, the one
 * `VoiceSettings` uses: Escape closes, Tab is trapped inside, focus is captured
 * before opening and handed back on close.
 */
export function HelpLauncher() {
	// Re-render when the reader changes language: `say` reads storage,
	// and storage changing is not something React can see on its own.
	useLocale();
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
				className="btn-help"
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? dialogId : undefined}
				onClick={() => setOpen(true)}
			>
				<span className="btn-help__glyph">
					<InfoIcon />
				</span>
				<span className="rail__fold">{say("navHowTo")}</span>
			</button>

			{open && mounted
				? createPortal(
						<div className="help">
							<button
								type="button"
								className="help__scrim"
								onClick={() => setOpen(false)}
								tabIndex={-1}
							>
								<span className="sr-only">Close</span>
							</button>

							<div
								className="help__panel"
								id={dialogId}
								ref={panelRef}
								role="dialog"
								aria-modal="true"
								aria-labelledby={`${dialogId}-title`}
							>
								<div className="help__head">
									<h2 className="help__title" id={`${dialogId}-title`}>
										{helpCopy(currentLocale()).title}
									</h2>
									<button
										type="button"
										className="icon-btn help__close"
										onClick={() => setOpen(false)}
									>
										<CloseIcon />
										<span className="sr-only">Close</span>
									</button>
								</div>

								<div className="help__body">
									<HelpContent />
								</div>
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

function Section({
	title,
	glyph,
	children,
}: {
	title: string;
	glyph?: React.ReactNode;
	children: React.ReactNode;
}) {
	return (
		<section className="help__section">
			<h3 className="help__heading">
				{glyph ? (
					<span className="help__heading-glyph" aria-hidden="true">
						{glyph}
					</span>
				) : null}
				{title}
			</h3>
			{children}
		</section>
	);
}

function HelpContent() {
	const copy = helpCopy(currentLocale());
	return (
		<>
			<p className="help__lede">{copy.lede}</p>
			{copy.sections.map((section) => (
				<HelpSectionView
					key={section.title}
					section={section}
					rows={copy.guideRows}
				/>
			))}
		</>
	);
}

const GLYPHS = {
	person: <PersonIcon />,
	spark: <SparkIcon />,
	mic: <MicIcon />,
	shuffle: <ShuffleIcon />,
};

/** **bold** and *italic*, the only markup the copy file uses. */
function rich(text: string): React.ReactNode[] {
	return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => {
		if (part.startsWith("**"))
			// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
			return <strong key={i}>{part.slice(2, -2)}</strong>;
		if (part.startsWith("*"))
			// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
			return <em key={i}>{part.slice(1, -1)}</em>;
		return part;
	});
}

function HelpSectionView({
	section,
	rows,
}: {
	section: HelpSection;
	rows: Record<string, { audience: string; blurb: string }>;
}) {
	return (
		<Section
			title={section.title}
			glyph={section.glyph ? GLYPHS[section.glyph] : undefined}
		>
			{section.paras.map((p) => (
				<p key={p.slice(0, 24)}>{rich(p)}</p>
			))}
			{section.guides ? (
				<ul className="help__list">
					{GUIDES.map((guide) => {
						const localised = rows[guide.guideId];
						return (
							<li key={guide.guideId}>
								<strong>{guide.name}</strong>
								<span className="help__muted">
									{" "}
									· {localised?.audience ?? guide.audience}
								</span>
								<br />
								{localised?.blurb ?? guide.blurb}
							</li>
						);
					})}
				</ul>
			) : null}
			{section.can ? (
				<>
					<p className="help__can">{section.can.label}</p>
					<ul className="help__list">
						{section.can.items.map((item) => (
							<li key={item.slice(0, 24)}>{rich(item)}</li>
						))}
					</ul>
				</>
			) : null}
			{section.cannot ? (
				<>
					<p className="help__cannot">{section.cannot.label}</p>
					<ul className="help__list">
						{section.cannot.items.map((item) => (
							<li key={item.slice(0, 24)}>{rich(item)}</li>
						))}
					</ul>
				</>
			) : null}
			{section.list ? (
				<ul className="help__list">
					{section.list.map((item) => (
						<li key={item.slice(0, 24)}>{rich(item)}</li>
					))}
				</ul>
			) : null}
			{section.note ? <p className="help__note">{rich(section.note)}</p> : null}
		</Section>
	);
}
