import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { Field } from "#/components/auth/Field";
import { AuthError, completeReset } from "#/lib/aspire/auth";

/**
 * Where a password-reset email lands, at `/reset?token=…`.
 *
 * The token is single-use and the service spends it here. Arriving with a
 * missing or expired one is the ordinary case rather than an error worth
 * dressing up — links get forwarded, opened twice, and read a week later — so
 * it says so plainly and offers the one useful next step.
 */

export const Route = createFileRoute("/reset")({
	validateSearch: (search: Record<string, unknown>) => ({
		token: typeof search.token === "string" ? search.token : "",
	}),
	component: Reset,
});

function Reset() {
	const { token } = Route.useSearch();
	const navigate = useNavigate();

	const [password, setPassword] = useState("");
	const [repeat, setRepeat] = useState("");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	if (!token) {
		return (
			<AuthSurface
				title="That link is incomplete"
				subtitle="Password links work once and expire after an hour. Ask for a fresh one and it will arrive in a moment."
				footText="Back to"
				footLinkLabel="sign in"
				footLinkTo="/signin"
			>
				<span />
			</AuthSurface>
		);
	}

	async function submit(event: React.FormEvent) {
		event.preventDefault();
		if (busy) return;
		if (password !== repeat) {
			setError("These two do not match yet.");
			return;
		}
		setBusy(true);
		setError("");
		try {
			await completeReset(token, password);
			// Straight in. Having just proved control of the address and set a
			// password, being asked to type it again would be theatre.
			void navigate({ to: "/", replace: true });
		} catch (failure) {
			setError(
				failure instanceof AuthError
					? failure.message
					: "Could not set that password. Please try again.",
			);
		} finally {
			setBusy(false);
		}
	}

	return (
		<AuthSurface
			title="Set a new password"
			subtitle="Almost done. Pick something you will remember."
			footText="Changed your mind?"
			footLinkLabel="Back to sign in"
			footLinkTo="/signin"
		>
			<form className="auth__fields" onSubmit={submit} noValidate>
				<Field
					label="New password"
					icon="lock"
					type="password"
					autoComplete="new-password"
					revealable
					value={password}
					onChange={setPassword}
					placeholder="New password"
					disabled={busy}
					error={error && password !== repeat ? "" : error}
				/>
				<Field
					label="Type it once more"
					icon="lock"
					type="password"
					autoComplete="new-password"
					value={repeat}
					onChange={setRepeat}
					placeholder="Repeat it"
					disabled={busy}
					error={repeat && repeat !== password ? "These two do not match yet." : ""}
				/>
				<ul className="auth__reqs">
					<li data-ok={password.length >= 10 || undefined}>10 characters or more</li>
					<li data-ok={/[0-9]/.test(password) || undefined}>one number helps</li>
					<li data-ok={(password.length > 0 && password === repeat) || undefined}>
						both boxes match
					</li>
				</ul>
				<button type="submit" className="auth__primary" disabled={busy}>
					{busy ? "Saving" : "Save and sign in"}
				</button>
			</form>
		</AuthSurface>
	);
}
