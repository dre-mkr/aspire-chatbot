import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { Field } from "#/components/auth/Field";
import {
	AuthError,
	redeemSignInLink,
	requestReset,
	requestSignInLink,
	signIn,
} from "#/lib/aspire/auth";
import { keys } from "#/lib/aspire/queries";

/** Signing in, at `/signin`. */

interface SignInSearch {
	next?: string;
	/** From the passwordless email link, which `mail.py` sends here. */
	token?: string;
}

/** Only same-origin paths. Anything else falls back to the empty state. */
function safeNext(value: unknown): string | undefined {
	if (typeof value !== "string") return undefined;
	// Reject any second character that is a slash OR a backslash.
	if (!value.startsWith("/") || /^[/\\]/.test(value.slice(1))) return undefined;
	return value;
}

export const Route = createFileRoute("/signin")({
	// Full-document SSR, stated rather than inherited.
	ssr: true,
	validateSearch: (search: Record<string, unknown>): SignInSearch => {
		// `token` was DROPPED here, so the passwordless link in the email landed
		// on a plain sign-in form and its fifteen-minute token was never
		// redeemed. `requestSignInLink` worked; the other half never fired.
		const next = safeNext(search.next);
		const token = typeof search.token === "string" ? search.token : undefined;
		return { ...(next ? { next } : {}), ...(token ? { token } : {}) };
	},
	component: SignIn,
});

function SignIn() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { next, token } = Route.useSearch();

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [busy, setBusy] = useState(false);
	/** Which email went out, so the confirmation can say the right thing. */
	const [sent, setSent] = useState<"signin" | "reset" | null>(null);
	const [errors, setErrors] = useState<{
		email?: string;
		password?: string;
		form?: string;
	}>({});

	/** Everything user-scoped belongs to whoever is signed in. */
	function resetScopedCaches() {
		queryClient.removeQueries({ queryKey: keys.allConversations() });
		queryClient.removeQueries({ queryKey: keys.allGames() });
		queryClient.removeQueries({ queryKey: keys.allEligibility() });
	}

	/**
	 * Redeem a token that arrived in the URL, from the passwordless email link.
	 *
	 * `mail.py` sends `/signin?token=…`, and this route used to discard it in
	 * `validateSearch`, so the link opened a plain sign-in form and the reader
	 * typed a password they had asked not to need. Once, guarded by a ref: the
	 * token is single-use, and a second attempt would fail against a link that
	 * had just worked.
	 */
	const redeemed = useRef(false);
	// biome-ignore lint/correctness/useExhaustiveDependencies: the `redeemed` ref is the guard — this runs once per token and must not re-run when a helper's identity changes
	useEffect(() => {
		if (!token || redeemed.current) return;
		redeemed.current = true;
		setBusy(true);
		void redeemSignInLink(token)
			.then(async () => {
				resetScopedCaches();
				await queryClient.invalidateQueries({
					queryKey: keys.allConversations(),
				});
				void navigate({ to: safeNext(next) ?? "/", replace: true });
			})
			.catch((error) => {
				setErrors({
					form:
						error instanceof AuthError
							? error.message
							: "That sign-in link has expired. Ask for a fresh one.",
				});
			})
			.finally(() => setBusy(false));
		// `resetScopedCaches` is stable for this component's life.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [token, next, navigate, queryClient]);

	async function submit(event: React.FormEvent) {
		event.preventDefault();
		if (busy) return;
		setBusy(true);
		setErrors({});

		try {
			const result = await signIn(email.trim(), password);
			resetScopedCaches();
			// Refetched at once so claimed conversations appear without a reload.
			await queryClient.invalidateQueries({
				queryKey: keys.allConversations(),
			});
			// Checked again here, deliberately.
			void navigate({
				to: safeNext(next) ?? "/",
				// A signed-in person should not be able to press Back into the sign-in page they just used.
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
			setSent("signin");
		} catch (error) {
			setErrors({
				form:
					error instanceof AuthError
						? error.message
						: "Could not send that link.",
			});
		} finally {
			setBusy(false);
		}
	}

	/**
	 * THE PRODUCT HAD NO WAY TO RESET A PASSWORD.
	 *
	 * `requestReset` has existed in `auth.ts` since the account work landed and
	 * had zero callers; `/reset` and `/verify` both tell a reader to "ask for a
	 * fresh one" and neither says where. Somebody who forgot their password
	 * could not get back into their own account at all.
	 *
	 * The link is here, on the screen where they discover the problem, and it
	 * reuses the confirmation the sign-in link already had.
	 */
	async function sendReset() {
		if (busy || !email.trim()) {
			setErrors({ email: "Enter your email and we will send a reset link." });
			return;
		}
		setBusy(true);
		setErrors({});
		try {
			await requestReset(email.trim());
			setSent("reset");
		} catch (error) {
			setErrors({
				form:
					error instanceof AuthError
						? error.message
						: "Could not send that link.",
			});
		} finally {
			setBusy(false);
		}
	}

	if (sent) {
		return (
			<AuthSurface
				title="Check your email"
				subtitle={`We sent a ${sent === "reset" ? "password reset" : "sign-in"} link to ${email.trim()}. It works once and expires in fifteen minutes.`}
			>
				<p className="auth__note">
					Nothing arrived? Look in spam, then ask for another link. Nobody can
					get in without it.
				</p>
				{/* "Try again" was a link to `/signin` — the page this already is —
				 * so a reader who mistyped their address tapped it, watched nothing
				 * happen, and had no way back to the form. */}
				<button
					type="button"
					className="auth__secondary"
					onClick={() => {
						setSent(null);
						setErrors({});
					}}
				>
					Use a different address
				</button>
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
					{busy ? <span className="auth__spin" aria-hidden="true" /> : null}
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

				<button
					type="button"
					className="auth__quiet-link"
					onClick={sendReset}
					disabled={busy}
				>
					Forgot your password?
				</button>
			</form>
		</AuthSurface>
	);
}
