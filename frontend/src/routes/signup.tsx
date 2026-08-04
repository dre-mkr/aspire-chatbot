import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { Field } from "#/components/auth/Field";
import { AuthError, register } from "#/lib/aspire/auth";
import { keys } from "#/lib/aspire/queries";

/**
 * Creating an account, at `/signup`.
 *
 * Four steps, submitted once at the end. The steps are a wizard in the browser
 * rather than four round trips: a half-finished account is not a useful thing
 * to have in the table, and somebody who gives up at step 3 should leave
 * nothing behind.
 *
 * Date of birth is asked first, before any credentials, because it decides
 * everything after it. Under 13, the account belongs to the adult named in
 * step 3 — their email and password in step 4 — and the child's details ride
 * along on it. That is the one place this form's shape changes, and it changes
 * as soon as the birth date is complete rather than at the end.
 */

const ISLANDS = ["St. Kitts", "Nevis"];

const SCHOOLS = [
	"Basseterre High School",
	"Washington Archibald High School",
	"Cayon High School",
	"Verchilds High School",
	"Charlestown Secondary School",
	"Gingerland Secondary School",
	"Primary school",
	"Not in school right now",
];

const MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
];

/** Old enough to hold an account alone. Mirrors `MINOR_AGE` in the service. */
const MINOR_AGE = 13;

function safeNext(value: unknown): string | undefined {
	if (typeof value !== "string") return undefined;
	if (!value.startsWith("/") || value.startsWith("//")) return undefined;
	return value;
}

export const Route = createFileRoute("/signup")({
	validateSearch: (search: Record<string, unknown>) => {
		const next = safeNext(search.next);
		return next ? { next } : {};
	},
	component: SignUp,
});

function ageFrom(day: string, month: string, year: string): number | null {
	const d = Number(day);
	const m = Number(month);
	const y = Number(year);
	if (!d || !m || !y || String(y).length !== 4) return null;
	const today = new Date();
	let age = today.getFullYear() - y;
	if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) {
		age -= 1;
	}
	return age;
}

