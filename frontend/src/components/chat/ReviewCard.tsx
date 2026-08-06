/**
 * The whole application, grouped, editable, before it is submitted.
 *
 * ## "Change item 4" edits item 4 and nothing else
 *
 * Tapping edit sends the graph to that slot, collects it, and returns HERE.
 * The flow is not restarted, no other answer is cleared, and the parent does
 * not walk the form again.
 *
 * That is the single most important behaviour on this card. A form that
 * restarts on a correction is a form parents abandon -- and the correction they
 * were making was usually a spelling, which means the abandonment is caused
 * entirely by the interface.
 *
 * ## Values arrive already masked
 *
 * `fields` carries `[slot, label, displayValue]` and the display value is what
 * the server decided a reader may see. A national ID reads as `••••5678`. This
 * card renders a transcript entry, the transcript is persisted, and neither of
 * those is a place for a full ID number.
 *
 * ## Attestation is explicit and cannot be pre-ticked
 *
 * The submit button is disabled until the box is checked. The consent TEXT and
 * its VERSION are rendered from the server's own copy, so the thing agreed to
 * is the thing recorded -- see `review_events` and `consent_version`.
 */
import { useState } from "react";
import type { ReviewCardDirective } from "../../lib/stream/types";
import { useAgeBand } from "./AgeBandProvider";

export function ReviewCard({
	directive,
	onEdit,
	onSubmit,
	consentText = "I confirm the details above are correct and I am the parent or legal guardian of the child named.",
	consentVersion = "v1",
}: {
	directive: ReviewCardDirective;
	onEdit: (slot: string) => void;
	onSubmit: () => void;
	consentText?: string;
	consentVersion?: string;
}) {
	const band = useAgeBand();
	const [attested, setAttested] = useState(false);

	// A running number across sections, so "change item 4" means the fourth
	// thing on screen rather than the fourth thing in section two.
	let item = 0;

	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				borderRadius: "1rem",
				border: "1px solid var(--hairline)",
				background: "var(--wash-3)",
				overflow: "hidden",
			}}
		>
			{directive.sections.map((section) => (
				<section key={section.title} style={{ padding: "1rem" }}>
					<h3
						style={{
							margin: "0 0 0.5rem",
							fontSize: "var(--band-type, 16px)",
							fontWeight: 700,
							color: "var(--plum-deep)",
						}}
					>
						{section.title}
					</h3>

					<dl style={{ margin: 0 }}>
						{section.fields.map(([slot, label, value]) => {
							item += 1;
							return (
								<div
									key={slot}
									style={{
										display: "grid",
										gridTemplateColumns: "1fr auto",
										gap: "0.5rem",
										alignItems: "center",
										padding: "0.5rem 0",
										borderTop: "1px solid var(--hairline)",
									}}
								>
									<div>
										<dt
											style={{
												fontSize: "calc(var(--band-type, 16px) - 2px)",
												color: "var(--quiet)",
											}}
										>
											{item}. {label}
										</dt>
										<dd
											style={{
												margin: 0,
												fontSize: "var(--band-type, 16px)",
												color: "var(--prose)",
											}}
										>
											{value || "—"}
										</dd>
									</div>
									<button
										type="button"
										onClick={() => onEdit(slot)}
										// The accessible name has to name the field. Nine
										// buttons all called "Change" is a screen-reader
										// user guessing.
										aria-label={`Change ${label}`}
										style={{
											minHeight: `${Math.max(44, band.touchTarget - 8)}px`,
											minWidth: "44px",
											padding: "0.375rem 0.75rem",
											borderRadius: "0.5rem",
											border: "1px solid var(--hairline)",
											background: "transparent",
											color: "var(--plum)",
											fontSize: "calc(var(--band-type, 16px) - 1px)",
											fontWeight: 600,
											cursor: "pointer",
										}}
									>
										Change
									</button>
								</div>
							);
						})}
					</dl>

					{section.documents.length > 0 ? (
						<div
							style={{
								display: "flex",
								gap: "0.5rem",
								marginBlockStart: "0.75rem",
								flexWrap: "wrap",
							}}
						>
							{section.documents.map((documentId) => (
								<div
									key={documentId}
									style={{
										width: "4.5rem",
										height: "4.5rem",
										borderRadius: "0.5rem",
										border: "1px solid var(--hairline)",
										background: "var(--wash-6)",
										display: "grid",
										placeItems: "center",
										fontSize: "0.7rem",
										color: "var(--quiet)",
									}}
								>
									{/*
									 * A placeholder rather than the document itself.
									 * Rendering it needs a short-lived signed URL, which
									 * is fetched on demand -- a thumbnail grid that
									 * pre-fetches nine of them is nine live URLs sitting
									 * in a page a parent may leave open.
									 */}
									Document
								</div>
							))}
						</div>
					) : null}
				</section>
			))}

			<div
				style={{
					padding: "1rem",
					borderTop: "1px solid var(--hairline)",
					background: "var(--wash-6)",
				}}
			>
				<label
					style={{
						display: "flex",
						gap: "0.625rem",
						alignItems: "flex-start",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--prose)",
						cursor: "pointer",
						minHeight: "44px",
					}}
				>
					<input
						type="checkbox"
						checked={attested}
						onChange={(event) => setAttested(event.target.checked)}
						style={{
							width: "1.25rem",
							height: "1.25rem",
							marginBlockStart: "2px",
						}}
					/>
					<span>{consentText}</span>
				</label>

				<button
					type="button"
					// Disabled, not hidden, and not "submit anyway with a warning".
					// An application submitted without explicit attestation is an
					// application with no consent record behind it.
					disabled={!attested}
					onClick={onSubmit}
					style={{
						marginBlockStart: "0.75rem",
						width: "100%",
						minHeight: `${band.touchTarget}px`,
						borderRadius: "0.875rem",
						border: "1px solid var(--plum)",
						background: attested ? "var(--plum)" : "var(--wash-12)",
						color: attested ? "white" : "var(--faint)",
						fontSize: "var(--band-type, 16px)",
						fontWeight: 700,
						cursor: attested ? "pointer" : "not-allowed",
					}}
				>
					Submit the application
				</button>

				<p
					style={{
						margin: "0.5rem 0 0",
						fontSize: "0.75rem",
						color: "var(--faint)",
					}}
				>
					Consent text {consentVersion}
				</p>
			</div>
		</div>
	);
}
