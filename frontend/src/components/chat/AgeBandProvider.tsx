/** The age band, and everything it decides about the interface. */
import { createContext, type ReactNode, useContext, useMemo } from "react";

export type AgeBand = "5-8" | "9-12" | "13-15" | "16-18" | "adult";

export interface BandConfig {
	band: AgeBand;
	/** Body type size in pixels. Not a Tailwind step: widgets need the number. */
	typeScale: number;
	/** Minimum tap target, in CSS pixels at 1x. 44 is the WCAG floor. */
	touchTarget: number;
	/** Speech on by default. A per-user preference overrides it in the client. */
	ttsDefault: boolean;
	/** Quick replies dominate the surface rather than sitting under it. */
	chipsDominant: boolean;
	/** The free-text input starts collapsed behind a "type instead" affordance. */
	inputCollapsed: boolean;
	/** Drag-and-drop is excluded outright below 13. See `dragAllowed`. */
	dragAllowed: boolean;
	/** Push-to-talk button size, in CSS pixels. */
	micSize: number;
}

/** The four configurations, written out rather than computed from the band. */
const CONFIGS: Record<AgeBand, BandConfig> = {
	"5-8": {
		band: "5-8",
		typeScale: 20,
		// 64, not 44.
		touchTarget: 64,
		ttsDefault: true,
		chipsDominant: true,
		inputCollapsed: true,
		dragAllowed: false,
		// 88pt for the youngest band: push-to-talk is the primary input, so it is sized as one.
		micSize: 88,
	},
	"9-12": {
		band: "9-12",
		typeScale: 18,
		touchTarget: 56,
		ttsDefault: true,
		chipsDominant: true,
		inputCollapsed: false,
		dragAllowed: false,
		micSize: 64,
	},
	"13-15": {
		band: "13-15",
		typeScale: 16,
		touchTarget: 44,
		ttsDefault: false,
		chipsDominant: false,
		inputCollapsed: false,
		dragAllowed: true,
		micSize: 48,
	},
	"16-18": {
		band: "16-18",
		typeScale: 16,
		touchTarget: 44,
		ttsDefault: false,
		chipsDominant: false,
		inputCollapsed: false,
		dragAllowed: true,
		micSize: 44,
	},
	adult: {
		band: "adult",
		typeScale: 16,
		touchTarget: 44,
		ttsDefault: false,
		chipsDominant: false,
		inputCollapsed: false,
		dragAllowed: true,
		micSize: 44,
	},
};

/** The conservative default: largest targets, speech on, input collapsed. */
const FALLBACK = CONFIGS["5-8"];

const BandContext = createContext<BandConfig>(FALLBACK);

export function configFor(band: string | null | undefined): BandConfig {
	return CONFIGS[(band ?? "") as AgeBand] ?? FALLBACK;
}

/**
 * The band a chosen guide implies.
 *
 * This whole table used to run on one route — `/admin/widgets`, the internal
 * preview — so every real reader fell through to `FALLBACK` and got the
 * five-year-old's interface: 20px type, 64px targets, no dragging. A teacher
 * uploading a document got it too.
 *
 * Conservative on purpose, in two directions. A guide that spans two bands
 * takes the younger one — `stella` covers 5 to 12 and gets `5-8` — and a reader
 * who has not said who they are keeps the fallback rather than being assumed
 * adult. Nothing here can shrink a target for somebody who did not ask.
 *
 * The server's `age_band` on the graph session is finer than this, and when it
 * is plumbed through it should win; this is what the client can know on its own.
 */
export function bandForPersona(persona: string | null | undefined): AgeBand {
	switch (persona) {
		case "stella":
			return "5-8";
		case "orion":
			return "13-15";
		case "aurora":
		case "nova":
			return "adult";
		default:
			// `everyone`, or nobody has said. A child may be reading.
			return FALLBACK.band;
	}
}

export function AgeBandProvider({
	band,
	children,
}: {
	/** From the server-issued session. Never from a prop chosen locally. */
	band: string | null | undefined;
	children: ReactNode;
}) {
	const config = useMemo(() => configFor(band), [band]);
	return (
		<BandContext.Provider value={config}>
			{/* A CSS variable as well as context: widgets read the scale from inline
			    styles. `display: contents` so this can wrap a whole screen without
			    becoming a box in the middle of its layout — custom properties still
			    inherit down the element tree from an element that has no box. */}
			<div
				data-age-band={config.band}
				style={
					{
						display: "contents",
						"--band-type": `${config.typeScale}px`,
						"--band-target": `${config.touchTarget}px`,
					} as React.CSSProperties
				}
			>
				{children}
			</div>
		</BandContext.Provider>
	);
}

export function useAgeBand(): BandConfig {
	return useContext(BandContext);
}
