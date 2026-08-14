/** Case 13, as stella. Identical questions to the other two -- see lib/persona-probe.mjs. */

import { probeSteps } from "../lib/persona-probe.mjs";

export const suite = {
	name: "judging_persona_stella",
	identity: "B",
	description: "The shared persona probe, answered as stella.",
};

export async function steps() {
	return probeSteps("stella");
}
