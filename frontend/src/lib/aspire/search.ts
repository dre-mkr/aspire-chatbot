/** The answer settings both conversation pages read out of the address. */

import { type AgeBand, asPersonaId, type PersonaId } from "./personas";

export interface AnswerSearch {
	simple?: true;
	/** Who the assistant is answering for. */
	persona?: PersonaId;
	/** Which language the conversation is being held in. */
	lang?: "en" | "es" | "fr";
	/**
	 * Which band the persona answers at, where it carries more than one voice.
	 *
	 * `stella` is Skye at 5-8 and Kaleb at 9-12. The persona alone cannot say
	 * which, so a reader asking for Kaleb by name needs this to travel with it.
	 */
	band?: AgeBand;
}

const LANGUAGES = ["en", "es", "fr"] as const;

function asLanguage(value: unknown): "en" | "es" | "fr" | undefined {
	return typeof value === "string" &&
		(LANGUAGES as ReadonlyArray<string>).includes(value)
		? (value as "en" | "es" | "fr")
		: undefined;
}

/**
 * Shared by `/` and `/chat/$chatId` so the two pages agree on the schema
 * without a layout route between them to hold it.
 */
export function validateAnswerSearch(
	search: Record<string, unknown>,
): AnswerSearch {
	// User-editable, so `?persona=nonsense` must land on "not chosen".
	const persona = asPersonaId(search.persona);
	// The band separates Skye from Kaleb, which the persona alone cannot.
	const band = ["5-8", "9-12", "13-15", "16-18", "adult"].includes(
		String(search.band),
	)
		? (String(search.band) as AnswerSearch["band"])
		: undefined;
	const lang = asLanguage(search.lang);
	return {
		...(search.simple === true || search.simple === "true"
			? { simple: true as const }
			: {}),
		...(persona ? { persona } : {}),
		...(band ? { band } : {}),
		...(lang ? { lang } : {}),
	};
}
