/** The answer settings both conversation pages read out of the address. */

import { asPersonaId, type PersonaId } from "./personas";

export interface AnswerSearch {
	simple?: true;
	/** Who the assistant is answering for. */
	persona?: PersonaId;
	/** Which language the conversation is being held in. */
	lang?: "en" | "es" | "fr";
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
	const lang = asLanguage(search.lang);
	return {
		...(search.simple === true || search.simple === "true"
			? { simple: true as const }
			: {}),
		...(persona ? { persona } : {}),
		...(lang ? { lang } : {}),
	};
}
