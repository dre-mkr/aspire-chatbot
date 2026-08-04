import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { AuthError, redeemSignInLink } from "#/lib/aspire/auth";

/**
 * Where the confirm-your-email and sign-in links land, at `/verify?token=…`.
 *
 * Both kinds of link arrive here and both are spent immediately — there is
 * nothing to ask, so there is nothing to show but the outcome. The redemption
 * runs once even under React's double-invoked effects in development, because
 * the token is single-use and spending it twice would turn a working link into
 * an expired one on the first visit.
 */

export const Route = createFileRoute("/verify")({
	// Full-document SSR, stated rather than inherited. This form is entirely
	// client-interactive, but it is also the first paint a signed-out visitor
	// gets, so the shell should arrive as HTML rather than after the bundle.
	// It was rendering this way already -- by inheriting `defaultSsr` from a
	// declaration that lived in a generated file. Saying so here means the mode
	// is a decision on the record and survives the next regeneration.
	ssr: true,
	validateSearch: (search: Record<string, unknown>) => ({
		token: typeof search.token === "string" ? search.token : "",
	}),
	component: Verify,
});

function Verify() {
	const { token } = Route.useSearch();
	const navigate = useNavigate();
	const [failed, setFailed] = useState("");
	const spent = useRef(false);

	useEffect(() => {
		if (!token || spent.current) return;
		spent.current = true;
		void redeemSignInLink(token)
			.then(() => navigate({ to: "/", replace: true }))
			.catch((error) =>
				setFailed(
					error instanceof AuthError
						? error.message
						: "That link could not be used. Please ask for another.",
				),
			);
	}, [token, navigate]);

	if (!token || failed) {
		return (
			<AuthSurface
				title={failed ? "That link has been used" : "That link is incomplete"}
				subtitle={
					failed
						? "Sign-in links work once and expire quickly, which is what keeps them safe to send by email. Ask for a fresh one."
						: "The link looks like it was cut short somewhere. Ask for a new one and it will arrive in a moment."
				}
				footText="Back to"
				footLinkLabel="sign in"
				footLinkTo="/signin"
			>
				<span />
			</AuthSurface>
		);
	}

	return (
		<AuthSurface title="Signing you in" subtitle="One moment.">
			<span />
		</AuthSurface>
	);
}
