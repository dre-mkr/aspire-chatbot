import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { onPersonaRefused } from "../stream/session";
import { asPersonaId, type PersonaId, personaById } from "./personas";
import type { AnswerSearch } from "./search";
import { useSession } from "./use-session";

/**
 * The three answer settings, read from the address rather than from state, so
 * a conversation can be shared or reloaded exactly as it was being read.
 *
 * A hook over the URL rather than a layout route: it renders nothing and holds
 * nothing across a navigation, so both pages can use it without sharing a
 * mount. `strict: false` is what lets one hook serve two routes.
 */
export function useAnswerSettings() {
	const navigate = useNavigate();
	const search = useSearch({ strict: false }) as AnswerSearch;

	/** The persona the signed-in account resolves to, derived server-side. */
	const { session } = useSession();
	const accountPersona =
		session?.accountType === "registered" ? asPersonaId(session.persona) : null;
	const persona = search.persona ?? accountPersona ?? null;
	/** Set only when a guide was picked by name; otherwise the session decides. */
	const band = search.band ?? null;

	const simpleMode = search.simple === true;
	const toggleSimpleMode = useCallback(() => {
		void navigate({
			to: ".",
			// Spread, not replace.
			search: (previous: AnswerSearch): AnswerSearch =>
				previous.simple
					? { ...previous, simple: undefined }
					: { ...previous, simple: true },
			replace: true,
		});
	}, [navigate]);

	// `replace`, like the toggle above: picking a persona adjusts the view, not the history.
	const setPersona = useCallback(
		(next: PersonaId | null, band?: AnswerSearch["band"]) => {
			void navigate({
				to: ".",
				search: (previous: AnswerSearch): AnswerSearch => ({
					...previous,
					persona: next ?? undefined,
					// Cleared rather than carried: a band belonging to the guide
					// just left would otherwise follow the reader to the next one.
					band: next ? band : undefined,
				}),
				replace: true,
			});
		},
		[navigate],
	);

	// `replace`, like the other two settings: language adjusts the view, not the history.
	const setLanguageInUrl = useCallback(
		(next: "en" | "es" | "fr") => {
			void navigate({
				to: ".",
				search: (previous: AnswerSearch): AnswerSearch => ({
					...previous,
					lang: next,
				}),
				replace: true,
			});
		},
		[navigate],
	);

	/** A persona the server would not grant, said out loud and then corrected. */
	const [personaNotice, setPersonaNotice] = useState<string | null>(null);
	const dismissPersonaNotice = useCallback(() => setPersonaNotice(null), []);

	useEffect(() => {
		return onPersonaRefused(({ requested, granted }) => {
			const grantedId = asPersonaId(granted);
			const requestedName =
				personaById(asPersonaId(requested))?.name ?? requested;
			const grantedName = personaById(grantedId)?.name ?? granted;
			setPersonaNotice(
				`${requestedName} is not available on this account, so answers stay with ${grantedName}.`,
			);
			// Corrected rather than left disagreeing with the session.
			setPersona(grantedId);
		});
	}, [setPersona]);

	return {
		simpleMode,
		toggleSimpleMode,
		persona,
		band,
		setPersona,
		lang: search.lang,
		setLanguageInUrl,
		personaNotice,
		dismissPersonaNotice,
	};
}
