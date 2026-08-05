/**
 * The age band, and everything it decides about the interface.
 *
 * One context, read by the composer, the chips, the voice layer and every
 * widget. It exists so that "what does a six-year-old's screen look like?" has
 * a single answer in a single file rather than a `band === "5-8"` check in
 * fifteen components that will drift.
 *
 * ## The band comes from the server session and from nowhere else
 *
 * Not from a prop a parent component chose, not from local storage, not from a
 * query parameter. It is minted into the session token from the account record
 * (see `backend/app/graph/identity.py`), and this provider reads it from the
 * session the server issued. Anything else would make the youngest, most
 * protected configuration selectable by whoever opens the console.
 *
 * `useAgeBand` outside a provider returns the 5-8 configuration rather than
 * throwing. That is deliberate and it is the conservative direction: a
 * component rendered outside the tree gets the largest targets, the simplest
 * layout and speech on, which is safe for everybody and merely unnecessary for
 * an adult.
 */
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
	/**
	 * The free-text input starts collapsed behind a "type instead" affordance.
	 *
	 * COLLAPSED, never removed. It is an escape hatch: a child who wants to say
	 * something the chips do not cover must be able to, and a product that took
	 * the keyboard away would be deciding what a six-year-old is allowed to ask.
	 */
	inputCollapsed: boolean;
	/** Drag-and-drop is excluded outright below 13. See `dragAllowed`. */
	dragAllowed: boolean;
	/** Push-to-talk button size, in CSS pixels. */
	micSize: number;
}

/**
 * The four configurations, written out rather than computed from the band.
 *
 * A table beats a set of conditionals here for the same reason the access
 * matrix is a table: the question people ask of this file is "what does a
 * nine-year-old get?", and the answer should be one row to read.
 */
const CONFIGS: Record<AgeBand, BandConfig> = {
	"5-8": {
		band: "5-8",
		typeScale: 20,
		// 64, not 44. A six-year-old's tap is imprecise and a missed tap on a
		// quick reply reads to them as the app ignoring them.
		touchTarget: 64,
		ttsDefault: true,
		chipsDominant: true,
		inputCollapsed: true,
		dragAllowed: false,
		// 88pt for the youngest band: the push-to-talk button is the primary
		// input, so it is sized as a primary control rather than as an icon.
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
			{/*
			 * The scale is published as a CSS variable as well as through
			 * context, because widgets are rendered inside `dangerously`-free
			 * islands that size themselves in CSS and should not each have to
			 * read React state to know how big their text is.
			 */}
			<div
				data-age-band={config.band}
				style={
					{
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

/**
 * Whether drag-and-drop may be used for this band.
 *
 * A named function rather than a field read, because it is a product rule and
 * it is asked in several places. Drag-and-drop is excluded for 5-8 and 9-12
 * outright: it is a fine-motor task, it is hostile on a phone held one-handed,
 * and it fails completely for anyone using a switch, a keyboard or a screen
 * reader. Everything it would do, a tap-then-tap does.
 */
export function dragAllowed(config: BandConfig): boolean {
	return config.dragAllowed;
}
