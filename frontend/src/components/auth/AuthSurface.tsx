import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

/**
 * The shell both auth pages sit in.
 *
 * A split surface: the brand panel on the left carries the gradient and says
 * what ASPIRE is, the white column on the right carries the form. On a narrow
 * screen the panel becomes a header and the form rises over it as a sheet,
 * which is why the column has its own radius and a negative top margin rather
 * than the two being separate blocks.
 *
 * One component for sign-in and sign-up on purpose. They are the same surface
 * at two moments, and the step indicator is the only structural difference
 * between them — building two would guarantee they drift.
 */

interface AuthSurfaceProps {
	/** What this screen is called, as a heading. */
	title: string;
	subtitle: string;
	/** Progress through sign-up. Absent on sign-in, which has no steps. */
	step?: { current: number; total: number; label: string };
	/** Where "back" goes. Absent means no back control. */
	onBack?: () => void;
	backLabel?: string;
	children: ReactNode;
	/** The line under the form: "New to ASPIRE?" and its link. */
	footText?: string;
	footLinkLabel?: string;
	footLinkTo?: string;
	footNote?: string;
}

/** What the panel says. Deliberately concrete rather than marketing. */
const STATS = [
	{ value: "5–18", label: "Ages supported" },
	{ value: "2", label: "Islands" },
];

export function AuthSurface({
	title,
	subtitle,
	step,
	onBack,
	backLabel = "Back",
	children,
	footText,
	footLinkLabel,
	footLinkTo,
	footNote,
}: AuthSurfaceProps) {
	return (
		<div className="auth">
			<div className="auth__panel">
				{/* Ambient only, and hidden from assistive tech: two blurred
				    washes that give the flat gradient some depth. */}
				<div className="auth__orb auth__orb--a" aria-hidden="true" />
				<div className="auth__orb auth__orb--b" aria-hidden="true" />

				<div className="auth__panel-inner">
					<img
						className="auth__logo"
						src="/brand/aspire-wordmark.png"
						alt="ASPIRE — Achieving Success through Personal Investment, Resources and Education"
					/>
					<h1 className="auth__headline">
						Learn to invest.
						<br />
						<span>Build your future.</span>
					</h1>
					<p className="auth__panel-sub">
						The ASPIRE assistant answers questions about money, your modules and
						the programme itself — in plain words, at your own pace.
					</p>

					<div className="auth__stats">
						{STATS.map((stat) => (
							<div className="auth__stat" key={stat.label}>
								<span className="auth__stat-value">{stat.value}</span>
								<span className="auth__stat-label">{stat.label}</span>
							</div>
						))}
					</div>

					<span className="auth__gov">
						A programme of the Government of St. Kitts and Nevis.
					</span>
				</div>
			</div>

			<div className="auth__column">
				<div className="auth__form">
					{onBack ? (
						<button type="button" className="auth__back" onClick={onBack}>
							<svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true">
								<path
									d="M15 18l-6-6 6-6"
									fill="none"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
									strokeLinejoin="round"
								/>
							</svg>
							{backLabel}
						</button>
					) : null}

					{step ? (
						<div className="auth__steps">
							{/* The bars are decorative: the line beneath them says
							    "Step 2 of 4" in words, which is the thing worth
							    announcing. A role="group" here would make a screen
							    reader walk four empty spans to learn nothing. */}
							<div className="auth__segs" aria-hidden="true">
								{Array.from({ length: step.total }, (_, index) => (
									<span
										// Segments are positional and fixed in number.
										// biome-ignore lint/suspicious/noArrayIndexKey: positional by design
										key={index}
										className="auth__seg"
										data-done={index < step.current || undefined}
									/>
								))}
							</div>
							<span className="auth__step-text">
								Step {step.current} of {step.total} · {step.label}
							</span>
						</div>
					) : null}

					<div className="auth__head">
						<h2 className="auth__title">{title}</h2>
						<p className="auth__sub">{subtitle}</p>
					</div>

					{children}

					{footText ? (
						<div className="auth__foot">
							<span>
								{footText}{" "}
								{footLinkTo && footLinkLabel ? (
									<Link to={footLinkTo} className="auth__foot-link">
										{footLinkLabel}
									</Link>
								) : null}
							</span>
							{footNote ? <span className="auth__foot-note">{footNote}</span> : null}
						</div>
					) : null}
				</div>
			</div>
		</div>
	);
}
