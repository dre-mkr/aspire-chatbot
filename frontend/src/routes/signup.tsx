import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { AuthSurface } from "#/components/auth/AuthSurface";
import { Field } from "#/components/auth/Field";
import { AuthError, register } from "#/lib/aspire/auth";
import { asPersonaId } from "#/lib/aspire/personas";
import { keys } from "#/lib/aspire/queries";

/** Creating an account, at `/signup`. */

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

type Role = "participant" | "guardian" | "educator";

/** The three answers, in the order somebody scans them. */
const ROLES: ReadonlyArray<{ id: Role; label: string; blurb: string }> = [
	{
		id: "participant",
		label: "I'm joining ASPIRE",
		blurb: "You are the young person taking part, aged 5 to 18.",
	},
	{
		id: "guardian",
		label: "I'm a parent or guardian",
		blurb: "You are applying for a child, or looking after their account.",
	},
	{
		id: "educator",
		label: "I'm a teacher or educator",
		blurb: "You teach the material or support students who take part.",
	},
];

/** Old enough to hold an account alone. Mirrors `MINOR_AGE` in the service. */
const MINOR_AGE = 13;

/** Above this, `band_for` returns `adult`. */
const ADULT_ABOVE = 18;

const ADULT_ROLES: ReadonlySet<Role> = new Set<Role>(["guardian", "educator"]);

/** Which steps this role walks. The contact step is a participant's alone. */
type StepId = "role" | "about" | "place" | "contact" | "credentials";

function stepsFor(role: Role | null): StepId[] {
	const base: StepId[] = ["role", "about", "place"];
	// An adult role has no separate adult to name — they are the adult, and the server drops anything that arrives…
	if (role === "participant") base.push("contact");
	base.push("credentials");
	return base;
}

function safeNext(value: unknown): string | undefined {
	if (typeof value !== "string") return undefined;
	if (!value.startsWith("/") || value.startsWith("//")) return undefined;
	return value;
}

