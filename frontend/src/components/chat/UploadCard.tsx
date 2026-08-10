/**
 * Asking for a document, and getting it to storage without touching our server.
 *
 * ## The bytes never pass through FastAPI or the graph
 *
 * The card asks the API for a presigned URL, PUTs the file straight to object
 * storage, and hands the graph a `document_id`. The file itself is never in a
 * request body we parse, never in graph state, never in a log line, and never
 * in an LLM context window.
 *
 * That is not only about cost. A birth certificate that passes through the
 * application server is a birth certificate in a request log, in an APM trace,
 * and in whatever a crash reporter captured -- three places nobody audited for
 * it. The presigned URL removes all three by removing the hop.
 *
 * ## Camera on mobile, picker on desktop
 *
 * `capture="environment"` makes a phone open the rear camera directly rather
 * than the file browser, which is the difference between a parent photographing
 * a certificate in ten seconds and hunting through a gallery. Desktop browsers
 * ignore the attribute and show a picker, which is correct there.
 *
 * ## Preview, then confirm, then retake
 *
 * Never upload on selection. A blurry photo is the normal first attempt, and
 * the moment to notice it is before it goes anywhere -- not in an admin queue
 * three days later.
 */
import { useEffect, useRef, useState } from "react";
import { graphSession } from "../../lib/stream/session";
import type { UploadDirective } from "../../lib/stream/types";
import { useAgeBand } from "./AgeBandProvider";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

type Phase = "idle" | "chosen" | "uploading" | "done" | "failed";

