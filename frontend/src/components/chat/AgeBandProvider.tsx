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
		// 88pt for the youngest band: the push-to-talk button is the primary input, so it is sized as a primary control…
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
			{/* The scale is published as a CSS variable as well as through context, because widgets are rendered inside `dan… */}
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

/** Whether drag-and-drop may be used for this band. */
export function dragAllowed(config: BandConfig): boolean {
	return config.dragAllowed;
}
