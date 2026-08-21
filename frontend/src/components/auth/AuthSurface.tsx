import { Link, type LinkProps } from "@tanstack/react-router";
import { type ReactNode, useEffect, useRef } from "react";

/** The shell both auth pages sit in. */

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
	/** A real route, checked against the route tree. */
	footLinkTo?: LinkProps["to"];
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
	/**
	 * Moving between sign-up steps replaces the whole form and says nothing.
	 * Focus stayed on the "Continue" button that had just been replaced, so a
	 * keyboard user Tabbed on from wherever the browser dropped them and a
	 * screen reader was told nothing at all. Sending focus to the new heading
	 * reads the step out and puts the next Tab at the top of the new form.
	 *
	 * Not on arrival — only on a step that changed under someone already here.
	 */
	const headingRef = useRef<HTMLHeadingElement>(null);
	const lastStep = useRef(step?.current);
	useEffect(() => {
		const current = step?.current;
		if (current === undefined || lastStep.current === current) return;
		lastStep.current = current;
		headingRef.current?.focus();
	}, [step?.current]);

	return (
		<div className="auth">
			{/* The pitch is the whole first half of this page in reading order, so
			    the way past it is stated before it. `.skip-link` is the same
			    control the chat screen uses for the same reason. */}
			<a href="#auth-form" className="skip-link">
				Skip to the form
			</a>

			{/* Supplementary to the task: somebody is here to sign in, not to read
			    the pitch. Announced as `complementary` so it can be skipped over. */}
			<aside className="auth__panel" aria-label="About ASPIRE">
				{/* Ambient only: two blurred washes that give the gradient depth. */}
				<div className="auth__orb auth__orb--a" aria-hidden="true" />
				<div className="auth__orb auth__orb--b" aria-hidden="true" />

				<div className="auth__panel-inner">
					<img
						className="auth__logo"
						src="/brand/aspire-wordmark.png"
						// Reserves the box before the image decodes.
						width={190}
						height={48}
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
			</aside>

			<main className="auth__column">
				<div className="auth__form" id="auth-form">
					{onBack ? (
						<button type="button" className="auth__back" onClick={onBack}>
							<svg
								width="17"
								height="17"
								viewBox="0 0 24 24"
								aria-hidden="true"
							>
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
							{/* Decorative: the line beneath states the step in words. */}
							<div className="auth__segs" aria-hidden="true">
								{Array.from({ length: step.total }, (_, index) => (
									<span
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
						{/* `-1`, so it takes focus on a step change without becoming a
						    tab stop of its own. */}
						<h2 className="auth__title" ref={headingRef} tabIndex={-1}>
							{title}
						</h2>
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
							{footNote ? (
								<span className="auth__foot-note">{footNote}</span>
							) : null}
						</div>
					) : null}
				</div>
			</main>
		</div>
	);
}
