/**
 * The review queue. Oldest first, because that is the fair order.
 *
 * A family who applied in March is seen before one who applied last week,
 * whatever else is true about the rows. Sorting by anything else needs a
 * reason, and "newest first" is not one — it is the default that makes the
 * longest-waiting applicant wait longest.
 *
 * Flags are shown and are NOT a sort key by default. `doc_check` is advisory;
 * letting its confidence reorder the queue would make an automated opinion
 * decide who is seen first, which is one step from letting it decide anything.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { type ApplicationStatus, type QueueRow, queue } from "#/lib/admin/api";

export const Route = createFileRoute("/admin/applications")({
	component: Queue,
});

const STATUSES: Array<ApplicationStatus | ""> = [
	"",
	"submitted",
	"under_review",
	"info_requested",
	"approved",
	"rejected",
];

function Queue() {
	const [rows, setRows] = useState<Array<QueueRow>>([]);
	const [status, setStatus] = useState<string>("");
	const [flagged, setFlagged] = useState(false);
	const [problem, setProblem] = useState<string | null>(null);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		queue({ status: status || undefined, flagged })
			.then((result) => {
				if (!cancelled) {
					setRows(result.rows);
					setProblem(null);
				}
			})
			.catch((error) => !cancelled && setProblem(error.message))
			.finally(() => !cancelled && setLoading(false));
		return () => {
			cancelled = true;
		};
	}, [status, flagged]);

	return (
		<section>
			<h1
				style={{
					margin: "0 0 1rem",
					fontSize: "1.35rem",
					color: "var(--plum-deep)",
				}}
			>
				Applications
			</h1>

			<div
				style={{
					display: "flex",
					gap: "0.75rem",
					marginBlockEnd: "1rem",
					flexWrap: "wrap",
				}}
			>
				<label
					style={{ display: "flex", gap: "0.375rem", alignItems: "center" }}
				>
					<span style={{ fontSize: "0.85rem", color: "var(--quiet)" }}>
						Status
					</span>
					<select
						value={status}
						onChange={(event) => setStatus(event.target.value)}
						style={{
							minHeight: "44px",
							padding: "0 0.5rem",
							borderRadius: "0.5rem",
						}}
					>
						{STATUSES.map((value) => (
							<option key={value || "all"} value={value}>
								{value ? value.replace(/_/g, " ") : "All"}
							</option>
						))}
					</select>
				</label>
				<label
					style={{
						display: "flex",
						gap: "0.375rem",
						alignItems: "center",
						minHeight: "44px",
					}}
				>
					<input
						type="checkbox"
						checked={flagged}
						onChange={(event) => setFlagged(event.target.checked)}
					/>
					<span style={{ fontSize: "0.85rem" }}>Flagged documents only</span>
				</label>
			</div>

			{problem ? (
				<p role="alert" style={{ color: "var(--danger)" }}>
					{problem}
				</p>
			) : null}

			{loading ? (
				<p style={{ color: "var(--quiet)" }}>Loading…</p>
			) : rows.length === 0 ? (
				<p style={{ color: "var(--quiet)" }}>Nothing waiting.</p>
			) : (
				<table
					style={{
						width: "100%",
						borderCollapse: "collapse",
						background: "white",
					}}
				>
					<caption
						style={{
							textAlign: "left",
							padding: "0.5rem 0",
							color: "var(--quiet)",
							fontSize: "0.85rem",
						}}
					>
						{rows.length} application{rows.length === 1 ? "" : "s"}, longest
						waiting first
					</caption>
					<thead>
						<tr
							style={{
								textAlign: "left",
								borderBottom: "1px solid var(--hairline)",
							}}
						>
							<th style={cell}>Reference</th>
							<th style={cell}>Status</th>
							<th style={cell}>Parish</th>
							<th style={cell}>Children</th>
							<th style={cell}>Waiting since</th>
							<th style={cell}>Flags</th>
						</tr>
					</thead>
					<tbody>
						{rows.map((row) => (
							<tr
								key={row.id}
								style={{ borderBottom: "1px solid var(--hairline)" }}
							>
								<td style={cell}>
									<Link
										to="/admin/applications/$id"
										params={{ id: row.id }}
										style={{
											color: "var(--plum)",
											fontFamily: "var(--font-mono)",
										}}
									>
										{row.id.slice(0, 8).toUpperCase()}
									</Link>
								</td>
								<td style={cell}>{row.status.replace(/_/g, " ")}</td>
								{/* Parish is not sensitive: it is a queue filter and it identifies
								    nobody. Every other field on this row would be. */}
								<td style={cell}>{row.parish ?? "—"}</td>
								<td style={cell}>{row.children}</td>
								<td style={cell}>
									{new Date(row.created_at).toLocaleDateString()}
								</td>
								<td style={cell}>
									{row.flags > 0 ? (
										<span style={{ color: "var(--warn-ink)", fontWeight: 600 }}>
											{row.flags}
										</span>
									) : (
										"—"
									)}
								</td>
							</tr>
						))}
					</tbody>
				</table>
			)}
		</section>
	);
}

const cell = { padding: "0.625rem 0.75rem", fontSize: "0.9rem" } as const;
