import { useEffect, useRef, useState } from "react";
import {
	type AspireVideo,
	fetchVideos,
	runtime,
	videoSrc,
} from "#/lib/aspire/videos";
import { ViewHeader } from "./ViewHeader";

/**
 * Miracle Mountain: the ASPIRE films, from the catalog that actually holds them.
 *
 * THE TWO STORIES WERE TYPED INTO THIS FILE, AND THE CARDS DID NOTHING.
 * Each carried `cursor-pointer`, a hover shadow and a `group-hover:scale-105`
 * on its artwork — every signal a reader has for "this is a control" — with no
 * click handler behind any of it. A card that lifts under the cursor and then
 * ignores the click is worse than a card that sits still, because the reader
 * concludes the page is broken rather than that the card is a picture.
 *
 * They are driven from `/api/videos` now, which is the same catalog the
 * assistant matches on, so a film added to the programme appears here without
 * anyone remembering to retype its running time. And they play.
 */
export function StoriesView({ onBack }: { onBack: () => void }) {
	const [videos, setVideos] = useState<Array<AspireVideo> | null>(null);
	const [failed, setFailed] = useState(false);
	const [playing, setPlaying] = useState<AspireVideo | null>(null);
	const playerRef = useRef<HTMLVideoElement>(null);

	useEffect(() => {
		let live = true;
		fetchVideos()
			.then((rows) => {
				if (live) setVideos(rows);
			})
			.catch(() => {
				if (live) setFailed(true);
			});
		return () => {
			live = false;
		};
	}, []);

	// A story chosen is a story started; nobody taps a film to look at a paused
	// first frame.
	useEffect(() => {
		if (playing) playerRef.current?.play().catch(() => undefined);
	}, [playing]);

	return (
		<div className="view">
			<ViewHeader onBack={onBack} />

			<main className="view__main">
				<div className="view__head">
					{/* Was an `h2` with no `h1` above it anywhere on the page, set in
					 * Instrument Serif's bold — a weight the file does not carry, so
					 * the browser synthesised one by smearing the strokes. */}
					<h1 className="view__title">Miracle Mountain</h1>
					<p className="view__lede">
						Interactive financial tales of St. Kitts &amp; Nevis.
					</p>
				</div>

				{playing ? (
					<section className="panel stories__player">
						{/* biome-ignore lint/a11y/useMediaCaption: the catalog carries no
						    caption tracks yet; the description below stands in. */}
						<video
							ref={playerRef}
							key={playing.id}
							src={videoSrc(playing)}
							controls
							playsInline
							className="stories__video"
						/>
						<h2 className="panel__title">{playing.title}</h2>
						<p>{playing.description}</p>
						<button
							type="button"
							className="stories__close"
							onClick={() => setPlaying(null)}
						>
							<i className="ph-bold ph-arrow-left" aria-hidden="true" /> All
							stories
						</button>
					</section>
				) : failed ? (
					<div className="history__empty" role="alert">
						<i
							className="ph-duotone ph-cloud-warning history__empty-mark"
							aria-hidden="true"
						/>
						<p>The story library is not answering just now.</p>
					</div>
				) : videos === null ? (
					<div className="panel-row" aria-busy="true">
						<span className="sr-only">Loading the story library</span>
						{[0, 1].map((n) => (
							<div className="panel stories__card stories__card--ghost" key={n}>
								<span className="stories__art" />
								<span className="stories__ghost-line" />
								<span className="stories__ghost-line stories__ghost-line--short" />
							</div>
						))}
					</div>
				) : videos.length === 0 ? (
					<div className="history__empty">
						<i
							className="ph-duotone ph-film-slate history__empty-mark"
							aria-hidden="true"
						/>
						<p>No stories have been published yet.</p>
					</div>
				) : (
					<div className="panel-row">
						{videos.map((video) => (
							<button
								type="button"
								key={video.id}
								className="panel stories__card"
								onClick={() => setPlaying(video)}
							>
								<span className="stories__art" aria-hidden="true">
									<i className="ph-fill ph-play" />
								</span>
								<span className="stories__title">{video.title}</span>
								<span className="stories__meta">
									{video.setting} &middot; {runtime(video.duration_seconds)}
								</span>
								<span className="stories__blurb">{video.description}</span>
							</button>
						))}
					</div>
				)}
			</main>
		</div>
	);
}
