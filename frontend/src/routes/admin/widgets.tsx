/** The widget review queue. */
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AgeBandProvider } from "#/components/chat/AgeBandProvider";
import { WidgetRenderer } from "#/components/widgets/WidgetRenderer";
import {
	reviewWidget,
	type WidgetCandidate,
	widgetQueue,
} from "#/lib/admin/api";
import type { ConceptWidget } from "#/lib/stream/types";

export const Route = createFileRoute("/admin/widgets")({
	component: WidgetQueue,
});

function WidgetQueue() {
	const [rows, setRows] = useState<Array<WidgetCandidate>>([]);
	const [problem, setProblem] = useState<string | null>(null);
	const [loading, setLoading] = useState(true);

	const reload = () => {
		setLoading(true);
		widgetQueue()
			.then((result) => {
				setRows(result.rows);
				setProblem(null);
			})
			.catch((error) => setProblem(error.message))
			.finally(() => setLoading(false));
	};

	useEffect(reload, []);

	return (
		<section>
			<h1
				style={{
					margin: "0 0 0.25rem",
					fontSize: "1.35rem",
					color: "var(--plum-deep)",
				}}
			>
				Widgets waiting for review
			</h1>
			<p
				style={{
					margin: "0 0 1rem",
					color: "var(--quiet)",
					fontSize: "0.9rem",
				}}
			>
				Most-served first. Approving one means it is served instantly from then
				on and never regenerated.
			</p>

			{problem ? (
				<p role="alert" style={{ color: "var(--danger)" }}>
					{problem}
				</p>
			) : null}
			{loading ? <p style={{ color: "var(--quiet)" }}>Loading…</p> : null}
			{!loading && rows.length === 0 ? (
				<p style={{ color: "var(--quiet)" }}>Nothing waiting.</p>
			) : null}

			{rows.map((row) => (
				<Candidate key={row.id} row={row} onDone={reload} />
			))}
		</section>
	);
}

function Candidate({
	row,
	onDone,
}: {
	row: WidgetCandidate;
	onDone: () => void;
}) {
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState(() =>
		JSON.stringify(row.payload, null, 2),
	);
	const [problem, setProblem] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	const decide = async (decision: "approved" | "rejected") => {
		setBusy(true);
		setProblem(null);
		try {
			let payload: Record<string, unknown> | undefined;
			if (editing) {
				try {
					payload = JSON.parse(draft);
				} catch {
					setProblem("That edit is not valid JSON.");
					setBusy(false);
					return;
				}
			}
			await reviewWidget(row, { decision, payload });
			onDone();
		} catch (error) {
			setProblem((error as Error).message);
		} finally {
			setBusy(false);
		}
	};

	const preview = (() => {
		if (!editing) return row.payload as unknown as ConceptWidget;
		try {
			return JSON.parse(draft) as ConceptWidget;
		} catch {
			return row.payload as unknown as ConceptWidget;
		}
	})();

	return (
		<article
			style={{
				marginBlockEnd: "1.25rem",
				padding: "1rem",
				background: "white",
				border: "1px solid var(--hairline)",
				borderRadius: "0.75rem",
			}}
		>
			<header style={{ marginBlockEnd: "0.75rem" }}>
				<p style={{ margin: 0, fontSize: "0.85rem", color: "var(--quiet)" }}>
					{row.kind} · {row.concept_id} · {row.age_band} · {row.locale} · served{" "}
					{row.serve_count}×
				</p>
				{/* The source question is what a reviewer reads first: not "is this widget correct" in the abstract, but "does i… */}
				<p
					style={{
						margin: "0.25rem 0 0",
						fontStyle: "italic",
						color: "var(--prose)",
					}}
				>
					“{row.source_question}”
				</p>
			</header>

			{/* The real components, at the real band. */}
			<div
				style={{
					maxWidth: "24rem",
					border: "1px dashed var(--hairline)",
					padding: "0.5rem",
				}}
			>
				<AgeBandProvider band={row.age_band}>
					<WidgetRenderer
						widget={preview}
						onInteraction={() => undefined}
						onSkip={() => undefined}
					/>
				</AgeBandProvider>
			</div>

			{editing ? (
				<textarea
					value={draft}
					onChange={(event) => setDraft(event.target.value)}
					rows={14}
					spellCheck={false}
					style={{
						width: "100%",
						marginBlockStart: "0.75rem",
						fontFamily: "var(--font-mono)",
						fontSize: "0.8rem",
						padding: "0.5rem",
						borderRadius: "0.5rem",
						border: "1px solid var(--hairline)",
					}}
				/>
			) : null}

			{problem ? (
				<p role="alert" style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
					{problem}
				</p>
			) : null}

			<div
				style={{
					display: "flex",
					gap: "0.5rem",
					marginBlockStart: "0.75rem",
					flexWrap: "wrap",
				}}
			>
				<button
					type="button"
					disabled={busy}
					onClick={() => decide("approved")}
					style={primary}
				>
					{editing ? "Save and approve" : "Approve"}
				</button>
				<button
					type="button"
					disabled={busy}
					onClick={() => setEditing((value) => !value)}
					style={secondary}
				>
					{editing ? "Cancel edit" : "Edit"}
				</button>
				<button
					type="button"
					disabled={busy}
					onClick={() => decide("rejected")}
					style={secondary}
				>
					Reject
				</button>
			</div>
			<p
				style={{
					margin: "0.5rem 0 0",
					fontSize: "0.8rem",
					color: "var(--faint)",
				}}
			>
				Rejecting means this concept is answered in words only, for this band
				and language. Nothing regenerates it.
			</p>
		</article>
	);
}

const primary = {
	minHeight: "44px",
	padding: "0.375rem 1rem",
	borderRadius: "0.5rem",
	border: "1px solid var(--plum)",
	background: "var(--plum)",
	color: "white",
	fontWeight: 600,
	cursor: "pointer",
} as const;

const secondary = {
	...primary,
	background: "transparent",
	color: "var(--plum)",
	fontWeight: 500,
} as const;
