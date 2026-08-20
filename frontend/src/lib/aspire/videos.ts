/** The ASPIRE story videos, as the client needs to know them. */
import { API_URL } from "../config";

/** The catalog is small and static; a slow one is a panel that opens empty. */
const TIMEOUT_MS = 8_000;

/** One video from the ASPIRE library. */
export interface AspireVideo {
	id: string;
	title: string;
	description: string;
	/** The subject, as a reader would name it. Shown as a chip. */
	topic: string;
	/** Where the story is set. Always Saint Kitts and Nevis. */
	setting: string;
	duration_seconds: number;
	/**
	 * A path on our own origin, never an absolute URL.
	 *
	 * The server sends `/videos/<file>` precisely so the same payload is right
	 * on localhost, on staging and behind the CDN — and so nothing in this
	 * feature can ever point a reader off-site.
	 */
	src: string;
}

/** `4:22`. The library card's one piece of hard information. */
export function runtime(seconds: number): string {
	const total = Math.max(0, Math.round(seconds));
	const minutes = Math.floor(total / 60);
	return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * Every video in the library.
 *
 * Unfiltered on purpose: the server decides what may be OFFERED unasked
 * mid-conversation, but the panel is a reader opening a library deliberately.
 */
export async function fetchVideos(): Promise<Array<AspireVideo>> {
	const response = await fetch(`${API_URL}/api/videos`, {
		headers: { "Content-Type": "application/json" },
		signal: AbortSignal.timeout(TIMEOUT_MS),
	});
	if (!response.ok) throw new Error(`videos: ${response.status}`);
	const body = (await response.json()) as { videos?: Array<AspireVideo> };
	return body.videos ?? [];
}

/** The full URL to play, from the origin-relative path the server sent. */
export function videoSrc(video: AspireVideo): string {
	// Served by the same host that serves the app, not by the API. In dev those
	// are different ports, so the path is resolved against the page, not API_URL.
	return video.src;
}