function SignUp() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { next } = Route.useSearch();

	const [step, setStep] = useState(1);
	const [busy, setBusy] = useState(false);
	const [errors, setErrors] = useState<Record<string, string>>({});

	const [first, setFirst] = useState("");
	const [last, setLast] = useState("");
	const [day, setDay] = useState("");
	const [month, setMonth] = useState("");
	const [year, setYear] = useState("");
	const [island, setIsland] = useState("");
	const [school, setSchool] = useState("");
	const [gName, setGName] = useState("");
	const [gEmail, setGEmail] = useState("");
	const [gPhone, setGPhone] = useState("");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");

	const age = useMemo(() => ageFrom(day, month, year), [day, month, year]);
	const isMinor = age !== null && age < MINOR_AGE;

	const stepLabels = [
		"About you",
		"Where you live",
		isMinor ? "Your grown-up" : "Someone we can tell",
		"Sign-in details",
	];

	function fail(field: string, message: string) {
		setErrors({ [field]: message });
		return false;
	}

	function validate(): boolean {
		setErrors({});
		if (step === 1) {
			if (!first.trim()) return fail("first", "We need a first name.");
			if (!last.trim()) return fail("last", "We need a last name.");
			if (age === null) return fail("dob", "Fill in the whole date of birth.");
			if (age < 0 || age > 120) return fail("dob", "Check that date — it looks wrong.");
			return true;
		}
		if (step === 3 && isMinor) {
			// Refused here as well as by the service. An under-13 account without
			// a named adult is the one shape this form must not be able to send.
			if (!gName.trim()) return fail("gName", "Name the adult who will hold this account.");
			if (!gEmail.trim()) return fail("gEmail", "We need their email — it signs in to this account.");
			return true;
		}
		if (step === 4) {
			if (!email.trim()) return fail("email", "We need an email to sign in with.");
			if (password.length < 10) {
				return fail("password", "Use at least 10 characters.");
			}
			return true;
		}
		return true;
	}

	async function submit() {
		if (!validate() || busy) return;
		setBusy(true);
		try {
			await register({
				// Under 13 the adult's address is the account's, so step 4 collects
				// theirs and this sends it as the credential either way.
				email: email.trim(),
				password,
				firstName: first.trim(),
				lastName: last.trim(),
				dateOfBirth: `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
				island: island || null,
				school: school || null,
				guardianName: isMinor ? gName.trim() : null,
				guardianEmail: isMinor ? gEmail.trim() : null,
				guardianPhone: isMinor ? gPhone.trim() : null,
			});

			// The previous identity's data must not survive the change of owner.
			queryClient.removeQueries({ queryKey: keys.allConversations() });
			queryClient.removeQueries({ queryKey: keys.allGames() });
			queryClient.removeQueries({ queryKey: keys.allEligibility() });
			await queryClient.invalidateQueries({ queryKey: keys.allConversations() });

			// Re-validated at the point of use; see the note in signin.tsx.
			void navigate({
				to: safeNext(next) ?? "/",
				replace: true,
				search: (previous: Record<string, unknown>) => previous,
			});
		} catch (error) {
			const failure =
				error instanceof AuthError
					? error
					: new AuthError("Something went wrong. Please try again.");
			// A duplicate email belongs on step 4, where the email is.
			if (failure.field === "email" || failure.field === "password") {
				setStep(4);
			}
			setErrors({ [failure.field]: failure.message });
		} finally {
			setBusy(false);
		}
	}

	function advance() {
		if (!validate()) return;
		if (step === 4) {
			void submit();
			return;
		}
		setStep(step + 1);
	}

	return (
		<AuthSurface
			title={
				step === 1
					? "Let us start with you"
					: step === 2
						? "Where do you live?"
						: step === 3
							? isMinor
								? "Who looks after you?"
								: "Someone we can tell"
							: "Your sign-in details"
			}
			subtitle={
				step === 1
					? "Your date of birth decides which version of ASPIRE you get, so it has to be right."
					: step === 2
						? "This helps us point you at the right modules and schools."
						: step === 3
							? isMinor
								? "An adult holds this account. They sign in, and you use it with them."
								: "Someone we can reach about your progress. Optional."
								: "Last step. This is what you will sign in with."
			}
			step={{ current: step, total: 4, label: stepLabels[step - 1] }}
			onBack={() => (step === 1 ? navigate({ to: "/signin" }) : setStep(step - 1))}
			backLabel={step === 1 ? "Back to sign in" : "Back"}
			footText={step === 1 ? "Already have an account?" : undefined}
			footLinkLabel={step === 1 ? "Sign in" : undefined}
			footLinkTo={step === 1 ? "/signin" : undefined}
		>
			<div className="auth__fields">
				{step === 1 ? (
					<>
						<Field
							label="First name"
							icon="user"
							value={first}
							onChange={setFirst}
							placeholder="First name"
							autoComplete="given-name"
							error={errors.first}
						/>
						<Field
							label="Last name"
							icon="user"
							value={last}
							onChange={setLast}
							placeholder="Last name"
							autoComplete="family-name"
							error={errors.last}
						/>

						<fieldset className="field auth__fieldset">
							<legend className="field__label">Date of birth</legend>
							<div className="field__dob">
								<input
									className="field__input field__input--day"
									inputMode="numeric"
									maxLength={2}
									placeholder="DD"
									aria-label="Day"
									value={day}
									onChange={(e) => setDay(e.currentTarget.value.replace(/\D/g, ""))}
								/>
								<select
									className="field__input field__select"
									aria-label="Month"
									value={month}
									onChange={(e) => setMonth(e.currentTarget.value)}
								>
									<option value="">Month</option>
									{MONTHS.map((name, index) => (
										<option key={name} value={String(index + 1)}>
											{name}
										</option>
									))}
								</select>
								<input
									className="field__input field__input--year"
									inputMode="numeric"
									maxLength={4}
									placeholder="YYYY"
									aria-label="Year"
									value={year}
									onChange={(e) => setYear(e.currentTarget.value.replace(/\D/g, ""))}
								/>
							</div>
							{errors.dob ? (
								<span className="field__error" role="alert">
									{errors.dob}
								</span>
							) : isMinor ? (
								// Said as soon as it is known, not sprung at the end.
								<span className="field__hint">
									Under 13 — a parent or guardian will hold this account, and we
									will ask for them next.
								</span>
							) : (
								<span className="field__hint">
									We ask so the assistant talks to you at the right level.
								</span>
							)}
						</fieldset>
					</>
				) : null}

				{step === 2 ? (
					<>
						<fieldset className="field auth__fieldset">
							<legend className="field__label">Island</legend>
							<div className="auth__choices">
								{ISLANDS.map((name) => (
									<button
										type="button"
										key={name}
										className="auth__choice"
										data-selected={island === name || undefined}
										aria-pressed={island === name}
										onClick={() => setIsland(name)}
									>
										{name}
									</button>
								))}
							</div>
						</fieldset>
						<div className="field">
							<label className="field__label" htmlFor="school">
								School
							</label>
							<select
								id="school"
								className="field__input field__select"
								value={school}
								onChange={(e) => setSchool(e.currentTarget.value)}
							>
								<option value="">Choose a school</option>
								{SCHOOLS.map((name) => (
									<option key={name} value={name}>
										{name}
									</option>
								))}
							</select>
							<span className="field__hint">You can change this later.</span>
						</div>
					</>
				) : null}

				{step === 3 ? (
					<>
						<Field
							label={isMinor ? "Their name" : "Their name"}
							icon="user"
							value={gName}
							onChange={setGName}
							placeholder="Full name"
							error={errors.gName}
						/>
						<Field
							label="Their email"
							icon="mail"
							type="email"
							inputMode="email"
							value={gEmail}
							onChange={setGEmail}
							placeholder="them@example.com"
							hint={
								isMinor
									? "This is the address that signs in to the account."
									: undefined
							}
							error={errors.gEmail}
						/>
						<Field
							label="Their phone"
							icon="phone"
							inputMode="tel"
							value={gPhone}
							onChange={setGPhone}
							placeholder="869 000 0000"
							hint="Optional."
						/>
					</>
				) : null}

				{step === 4 ? (
					<>
						<Field
							label={isMinor ? "Their email" : "Email"}
							icon="mail"
							type="email"
							inputMode="email"
							autoComplete="email"
							value={email}
							onChange={setEmail}
							placeholder="you@example.com"
							hint={isMinor ? "The adult named in the last step signs in with this." : undefined}
							error={errors.email}
							disabled={busy}
						/>
						<Field
							label="Password"
							icon="lock"
							type="password"
							autoComplete="new-password"
							revealable
							value={password}
							onChange={setPassword}
							placeholder="At least 10 characters"
							error={errors.password}
							disabled={busy}
						/>
						<ul className="auth__reqs">
							<li data-ok={password.length >= 10 || undefined}>10 characters or more</li>
							<li data-ok={/[0-9]/.test(password) || undefined}>one number helps</li>
						</ul>
					</>
				) : null}

				{errors.form ? (
					<p className="auth__form-error" role="alert">
						{errors.form}
					</p>
				) : null}

				<button type="button" className="auth__primary" onClick={advance} disabled={busy}>
					{step === 4 ? (busy ? "Creating your account" : "Create account") : "Continue"}
				</button>

				{step === 1 ? (
					<span className="auth__secondary-note">
						Signing up keeps your chats when you switch device, and gets them back
						if this browser is cleared.
					</span>
				) : null}
			</div>
		</AuthSurface>
	);
}