export function UploadCard({
	directive,
	threadId,
	onUploaded,
}: {
	directive: UploadDirective;
	/**
	 * The conversation this document belongs to.
	 *
	 * Needed for the presign call's credential, not merely for bookkeeping —
	 * `/v2/documents/presign` authenticates with the GRAPH session token, which
	 * is minted per thread and held in memory by `lib/stream/session`.
	 */
	threadId?: string;
	/**
	 * The receipt for a document that is already in the bucket.
	 *
	 * Carries the mime and size as well as the id because the graph is paused
	 * waiting for exactly this shape, and records all three against the slot.
	 */
	onUploaded: (result: {
		document_id: string;
		mime: string;
		size_bytes: number;
	}) => void;
}) {
	const band = useAgeBand();
	const [phase, setPhase] = useState<Phase>("idle");
	const [file, setFile] = useState<File | null>(null);
	const [preview, setPreview] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [progress, setProgress] = useState(0);
	const input = useRef<HTMLInputElement>(null);

	// Object URLs are a leak if they are not revoked, and a parent adding four
	// children uploads a dozen files in one sitting.
	useEffect(() => {
		return () => {
			if (preview) URL.revokeObjectURL(preview);
		};
	}, [preview]);

	const choose = (candidate: File | null) => {
		setProblem(null);
		if (!candidate) return;

		// Both checks are repeated server-side. They are here because a clear
		// error before a 10MB upload beats a rejection after one, on a phone
		// connection a parent is paying for by the megabyte.
		if (!directive.accepts.includes(candidate.type)) {
			setProblem(
				`That is a ${describeType(candidate.type)}. Please send a photo or a PDF.`,
			);
			return;
		}
		if (candidate.size > directive.max_mb * 1024 * 1024) {
			setProblem(
				`That file is ${(candidate.size / 1024 / 1024).toFixed(1)}MB. The limit is ${directive.max_mb}MB — a photo usually works.`,
			);
			return;
		}

		setFile(candidate);
		setPreview(
			candidate.type.startsWith("image/")
				? URL.createObjectURL(candidate)
				: null,
		);
		setPhase("chosen");
	};

	const upload = async () => {
		if (!file) return;
		if (!threadId) {
			// The directive arrived before the thread settled. Rare, and better
			// said than swallowed: there is no session to sign a presign with.
			setPhase("failed");
			setProblem(
				"This conversation is still starting. Try that again in a moment.",
			);
			return;
		}
		setPhase("uploading");
		setProgress(0);
		try {
			// The GRAPH session token, not the account one.
			// `/v2/documents/presign` decodes it with `decode_session_token` and
			// authenticates the caller by it, so the thread's own token is the
			// credential this call needs.
			//
			// This card used to send `credentials: "include"` and no Authorization
			// header at all — the only cookie-auth call in the client, against an
			// API that has never used cookies. Every upload 401'd before storage
			// was ever consulted, and the catch below reported it as "that did not
			// go through", so the failure looked like a flaky network.
			const session = await graphSession(threadId);

			const presign = await fetch(`${API_URL}/v2/documents/presign`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.token}`,
				},
				body: JSON.stringify({
					slot: directive.slot,
					mime: file.type,
					size: file.size,
					// WHERE the object goes, and it has to be said out loud.
					//
					// The token authenticates the caller; it does not name the
					// application. Left out, the endpoint scopes the upload to the
					// caller's SESSION id — but the graph records the document
					// under the APPLICATION id, and the two are never equal
					// (`store.new_draft` mints a fresh UUID). Every document ever
					// uploaded went to a key nothing reads and was recorded at a
					// key holding nothing, and both halves succeeded, so the 404
					// waited for an admin to open the file.
					//
					// Omitted rather than sent empty when the server did not
					// supply one: absent restores the session-scoped default,
					// where `""` would be refused as a malformed id.
					...(directive.application_id
						? { application_id: directive.application_id }
						: {}),
				}),
			});
			if (!presign.ok) {
				setPhase("failed");
				setProblem(await presignProblem(presign));
				return;
			}
			const { url, document_id: documentId, headers } = await presign.json();

			// Straight to storage. Note there is no `credentials` here and no
			// Authorization header: the signature IS the authorisation, and
			// sending our session token to a bucket would be sending it
			// somewhere it has no business being.
			const put = await fetch(url, {
				method: "PUT",
				headers: { "Content-Type": file.type, ...(headers ?? {}) },
				body: file,
			});
			if (!put.ok) throw new Error(`upload failed: ${put.status}`);

			setProgress(100);
			setPhase("done");
			onUploaded({
				document_id: documentId,
				mime: file.type,
				size_bytes: file.size,
			});
		} catch (error) {
			console.error("[aspire] upload failed", error);
			setPhase("failed");
			setProblem("That did not go through. Please try again.");
		}
	};

	return (
		<div
			style={{
				marginBlockStart: "0.75rem",
				padding: "1rem",
				borderRadius: "1rem",
				border: "1px solid var(--hairline)",
				background: "var(--wash-3)",
			}}
		>
			<p
				style={{
					margin: 0,
					fontSize: "var(--band-type, 16px)",
					fontWeight: 700,
					color: "var(--plum-deep)",
				}}
			>
				{directive.label}
			</p>
			{directive.help ? (
				<p
					style={{
						margin: "0.25rem 0 0.75rem",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--slate)",
					}}
				>
					{directive.help}
				</p>
			) : null}

			<input
				ref={input}
				type="file"
				accept={directive.accepts.join(",")}
				// Opens the rear camera on a phone; ignored on desktop.
				capture="environment"
				onChange={(event) => choose(event.target.files?.[0] ?? null)}
				style={{ display: "none" }}
			/>

			{preview ? (
				<img
					src={preview}
					alt="The document you chose"
					style={{
						maxWidth: "100%",
						maxHeight: "14rem",
						borderRadius: "0.75rem",
						display: "block",
						marginBlockEnd: "0.75rem",
					}}
				/>
			) : null}

			{file && !preview ? (
				<p
					style={{
						fontSize: "calc(var(--band-type, 16px) - 1px)",
						color: "var(--slate)",
					}}
				>
					{file.name} · {(file.size / 1024 / 1024).toFixed(1)}MB
				</p>
			) : null}

			{problem ? (
				<p
					role="alert"
					style={{
						margin: "0 0 0.75rem",
						padding: "0.5rem 0.75rem",
						borderRadius: "0.5rem",
						background: "var(--danger-wash)",
						border: "1px solid var(--danger-line)",
						color: "var(--danger)",
						fontSize: "calc(var(--band-type, 16px) - 1px)",
					}}
				>
					{problem}
				</p>
			) : null}

			{phase === "uploading" ? (
				<div
					role="progressbar"
					aria-valuemin={0}
					aria-valuemax={100}
					aria-valuenow={progress}
					style={{
						height: "0.5rem",
						borderRadius: "999px",
						background: "var(--wash-9)",
						overflow: "hidden",
					}}
				>
					<div
						style={{
							width: `${progress}%`,
							height: "100%",
							background: "var(--plum)",
							transition: "width 200ms ease",
						}}
					/>
				</div>
			) : null}

			{phase === "done" ? (
				<p
					style={{
						margin: 0,
						color: "var(--success)",
						fontWeight: 600,
						fontSize: "var(--band-type, 16px)",
					}}
				>
					Got it, thank you.
				</p>
			) : (
				<div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
					<button
						type="button"
						onClick={() => input.current?.click()}
						disabled={phase === "uploading"}
						style={buttonStyle(band.touchTarget, phase !== "chosen")}
					>
						{file ? "Retake" : "Take a photo"}
					</button>
					{file ? (
						<button
							type="button"
							onClick={upload}
							disabled={phase === "uploading"}
							style={buttonStyle(band.touchTarget, true)}
						>
							{phase === "uploading" ? "Sending…" : "Send it"}
						</button>
					) : null}
				</div>
			)}
		</div>
	);
}

/**
 * What to tell somebody whose presign was refused.
 *
 * One sentence per reason, because they call for different actions and the card
 * used to give the same one to all of them: "That did not go through. Please try
 * again." A parent whose service has no storage configured, or whose session
 * expired, can retry that card until the battery dies.
 *
 * The 400 reason is the service's own wording (`storage.check_upload`), which
 * names the actual limit — worth showing rather than paraphrasing, since the
 * client's matching check has already passed by the time we are here and the
 * two disagreeing is exactly what the reader needs to see.
 */
async function presignProblem(response: Response): Promise<string> {
	let detail = "";
	try {
		const body = (await response.json()) as { detail?: unknown };
		if (typeof body.detail === "string") detail = body.detail;
	} catch {
		// A non-JSON error body is a proxy or gateway talking, not the service.
	}

	if (response.status === 401)
		return "Your session timed out. Refresh the page and try once more.";
	if (response.status === 404)
		return "We could not find that application. Refresh the page and try once more.";
	if (response.status === 503)
		return (
			detail ||
			"Uploads are switched off on this service right now. Nothing you did — try later, or bring the document to a branch."
		);
	if (response.status === 400 && detail) return detail;
	return "That did not go through. Please try again.";
}

function buttonStyle(target: number, primary: boolean) {
	return {
		minHeight: `${target}px`,
		minWidth: "44px",
		padding: "0.5rem 1rem",
		borderRadius: "0.75rem",
		border: primary ? "1px solid var(--plum)" : "1px solid var(--hairline)",
		background: primary ? "var(--plum)" : "transparent",
		color: primary ? "white" : "var(--slate)",
		fontSize: "var(--band-type, 16px)",
		fontWeight: 600,
		cursor: "pointer",
	} as const;
}

function describeType(mime: string): string {
	if (mime.startsWith("video/")) return "video";
	if (mime.startsWith("audio/")) return "sound file";
	if (mime === "application/pdf") return "PDF";
	if (mime.startsWith("image/")) return "picture";
	return "file we cannot read";
}
