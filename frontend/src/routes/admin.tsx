/**
 * The admin route tree. A separate tree, a separate realm, one backend.
 *
 * Mounted at `/admin`, outside `_shell` — so it inherits none of the chat's
 * layout, none of its providers, and none of its session handling. That
 * separation is structural rather than cosmetic: a component that cannot reach
 * the chat's auth context cannot accidentally send its token.
 *
 * ## The password gate is a gate
 *
 * A seeded account arrives with `must_change_password` and this shell renders
 * the change form INSTEAD of the portal until it clears. Not a banner, not a
 * reminder — the queue is not reachable. A temporary password that can be used
 * indefinitely is a permanent password that several people know.
 *
 * ## Sign-in is an email and a password, never a pasted token
 *
 * The token exists and a human should never handle one. Pasting a bearer token
 * into a form trains people to move bearer tokens around, which is the habit
 * that eventually puts one in a chat message.
 */
import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useState } from "react";
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
	// Restored from the tab, but WITHOUT a role read back from storage — a role
	// the client remembered is a role the client chose. Every request is
	// authorised by the server from the token regardless, so this only ever
	// decides what to draw.
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
		<div
			style={{
				minHeight: "100vh",
				background: "var(--wash-3)",
				fontFamily: "var(--font-sans)",
				color: "var(--prose)",
			}}
		>
			<header
				style={{
					display: "flex",
					alignItems: "center",
					justifyContent: "space-between",
					gap: "1rem",
					padding: "0.75rem 1.25rem",
					background: "white",
					borderBottom: "1px solid var(--hairline)",
				}}
			>
				<nav style={{ display: "flex", gap: "1.25rem", alignItems: "center" }}>
					<strong style={{ color: "var(--plum-deep)" }}>ASPIRE admin</strong>
					<Link
						to="/admin/applications"
						style={{ color: "var(--plum)", textDecoration: "none" }}
						activeProps={{ style: { fontWeight: 700 } }}
					>
						Applications
					</Link>
					<Link
						to="/admin/widgets"
						style={{ color: "var(--plum)", textDecoration: "none" }}
						activeProps={{ style: { fontWeight: 700 } }}
					>
						Widgets
					</Link>
				</nav>
				<span
					style={{
						display: "flex",
						gap: "0.75rem",
						alignItems: "center",
						fontSize: "0.85rem",
						color: "var(--quiet)",
					}}
				>
					{session.email}
					<button
						type="button"
						onClick={() => {
							setToken(null);
							setSession(null);
						}}
						style={{
							minHeight: "44px",
							padding: "0.375rem 0.875rem",
							borderRadius: "0.5rem",
							border: "1px solid var(--hairline)",
							background: "transparent",
							color: "var(--slate)",
							cursor: "pointer",
						}}
					>
						Sign out
					</button>
				</span>
			</header>
			<main style={{ padding: "1.25rem", maxWidth: "84rem", margin: "0 auto" }}>
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
						// The server says the same thing for a wrong password and a
						// missing account. This must not add a distinction it
						// deliberately did not make.
						setProblem((error as Error).message);
					} finally {
						setBusy(false);
					}
				}}
				style={card}
			>
				<h1 style={heading}>ASPIRE admin</h1>
				<p style={subheading}>
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
				/>
				<Field
					id="staff-password"
					label="Password"
					type="password"
					value={password}
					onChange={setPassword}
					autoComplete="current-password"
				/>

				{problem ? <Problem>{problem}</Problem> : null}

				<button type="submit" disabled={busy} style={primary}>
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
						// The old token died with the password. Swapping it here is
						// what stops the person who just did the right thing from
						// being signed out for it.
						setToken(replacement);
						onChanged();
					} catch (error) {
						setProblem((error as Error).message);
					} finally {
						setBusy(false);
					}
				}}
				style={card}
			>
				<h1 style={heading}>Choose a password</h1>
				<p style={subheading}>
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

				<button type="submit" disabled={busy} style={primary}>
					{busy ? "Saving…" : "Save and continue"}
				</button>
			</form>
		</Centred>
	);
}

/* ── the small shared pieces ────────────────────────────────────────────── */

function Centred({ children }: { children: ReactNode }) {
	return (
		<div
			style={{
				minHeight: "100vh",
				display: "grid",
				placeItems: "center",
				background: "var(--wash-6)",
				fontFamily: "var(--font-sans)",
				padding: "1rem",
			}}
		>
			{children}
		</div>
	);
}

function Field({
	id,
	label,
	type,
	value,
	onChange,
	autoComplete,
	hint,
}: {
	id: string;
	label: string;
	type: string;
	value: string;
	onChange: (value: string) => void;
	autoComplete: string;
	hint?: string;
}) {
	return (
		<div style={{ marginBlockEnd: "0.875rem" }}>
			<label
				htmlFor={id}
				style={{
					display: "block",
					fontSize: "0.85rem",
					marginBlockEnd: "0.25rem",
					color: "var(--slate)",
				}}
			>
				{label}
			</label>
			<input
				id={id}
				type={type}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				autoComplete={autoComplete}
				required
				style={{
					width: "100%",
					minHeight: "44px",
					padding: "0.5rem 0.75rem",
					borderRadius: "0.5rem",
					border: "1px solid var(--hairline)",
					fontSize: "1rem",
				}}
			/>
			{hint ? (
				<p
					style={{
						margin: "0.25rem 0 0",
						fontSize: "0.8rem",
						color: "var(--quiet)",
					}}
				>
					{hint}
				</p>
			) : null}
		</div>
	);
}

function Problem({ children }: { children: ReactNode }) {
	return (
		<p
			role="alert"
			style={{
				margin: "0 0 0.875rem",
				padding: "0.5rem 0.75rem",
				borderRadius: "0.5rem",
				background: "var(--danger-wash)",
				border: "1px solid var(--danger-line)",
				color: "var(--danger)",
				fontSize: "0.9rem",
			}}
		>
			{children}
		</p>
	);
}

const card = {
	width: "min(26rem, 100%)",
	padding: "1.5rem",
	borderRadius: "1rem",
	background: "white",
	border: "1px solid var(--hairline)",
} as const;

const heading = {
	margin: "0 0 0.5rem",
	fontSize: "1.25rem",
	color: "var(--plum-deep)",
} as const;

const subheading = {
	margin: "0 0 1.25rem",
	color: "var(--quiet)",
	fontSize: "0.9rem",
	lineHeight: 1.45,
} as const;

const primary = {
	width: "100%",
	minHeight: "44px",
	borderRadius: "0.5rem",
	border: "1px solid var(--plum)",
	background: "var(--plum)",
	color: "white",
	fontWeight: 600,
	fontSize: "1rem",
	cursor: "pointer",
} as const;
