import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CloseIcon, PlayIcon, VideoIcon } from "#/components/icons";
import {
	type AspireVideo,
	fetchVideos,
	runtime,
	videoSrc,
} from "#/lib/aspire/videos";

/**
 * The ASPIRE video library — the launcher and the panel it opens.
 *
 * Self-contained for the same reason `HelpLauncher` is: both the landing screen
 * and the chat screen render the rail, so threading `open` state through two
 * pages to reach one button would be two props and a piece of state in each.
 * The dialog is portalled to the body and does not care where its trigger sits.
 *
 * The a11y behaviour is the project's modal recipe, unchanged: Escape closes,
 * Tab is trapped inside, focus is captured before opening and handed back on
 * close. What is added here is that closing also stops whatever is playing —
 * audio continuing from a dialog nobody can see is the worst version of this.
 */
export function VideoLauncher() {
	const [open, setOpen] = useState(false);
	const [mounted, setMounted] = useState(false);
	const [videos, setVideos] = useState<Array<AspireVideo> | null>(null);
	const [failed, setFailed] = useState(false);
	const dialogId = useId();
	const triggerRef = useRef<HTMLButtonElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	const returnFocusTo = useRef<HTMLElement | null>(null);

	// The portal is client-only: during SSR there is no document to look for.
	useEffect(() => setMounted(true), []);

	// Fetched on first open, not on mount: most sessions never open this, and
	// the rail is on every page.
	useEffect(() => {
		if (!open || videos !== null) return;
		let live = true;
		fetchVideos()
			.then((list) => live && setVideos(list))
			.catch(() => live && setFailed(true));
		return () => {
			live = false;
		};
	}, [open, videos]);

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
				'button:not([disabled]), video[controls], [href], [tabindex]:not([tabindex="-1"])',
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

	// Nothing keeps playing into a closed dialog.
	useEffect(() => {
		if (open) return;
		for (const media of document.querySelectorAll<HTMLVideoElement>(
			".video-lib video",
		)) {
			media.pause();
		}
	}, [open]);

	return (
		<>
			<button
				ref={triggerRef}
				type="button"
				className="btn-help btn-videos"
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? dialogId : undefined}
				onClick={() => setOpen(true)}
			>
				<span className="btn-help__glyph">
					<VideoIcon />
				</span>
				<span className="rail__fold">Videos</span>
			</button>

			{open && mounted
				? createPortal(
						<div className="help video-lib">
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
										ASPIRE videos
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
									<p className="video-lib__lead">
										Short animated stories from ASPIRE, set in St. Kitts and
										Nevis.
									</p>
									{failed ? (
										<p className="video-lib__empty">
											The video library could not be reached. Please try again.
										</p>
									) : videos === null ? (
										<p className="video-lib__empty">Loading videos…</p>
									) : videos.length === 0 ? (
										<p className="video-lib__empty">
											There are no videos to show yet.
										</p>
									) : (
										<ul className="video-lib__list">
											{videos.map((video) => (
												<li key={video.id}>
													<VideoCard video={video} />
												</li>
											))}
										</ul>
									)}
								</div>
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

/**
 * One video: its poster, what it is about, and a way to start it.
 *
 * Used by the library panel and by the in-conversation card, so a video looks
 * and behaves the same whether it was browsed to or offered.
 */
export function VideoCard({
	video,
	compact = false,
}: {
	video: AspireVideo;
	compact?: boolean;
}) {
	const [started, setStarted] = useState(false);
	const mediaRef = useRef<HTMLVideoElement>(null);
	const titleId = useId();

	function start() {
		setStarted(true);
		// After the state that adds `controls`, so the element the browser plays
		// is the one the reader can then pause.
		queueMicrotask(() => void mediaRef.current?.play().catch(() => undefined));
	}

	return (
		<article
			className="video-card"
			data-compact={compact || undefined}
			aria-labelledby={titleId}
		>
			<div className="video-card__stage">
				{/*
				  One element throughout, rather than a poster image swapped for a
				  player. `preload="metadata"` with a `#t=` fragment makes the browser
				  paint a real frame from the film, which is a truer thumbnail than
				  anything that could be drawn for it — and it costs a few hundred
				  kilobytes, not the 77MB the file weighs.

				  `controls` only appears once the reader has asked for it, so the
				  resting state is a picture rather than a widget.
				*/}
				{/* biome-ignore lint/a11y/useMediaCaption: no caption track has been supplied for these films yet */}
				<video
					ref={mediaRef}
					className="video-card__media"
					src={`${videoSrc(video)}#t=3`}
					preload="metadata"
					playsInline
					controls={started}
					aria-labelledby={titleId}
				/>
				{started ? null : (
					<button
						type="button"
						className="video-card__play"
						onClick={start}
						aria-describedby={titleId}
					>
						<span className="video-card__play-glyph" aria-hidden="true">
							<PlayIcon size={22} />
						</span>
						<span className="sr-only">Play {video.title}</span>
					</button>
				)}
				<span className="video-card__runtime" aria-hidden="true">
					{runtime(video.duration_seconds)}
				</span>
			</div>

			<div className="video-card__text">
				<p className="video-card__meta">
					<span className="video-card__topic">{video.topic}</span>
					<span className="video-card__setting">{video.setting}</span>
				</p>
				<h3 className="video-card__title" id={titleId}>
					{video.title}
				</h3>
				<p className="video-card__blurb">{video.description}</p>
			</div>
		</article>
	);
}
