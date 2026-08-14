import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { AuthError, confirmEmail } from "#/lib/aspire/auth";

/** Where the confirm-your-email link lands, at `/verify?token=…`.
 *
 * The sign-in link lands on `/signin?token=…` -- `mail.py` addresses them
 * separately, and they carry different purposes, which `_redeem` checks. */

export const Route = createFileRoute("/verify")({
	// Full-document SSR, stated rather than inherited.
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
		void confirmEmail(token)
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
				title={failed ? "That link did not work" : "That link is incomplete"}
				subtitle={
					failed
						? "Confirmation links work once and expire after a day, which is what keeps them safe to send by email. Ask for a fresh one."
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
