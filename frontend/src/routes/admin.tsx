/** The admin route tree. */
import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useState } from "react";
import { AlertIcon } from "#/components/icons";
import {
	changePassword,
	type Role,
	setToken,
	signIn,
	token,
} from "#/lib/admin/api";

export const Route = createFileRoute("/admin")({
	component: AdminShell,
});

type Session = { role: Role; email: string; mustChange: boolean } | null;

function AdminShell() {
	// Restored from the tab, but WITHOUT a role read back from storage — a role the client remembered is a role the…
	const [session, setSession] = useState<Session>(() =>
		token() ? { role: "reviewer", email: "", mustChange: false } : null,
	);

	if (!session) return <SignInForm onSignedIn={setSession} />;

	if (session.mustChange) {
		return (
			<ChangePasswordForm
				onChanged={() => setSession({ ...session, mustChange: false })}
			/>
		);
	}

	return (
		<div className="adm-shell">
			<header className="adm-bar">
				<nav className="adm-nav">
					<img
						className="adm-nav__mark"
						src="/brand/aspire-wordmark.png"
						width={190}
						height={48}
						alt="ASPIRE"
					/>
					<Link
						to="/admin/applications"
						className="adm-nav__link"
						activeProps={{ "data-active": "" }}
					>
						Applications
					</Link>
					<Link
						to="/admin/widgets"
						className="adm-nav__link"
						activeProps={{ "data-active": "" }}
					>
						Widgets
					</Link>
				</nav>
				<span className="adm-who">
					{session.email}
					<button
						type="button"
						className="adm-signout"
						onClick={() => {
							setToken(null);
							setSession(null);
						}}
					>
						Sign out
					</button>
				</span>
			</header>
			<main className="adm-main">
				<Outlet />
			</main>
		</div>
	);
}

function SignInForm({
	onSignedIn,
}: {
	onSignedIn: (session: Session) => void;
}) {
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [problem, setProblem] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	return (
		<Centred>
			<form
				className="adm-card"
				onSubmit={async (event) => {
					event.preventDefault();
					setBusy(true);
					setProblem(null);
					try {
						const result = await signIn(email.trim(), password);
						setToken(result.token);
						onSignedIn({
							role: result.role,
							email: result.email,
							mustChange: result.must_change_password,
						});
					} catch (error) {
						// The server says the same thing for a wrong password and a missing account.
						setProblem((error as Error).message);
					} finally {
						setBusy(false);
					}
				}}
			>
				<img
					className="adm-card__mark"
					src="/brand/aspire-wordmark.png"
					width={190}
					height={48}
					alt="ASPIRE"
				/>
				<h1 className="adm-card__title">Staff sign-in</h1>
				<p className="adm-card__sub">
					A separate sign-in from the chat. Your session is held for this tab
					only.
				</p>

				<Field
					id="staff-email"
					label="Email"
					type="email"
					value={email}
					onChange={setEmail}
					autoComplete="username"
					placeholder="you@aspire.kn"
				/>
				<Field
					id="staff-password"
					label="Password"
					type="password"
					value={password}
					onChange={setPassword}
					autoComplete="current-password"
					placeholder="Your password"
				/>

				{problem ? <Problem>{problem}</Problem> : null}

				<button type="submit" disabled={busy} className="adm-primary">
					{busy ? "Checking…" : "Sign in"}
				</button>
			</form>
		</Centred>
	);
}

function ChangePasswordForm({ onChanged }: { onChanged: () => void }) {
	const [current, setCurrent] = useState("");
	const [next, setNext] = useState("");
	const [confirm, setConfirm] = useState("");
	const [problem, setProblem] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);

	return (
		<Centred>
			<form
				className="adm-card"
				onSubmit={async (event) => {
					event.preventDefault();
					if (next !== confirm) {
						setProblem("Those two do not match.");
						return;
					}
					setBusy(true);
					setProblem(null);
					try {
						const { token: replacement } = await changePassword(current, next);
						// The old token died with the password.
						setToken(replacement);
						onChanged();
					} catch (error) {
						setProblem((error as Error).message);
					} finally {
						setBusy(false);
					}
				}}
			>
				<img
					className="adm-card__mark"
					src="/brand/aspire-wordmark.png"
					width={190}
					height={48}
					alt="ASPIRE"
				/>
				<h1 className="adm-card__title">Choose a password</h1>
				<p className="adm-card__sub">
					Your account was set up with a temporary password. Change it before
					going any further — the queue is not available until you do.
				</p>

				<Field
					id="current-password"
					label="Temporary password"
					type="password"
					value={current}
					onChange={setCurrent}
					autoComplete="current-password"
				/>
				<Field
					id="new-password"
					label="New password"
					type="password"
					value={next}
					onChange={setNext}
					autoComplete="new-password"
					hint="At least 12 characters. A phrase you will remember beats a short scramble you will write down."
				/>
				<Field
					id="confirm-password"
					label="Type it again"
					type="password"
					value={confirm}
					onChange={setConfirm}
					autoComplete="new-password"
				/>

				{problem ? <Problem>{problem}</Problem> : null}

				<button type="submit" disabled={busy} className="adm-primary">
					{busy ? "Saving…" : "Save and continue"}
				</button>
			</form>
		</Centred>
	);
}

/* ── the small shared pieces ────────────────────────────────────────────── */

function Centred({ children }: { children: ReactNode }) {
	return <div className="adm-page">{children}</div>;
}

function Field({
	id,
	label,
	type,
	value,
	onChange,
	autoComplete,
	hint,
	placeholder,
}: {
	id: string;
	label: string;
	type: string;
	value: string;
	onChange: (value: string) => void;
	autoComplete: string;
	hint?: string;
	placeholder?: string;
}) {
	const hintId = `${id}-hint`;
	return (
		<div className="adm-field">
			<label className="adm-field__label" htmlFor={id}>
				{label}
			</label>
			<input
				id={id}
				className="adm-field__input"
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				autoComplete={autoComplete}
				placeholder={placeholder}
				aria-describedby={hint ? hintId : undefined}
				required
			/>
			{hint ? (
				<p className="adm-field__hint" id={hintId}>
					{hint}
				</p>
			) : null}
		</div>
	);
}

function Problem({ children }: { children: ReactNode }) {
	return (
		<p role="alert" className="adm-problem">
			<AlertIcon size={17} />
			{children}
		</p>
	);
}
