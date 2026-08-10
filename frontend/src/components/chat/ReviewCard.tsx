/** The whole application, grouped, editable, before it is submitted. */
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

	// A running number across sections, so "change item 4" means the fourth thing on screen rather than the fourth…
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
										// The accessible name has to name the field.
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
									{/* A placeholder rather than the document itself. */}
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
