/** Case 13, as orion. Identical questions to the other two -- see lib/persona-probe.mjs. */

import { probeSteps } from "../lib/persona-probe.mjs";

export const suite = {
	name: "judging_persona_orion",
	identity: "D",
	description: "The shared persona probe, answered as orion.",
};

export async function steps() {
	return probeSteps("orion");
}
