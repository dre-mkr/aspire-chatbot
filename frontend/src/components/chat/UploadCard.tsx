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
import type { UploadDirective } from "../../lib/stream/types";
import { useAgeBand } from "./AgeBandProvider";

const API_URL = (
	import.meta.env.VITE_ASPIRE_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

type Phase = "idle" | "chosen" | "uploading" | "done" | "failed";

export function UploadCard({
	directive,
	onUploaded,
}: {
	directive: UploadDirective;
	onUploaded: (documentId: string) => void;
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
		setPhase("uploading");
		setProgress(0);
		try {
			const presign = await fetch(`${API_URL}/v2/documents/presign`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				credentials: "include",
				body: JSON.stringify({
					slot: directive.slot,
					mime: file.type,
					size: file.size,
				}),
			});
			if (!presign.ok) throw new Error(`presign failed: ${presign.status}`);
			const { url, document_id: documentId, headers } = await presign.json();

			// Straight to storage. Note there is no `credentials` here and no
			// Authorization header: the signature IS the authorisation, and
			// sending our session cookie to a bucket would be sending it
			// somewhere it has no business being.
			const put = await fetch(url, {
				method: "PUT",
				headers: { "Content-Type": file.type, ...(headers ?? {}) },
				body: file,
			});
			if (!put.ok) throw new Error(`upload failed: ${put.status}`);

			setProgress(100);
			setPhase("done");
			onUploaded(documentId);
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