export const Route = createFileRoute("/signup")({
	// Full-document SSR, stated rather than inherited.
	ssr: true,
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
	if (
		today.getMonth() + 1 < m ||
		(today.getMonth() + 1 === m && today.getDate() < d)
	) {
		age -= 1;
	}
	return age;
}

function SignUp() {
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { next } = Route.useSearch();

	const [role, setRole] = useState<Role | null>(null);
	const [index, setIndex] = useState(0);
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

	const steps = useMemo(() => stepsFor(role), [role]);
	const step = steps[index] ?? "role";

	const age = useMemo(() => ageFrom(day, month, year), [day, month, year]);
	const isMinor = role === "participant" && age !== null && age < MINOR_AGE;
	const adultRole = role !== null && ADULT_ROLES.has(role);
	// Only meaningful once the date is complete; `age === null` is "not finished typing", not "too young", and must…
	const tooYoungForRole = adultRole && age !== null && age <= ADULT_ABOVE;

	const LABELS: Record<StepId, string> = {
		role: "About this account",
		about: adultRole ? "About you" : "About you",
		place: "Where you live",
		contact: isMinor ? "Your grown-up" : "Someone we can tell",
		credentials: "Sign-in details",
	};

	function fail(field: string, message: string) {
		setErrors({ [field]: message });
		return false;
	}

	function validate(): boolean {
		setErrors({});
		if (step === "role") {
			if (role === null) return fail("role", "Choose who this account is for.");
			return true;
		}
		if (step === "about") {
			if (!first.trim()) return fail("first", "We need a first name.");
			if (!last.trim()) return fail("last", "We need a last name.");
			if (age === null) return fail("dob", "Fill in the whole date of birth.");
			if (age < 0 || age > 120)
				return fail("dob", "Check that date — it looks wrong.");
			if (tooYoungForRole) {
				// The check that closes the trap this redesign exists for.
				return fail(
					"dob",
					role === "guardian"
						? "This should be your own date of birth, not your child's — their details come later, with the application."
						: "A teacher or educator account is held by someone over 18.",
				);
			}
			return true;
		}
		if (step === "contact" && isMinor) {
			// Refused here as well as by the service.
			if (!gName.trim())
				return fail("gName", "Name the adult who will hold this account.");
			if (!gEmail.trim())
				return fail(
					"gEmail",
					"We need their email — it signs in to this account.",
				);
			return true;
		}
		if (step === "credentials") {
			if (!email.trim())
				return fail("email", "We need an email to sign in with.");
			if (password.length < 10) {
				return fail("password", "Use at least 10 characters.");
			}
			return true;
		}
		return true;
	}

	async function submit() {
		if (!validate() || busy || role === null) return;
		setBusy(true);
		try {
			const result = await register({
				role,
				// Under 13 the adult's address is the account's, so the last step collects theirs and this sends it as the cred…
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
			await queryClient.invalidateQueries({
				queryKey: keys.allConversations(),
			});

			// The persona the account actually resolved to, as the SERVER derived it, carried into the app so the picker op…
			const persona = asPersonaId(result.persona);

			// Re-validated at the point of use; see the note in signin.tsx.
			void navigate({
				to: safeNext(next) ?? "/",
				replace: true,
				search: (previous: Record<string, unknown>) => ({
					...previous,
					...(persona ? { persona } : {}),
				}),
			});
		} catch (error) {
			const failure =
				error instanceof AuthError
					? error
					: new AuthError("Something went wrong. Please try again.");
			// A duplicate email belongs on the step the email is on.
			if (failure.field === "email" || failure.field === "password") {
				setIndex(steps.indexOf("credentials"));
			}
			setErrors({ [failure.field]: failure.message });
		} finally {
			setBusy(false);
		}
	}

	function advance() {
		if (!validate()) return;
		if (step === "credentials") {
			void submit();
			return;
		}
		setIndex(index + 1);
	}

	const TITLES: Record<StepId, string> = {
		role: "Who is this account for?",
		about: adultRole ? "About you" : "Let us start with you",
		place: "Where do you live?",
		contact: isMinor ? "Who looks after you?" : "Someone we can tell",
		credentials: "Your sign-in details",
	};

	const SUBTITLES: Record<StepId, string> = {
		role: "It decides which assistant you get and what the rest of this form asks for.",
		about:
			role === "guardian"
				? "Your own details — your child's come later, with the application itself."
				: role === "educator"
					? "Your own details. Nothing here is shared with your students."
					: "Your date of birth decides which version of ASPIRE you get, so it has to be right.",
		place: "This helps us point you at the right modules and schools.",
		contact: isMinor
			? "An adult holds this account. They sign in, and you use it with them."
			: "Someone we can reach about your progress. Optional.",
		credentials: "Last step. This is what you will sign in with.",
	};

	return (
		<AuthSurface
			title={TITLES[step]}
			subtitle={SUBTITLES[step]}
			step={{
				current: index + 1,
				total: steps.length,
				label: LABELS[step],
			}}
			onBack={() =>
				index === 0 ? navigate({ to: "/signin" }) : setIndex(index - 1)
			}
			backLabel={index === 0 ? "Back to sign in" : "Back"}
			footText={index === 0 ? "Already have an account?" : undefined}
			footLinkLabel={index === 0 ? "Sign in" : undefined}
			footLinkTo={index === 0 ? "/signin" : undefined}
		>
			<div className="auth__fields">
				{step === "role" ? (
					<fieldset className="field auth__fieldset">
						<legend className="sr-only">Who this account is for</legend>
						<div className="auth__roles">
							{ROLES.map((option) => (
								<button
									type="button"
									key={option.id}
									className="auth__role"
									data-selected={role === option.id || undefined}
									aria-pressed={role === option.id}
									onClick={() => {
										setRole(option.id);
										setErrors({});
									}}
								>
									<span className="auth__role-label">{option.label}</span>
									<span className="auth__role-blurb">{option.blurb}</span>
								</button>
							))}
						</div>
						{errors.role ? (
							<span className="field__error" role="alert">
								{errors.role}
							</span>
						) : null}
					</fieldset>
				) : null}

				{step === "about" ? (
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
							<legend className="field__label">
								{adultRole ? "Your date of birth" : "Date of birth"}
							</legend>
							<div className="field__dob">
								<input
									className="field__input field__input--day"
									inputMode="numeric"
									maxLength={2}
									placeholder="DD"
									aria-label="Day"
									value={day}
									onChange={(e) =>
										setDay(e.currentTarget.value.replace(/\D/g, ""))
									}
								/>
								<select
									className="field__input field__select"
									aria-label="Month"
									value={month}
									onChange={(e) => setMonth(e.currentTarget.value)}
								>
									<option value="">Month</option>
									{MONTHS.map((name, monthIndex) => (
										<option key={name} value={String(monthIndex + 1)}>
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
									onChange={(e) =>
										setYear(e.currentTarget.value.replace(/\D/g, ""))
									}
								/>
							</div>
							{errors.dob ? (
								<span className="field__error" role="alert">
									{errors.dob}
								</span>
							) : adultRole ? (
								// Said before the field is filled in, not after it is rejected.
								<span className="field__hint">
									{role === "guardian"
										? "Yours, not your child's. Their date of birth is part of the application."
										: "Yours. A teacher account is held by someone over 18."}
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

				{step === "place" ? (
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
								{role === "educator" ? "Where you teach" : "School"}
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

				{step === "contact" ? (
					<>
						<Field
							label="Their name"
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

				{step === "credentials" ? (
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
							hint={
								isMinor
									? "The adult named in the last step signs in with this."
									: undefined
							}
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
							<li data-ok={password.length >= 10 || undefined}>
								10 characters or more
							</li>
							<li data-ok={/[0-9]/.test(password) || undefined}>
								one number helps
							</li>
						</ul>
					</>
				) : null}

				{errors.form ? (
					<p className="auth__form-error" role="alert">
						{errors.form}
					</p>
				) : null}

				<button
					type="button"
					className="auth__primary"
					onClick={advance}
					disabled={busy}
				>
					{step === "credentials"
						? busy
							? "Creating your account"
							: "Create account"
						: "Continue"}
				</button>

				{step === "role" ? (
					<span className="auth__secondary-note">
						Signing up keeps your chats when you switch device, and gets them
						back if this browser is cleared.
					</span>
				) : null}
			</div>
		</AuthSurface>
	);
}
