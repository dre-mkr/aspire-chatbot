/** Case 13, as aurora. Identical questions to the other two -- see lib/persona-probe.mjs. */

import { probeSteps } from "../lib/persona-probe.mjs";

export const suite = {
	name: "judging_persona_aurora",
	identity: "E",
	description: "The shared persona probe, answered as aurora.",
};

export async function steps() {
	return probeSteps("aurora");
}
