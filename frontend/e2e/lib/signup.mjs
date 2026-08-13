/**
 * The real /signup wizard, walked the way a person walks it.
 *
 * Date of birth is the only lever that sets the age band, and the band is what
 * decides which agents are reachable (backend/app/graph/access.py). The persona
 * picker in the chat can narrow, never widen — so identities are made here.
 *
 * The advance button is type="button" inside no <form>: Enter never submits.
 */

const STEPS = [
	{ name: "role", probe: ".auth__role" },
	{ name: "about", probe: 'input[aria-label="Day"]' },
	{ name: "place", probe: "#school" },
	{ name: "contact", probe: 'input[placeholder="them@example.com"]' },
	{ name: "credentials", probe: 'input[placeholder="At least 10 characters"]' },
];

const ROLE_LABEL = {
	participant: "I'm joining ASPIRE",
	guardian: "I'm a parent or guardian",
	educator: "I'm a teacher or educator",
};

async function currentStep(page) {
	for (const step of STEPS) {
		if (await page.$(step.probe)) return step.name;
	}
	return null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function clickByText(page, selector, text) {
	return page.evaluate(
		(sel, want) => {
			for (const node of document.querySelectorAll(sel)) {
				if ((node.innerText || "").trim().startsWith(want)) {
					node.click();
					return true;
				}
			}
			return false;
		},
		selector,
		text,
	);
}

/**
 * The page is server-rendered, so a click can land before React attaches and be
 * silently lost. `aria-pressed` flipping is proof the component's state updated —
 * i.e. proof of hydration — so retry until it does.
 */
async function press(page, selector, text) {
	for (let attempt = 0; attempt < 25; attempt++) {
		await clickByText(page, selector, text);
		const took = await page.evaluate(
			(sel, want) =>
				[...document.querySelectorAll(sel)].some(
					(node) =>
						(node.innerText || "").trim().startsWith(want) &&
						node.getAttribute("aria-pressed") === "true",
				),
			selector,
			text,
		);
		if (took) return;
		await sleep(200);
	}
	throw new Error(`${selector} ${JSON.stringify(text)} never took the press`);
}

/** Same problem: a controlled input drops text typed before hydration. */
async function fill(page, selector, value) {
	await page.waitForSelector(selector, { visible: true });
	const wanted = String(value);
	for (let attempt = 0; attempt < 8; attempt++) {
		await page.click(selector, { clickCount: 3 });
		await page.type(selector, wanted, { delay: 1 });
		const got = await page.$eval(selector, (node) => node.value);
		if (got === wanted) return;
		await sleep(200);
	}
	throw new Error(`${selector} would not hold ${JSON.stringify(wanted)}`);
}

async function advance(page) {
	await page.click("button.auth__primary");
}

/** Any visible validation error, so a stuck wizard says why rather than timing out. */
async function problems(page) {
	return page.evaluate(() =>
		[...document.querySelectorAll('[role="alert"]')]
			.map((node) => (node.innerText || "").trim())
			.filter(Boolean),
	);
}

/**
 * @param identity {{role, first, last, dob: 'YYYY-MM-DD', email, password,
 *                   island?, guardianName?, guardianEmail?}}
 */
export async function signUp(page, baseUrl, identity) {
	await page.goto(`${baseUrl}/signup`, { waitUntil: "networkidle2" });

	const [year, month, day] = identity.dob.split("-");
	let guard = 0;

	for (;;) {
		if (guard++ > 12) throw new Error("signup wizard did not finish");

		const step = await currentStep(page);
		if (step === null) break; // navigated away — account created

		if (step === "role") {
			await press(page, "button.auth__role", ROLE_LABEL[identity.role]);
		} else if (step === "about") {
			await fill(page, 'input[placeholder="First name"]', identity.first);
			await fill(page, 'input[placeholder="Last name"]', identity.last);
			await fill(page, 'input[aria-label="Day"]', String(Number(day)));
			await page.select('select[aria-label="Month"]', String(Number(month)));
			await fill(page, 'input[aria-label="Year"]', year);
		} else if (step === "place") {
			if (identity.island) await press(page, "button.auth__choice", identity.island);
		} else if (step === "contact") {
			if (identity.guardianName) {
				await fill(page, 'input[placeholder="Full name"]', identity.guardianName);
				await fill(page, 'input[placeholder="them@example.com"]', identity.guardianEmail);
			}
		} else if (step === "credentials") {
			await fill(page, 'input[placeholder="you@example.com"]', identity.email);
			await fill(page, 'input[placeholder="At least 10 characters"]', identity.password);
		}

		const before = step;
		await advance(page);

		// Either the step changed, the wizard finished, or something was rejected.
		try {
			await page.waitForFunction(
				(probe) => !document.querySelector(probe),
				{ timeout: 15_000, polling: 100 },
				STEPS.find((s) => s.name === before).probe,
			);
		} catch {
			const found = await problems(page);
			throw new Error(
				`signup stuck on "${before}"${found.length ? `: ${found.join(" | ")}` : ""}`,
			);
		}
	}

	await page.waitForSelector("#aspire-composer", { visible: true, timeout: 30_000 });
	return readSession(page);
}

export async function signIn(page, baseUrl, identity) {
	await page.goto(`${baseUrl}/signin`, { waitUntil: "networkidle2" });
	await fill(page, 'input[placeholder="you@example.com"]', identity.email);
	await fill(page, 'input[placeholder="Your password"]', identity.password);
	await page.click("button.auth__primary");
	await page.waitForSelector("#aspire-composer", { visible: true, timeout: 30_000 });
	return readSession(page);
}

/** Signed out: the app mints an anonymous session on first load. */
export async function anonymous(page, baseUrl) {
	await page.goto(baseUrl, { waitUntil: "networkidle2" });
	await page.waitForSelector("#aspire-composer", { visible: true, timeout: 30_000 });
	return readSession(page);
}

/** What the account token says — role and persona as the server derived them. */
export async function readSession(page) {
	return page.evaluate(() => {
		try {
			return JSON.parse(localStorage.getItem("aspire.session.v1") || "null");
		} catch {
			return null;
		}
	});
}
