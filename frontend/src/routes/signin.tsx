import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { Field } from "#/components/auth/Field";
import { AuthError, requestSignInLink, signIn } from "#/lib/aspire/auth";
import { keys } from "#/lib/aspire/queries";

/**
 * Signing in, at `/signin`.
 *
 * A full route rather than a modal, because it is a place you can be sent to
 * and a place you can link somebody to — and because a modal over a
 * conversation would put the thing you were reading behind a scrim while you
 * type a password.
 *
 * `next` is carried through the whole flow so that signing in returns you to
 * what you were doing rather than to a generic landing screen. It is validated
 * as a path on this origin: an unchecked redirect target is how a sign-in page
 * becomes a way to bounce somebody to another site with a trusted-looking link.
 */

interface SignInSearch {
	next?: string;
}

/** Only same-origin paths. Anything else falls back to the empty state. */
function safeNext(value: unknown): string | undefined {
	if (typeof value !== "string") return undefined;
	if (!value.startsWith("/") || value.startsWith("//")) return undefined;
	return value;
}

export const Route = createFileRoute("/signin")({
	validateSearch: (search: Record<string, unknown>): SignInSearch => {
		const next = safeNext(search.next);
		return next ? { next } : {};
	},
	component: SignIn,
});

function SignIn() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { next } = Route.useSearch();

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [busy, setBusy] = useState(false);
	const [linkSent, setLinkSent] = useState(false);
	const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>(
		{},
	);

	/**
	 * Everything user-scoped belongs to whoever is signed in.
	 *
	 * Removed rather than invalidated: invalidating leaves the previous
	 * identity's data readable while the refetch is in flight, and the rail
	 * showing somebody else's conversation titles for even one frame is exactly
	 * what must not happen.
	 */
	function resetScopedCaches() {
		queryClient.removeQueries({ queryKey: keys.allConversations() });
		queryClient.removeQueries({ queryKey: ["games"] });
		queryClient.removeQueries({ queryKey: ["eligibility"] });
	}

	async function submit(event: React.FormEvent) {
		event.preventDefault();
		if (busy) return;
		setBusy(true);
		setErrors({});

		try {
			const result = await signIn(email.trim(), password);
			resetScopedCaches();
			// The claimed conversations have to appear without a manual reload,
			// so the list is asked for again the moment the identity changes.
			await queryClient.invalidateQueries({ queryKey: keys.allConversations() });
			// Checked again here, deliberately. The validator on the route is the
			// first line, but the value that matters is the one handed to
			// `navigate`, and an unchecked redirect target is how a sign-in page
			// becomes a way to bounce somebody to another site behind a link that
			// looks like ours. Two cheap checks beat one clever one.
			void navigate({
				to: safeNext(next) ?? "/",
				// A signed-in person should not be able to press Back into the
				// sign-in page they just used.
				replace: true,
				search: (previous: Record<string, unknown>) => previous,
			});
			void result;
		} catch (error) {
			const failure =
				error instanceof AuthError
					? error
					: new AuthError("Something went wrong. Please try again.");
			setErrors({ [failure.field]: failure.message });
		} finally {
			setBusy(false);
		}
	}

	async function sendLink() {
		if (busy || !email.trim()) {
			setErrors({ email: "Enter your email first, and we will send a link." });
			return;
		}
		setBusy(true);
		setErrors({});
		try {
			await requestSignInLink(email.trim());
			setLinkSent(true);
		} catch (error) {
			setErrors({
				form: error instanceof AuthError ? error.message : "Could not send that link.",
			});
		} finally {
			setBusy(false);
		}
	}

	if (linkSent) {
		return (
			<AuthSurface
				title="Check your email"
				subtitle={`We sent a sign-in link to ${email.trim()}. It works once and expires in fifteen minutes.`}
				footText="Wrong address?"
				footLinkLabel="Try again"
				footLinkTo="/signin"
			>
				<p className="auth__note">
					Nothing arrived? Look in spam, then ask for another link. Nobody can get
					in without it.
				</p>
			</AuthSurface>
		);
	}

	return (
		<AuthSurface
			title="Welcome back"
			subtitle="Sign in to keep going."
			footText="New to ASPIRE?"
			footLinkLabel="Create an account"
			footLinkTo="/signup"
			footNote="Setting this up for a child under 13? Make your own account first."
		>
			<form className="auth__fields" onSubmit={submit} noValidate>
				<Field
					label="Email"
					icon="mail"
					type="email"
					inputMode="email"
					autoComplete="email"
					value={email}
					onChange={setEmail}
					placeholder="you@example.com"
					disabled={busy}
					error={errors.email}
				/>
				<Field
					label="Password"
					icon="lock"
					type="password"
					autoComplete="current-password"
					revealable
					value={password}
					onChange={setPassword}
					placeholder="Your password"
					disabled={busy}
					error={errors.password}
				/>

				{errors.form ? (
					<p className="auth__form-error" role="alert">
						{errors.form}
					</p>
				) : null}

				<button type="submit" className="auth__primary" disabled={busy}>
					{busy ? "Signing you in" : "Sign in"}
				</button>

				<button
					type="button"
					className="auth__secondary"
					onClick={sendLink}
					disabled={busy}
				>
					Email me a sign-in link
				</button>
				<span className="auth__secondary-note">
					No password needed — we send a link that signs you in.
				</span>
			</form>
		</AuthSurface>
	);
}
