/** One application: fields on the left, documents on the right, side by side. */
import {
	createFileRoute,
	useNavigate,
	useParams,
} from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
	type ApplicationDetail,
	type ApplicationStatus,
	application,
	documentUrl,
	transition,
} from "#/lib/admin/api";

export const Route = createFileRoute("/admin/applications/$id")({
	component: Detail,
});

/** Which moves the UI offers. Mirrors `TRANSITIONS` in the router. */
const NEXT: Record<string, Array<ApplicationStatus>> = {
	submitted: ["under_review"],
	under_review: ["info_requested", "approved", "rejected"],
	info_requested: ["under_review"],
	approved: [],
	rejected: [],
};

function Detail() {
	const { id } = useParams({ from: "/admin/applications/$id" });
	const navigate = useNavigate();
	const [data, setData] = useState<ApplicationDetail | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [selected, setSelected] = useState<Array<string>>([]);
	const [reason, setReason] = useState("");
	const [viewing, setViewing] = useState<{ id: string; url: string } | null>(
		null,
	);
	const [rotation, setRotation] = useState(0);
	const [zoom, setZoom] = useState(1);

	useEffect(() => {
		application(id)
			.then(setData)
			.catch((error) => setProblem(error.message));
	}, [id]);

	if (problem)
		return (
			<p role="alert" style={{ color: "var(--danger)" }}>
				{problem}
			</p>
		);
	if (!data) return <p style={{ color: "var(--quiet)" }}>Loading…</p>;

	const move = async (to: ApplicationStatus) => {
		if (!reason.trim()) {
			setProblem("Every change needs a reason note.");
			return;
		}
		if (to === "info_requested" && selected.length === 0) {
			setProblem(
				"Tick the fields that need correcting. The parent will only be asked for those.",
			);
			return;
		}
		try {
			await transition(id, {
				to,
				reason,
				slots: to === "info_requested" ? selected : [],
			});
			setProblem(null);
			navigate({ to: "/admin/applications" });
		} catch (error) {
			setProblem((error as Error).message);
		}
	};

	return (
		<section>
			<h1
				style={{
					margin: "0 0 0.25rem",
					fontSize: "1.35rem",
					color: "var(--plum-deep)",
				}}
			>
				{id.slice(0, 8).toUpperCase()}
			</h1>
			<p
				style={{
					margin: "0 0 1rem",
					color: "var(--quiet)",
					fontSize: "0.9rem",
				}}
			>
				{data.status.replace(/_/g, " ")} · submitted{" "}
				{data.submitted_at
					? new Date(data.submitted_at).toLocaleDateString()
					: "—"}{" "}
				· consent {data.consent_version ?? "not recorded"}
			</p>

			{/* Side by side. */}
			<div
				style={{
					display: "grid",
					gridTemplateColumns:
						"repeat(auto-fit, minmax(min(100%, 28rem), 1fr))",
					gap: "1rem",
					alignItems: "start",
				}}
			>
				<div style={panel}>
					<h2 style={heading}>Details</h2>
					<table style={{ width: "100%", borderCollapse: "collapse" }}>
						<tbody>
							{Object.entries(data.fields)
								.filter(([key]) => !key.startsWith("__"))
								.map(([key, value]) => (
									<tr
										key={key}
										style={{ borderBottom: "1px solid var(--hairline)" }}
									>
										<td
											style={{
												padding: "0.5rem 0.5rem 0.5rem 0",
												width: "2rem",
											}}
										>
											<input
												type="checkbox"
												aria-label={`Flag ${key} for correction`}
												checked={selected.includes(key)}
												onChange={(event) =>
													setSelected((current) =>
														event.target.checked
															? [...current, key]
															: current.filter((entry) => entry !== key),
													)
												}
											/>
										</td>
										<th
											scope="row"
											style={{
												textAlign: "left",
												padding: "0.5rem 0.75rem 0.5rem 0",
												fontWeight: 400,
												color: "var(--quiet)",
												fontSize: "0.85rem",
											}}
										>
											{key}
										</th>
										<td style={{ padding: "0.5rem 0", fontSize: "0.9rem" }}>
											{value}
										</td>
									</tr>
								))}
						</tbody>
					</table>
				</div>

				<div style={panel}>
					<h2 style={heading}>Documents</h2>
					{data.documents.length === 0 ? (
						<p style={{ color: "var(--quiet)" }}>None uploaded.</p>
					) : (
						<ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
							{data.documents.map((document) => (
								<li
									key={document.id}
									style={{
										padding: "0.5rem 0",
										borderBottom: "1px solid var(--hairline)",
									}}
								>
									<button
										type="button"
										onClick={async () => {
											const { url } = await documentUrl(document.id);
											setViewing({ id: document.id, url });
											setRotation(0);
											setZoom(1);
										}}
										style={{
											minHeight: "44px",
											background: "transparent",
											border: "none",
											color: "var(--plum)",
											cursor: "pointer",
											padding: 0,
											fontSize: "0.9rem",
										}}
									>
										{document.slot}
									</button>
									<div style={{ fontSize: "0.8rem", color: "var(--quiet)" }}>
										{document.mime} · scan {document.scan_status}
										{document.check_confidence !== null ? (
											<>
												{" · "}
												<span
													style={{
														color:
															document.check_confidence < 0.75
																? "var(--warn-ink)"
																: "var(--quiet)",
													}}
												>
													check {(document.check_confidence * 100).toFixed(0)}%
												</span>
											</>
										) : null}
									</div>
									{/* doc_check's note, shown as ADVICE. */}
									{document.check_notes ? (
										<div
											style={{ fontSize: "0.8rem", color: "var(--warn-ink)" }}
										>
											{document.check_notes}
										</div>
									) : null}
								</li>
							))}
						</ul>
					)}

					{viewing ? (
						<div style={{ marginBlockStart: "0.75rem" }}>
							<div
								style={{
									display: "flex",
									gap: "0.5rem",
									marginBlockEnd: "0.5rem",
								}}
							>
								<button
									type="button"
									style={tool}
									onClick={() => setRotation((r) => r + 90)}
								>
									Rotate
								</button>
								<button
									type="button"
									style={tool}
									onClick={() => setZoom((z) => Math.min(4, z + 0.5))}
								>
									Zoom in
								</button>
								<button
									type="button"
									style={tool}
									onClick={() => setZoom((z) => Math.max(1, z - 0.5))}
								>
									Zoom out
								</button>
							</div>
							<div
								style={{
									overflow: "auto",
									maxHeight: "32rem",
									background: "var(--wash-6)",
								}}
							>
								<img
									src={viewing.url}
									alt="The uploaded document"
									style={{
										transform: `rotate(${rotation}deg) scale(${zoom})`,
										transformOrigin: "top left",
										maxWidth: "100%",
									}}
								/>
							</div>
						</div>
					) : null}
				</div>
			</div>

			<div style={{ ...panel, marginBlockStart: "1rem" }}>
				<h2 style={heading}>Decision</h2>
				<label
					htmlFor="reason"
					style={{
						display: "block",
						fontSize: "0.85rem",
						color: "var(--quiet)",
					}}
				>
					Reason (required for every change)
				</label>
				<textarea
					id="reason"
					value={reason}
					onChange={(event) => setReason(event.target.value)}
					rows={3}
					style={{
						width: "100%",
						padding: "0.5rem",
						borderRadius: "0.5rem",
						border: "1px solid var(--hairline)",
						fontFamily: "inherit",
					}}
				/>
				{selected.length > 0 ? (
					<p style={{ fontSize: "0.85rem", color: "var(--plum-deep)" }}>
						{selected.length} field{selected.length === 1 ? "" : "s"} will
						reopen in the parent's chat. They will not refill the form.
					</p>
				) : null}
				<div
					style={{
						display: "flex",
						gap: "0.5rem",
						flexWrap: "wrap",
						marginBlockStart: "0.5rem",
					}}
				>
					{(NEXT[data.status] ?? []).map((next) => (
						<button
							key={next}
							type="button"
							onClick={() => move(next)}
							style={tool}
						>
							{next.replace(/_/g, " ")}
						</button>
					))}
					{(NEXT[data.status] ?? []).length === 0 ? (
						<p style={{ color: "var(--quiet)", fontSize: "0.9rem" }}>
							This decision is final. Reopening it would let the record be
							rewritten.
						</p>
					) : null}
				</div>
			</div>

			<div style={{ ...panel, marginBlockStart: "1rem" }}>
				<h2 style={heading}>History</h2>
				<ol
					style={{
						margin: 0,
						paddingInlineStart: "1.25rem",
						fontSize: "0.85rem",
					}}
				>
					{/* Keyed on the transition itself. */}
					{data.history.map((event) => (
						<li
							key={`${event.at}-${event.to}`}
							style={{ marginBlockEnd: "0.5rem" }}
						>
							<strong>
								{event.from ?? "—"} → {event.to}
							</strong>{" "}
							by {event.actor}
							<div style={{ color: "var(--quiet)" }}>{event.reason}</div>
							{event.slots.length > 0 ? (
								<div style={{ color: "var(--quiet)" }}>
									fields: {event.slots.join(", ")}
								</div>
							) : null}
							<div style={{ color: "var(--faint)" }}>
								{new Date(event.at).toLocaleString()}
							</div>
						</li>
					))}
				</ol>
			</div>
		</section>
	);
}

const panel = {
	padding: "1rem",
	background: "white",
	border: "1px solid var(--hairline)",
	borderRadius: "0.75rem",
} as const;

const heading = {
	margin: "0 0 0.75rem",
	fontSize: "1rem",
	color: "var(--plum-deep)",
} as const;

const tool = {
	minHeight: "44px",
	padding: "0.375rem 0.875rem",
	borderRadius: "0.5rem",
	border: "1px solid var(--plum)",
	background: "transparent",
	color: "var(--plum)",
	cursor: "pointer",
	fontSize: "0.9rem",
} as const;
