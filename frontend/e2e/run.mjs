#!/usr/bin/env node
/**
 * Drive every ASPIRE agent through the real website, one conversation at a time.
 *
 *   node e2e/run.mjs --preflight
 *   node e2e/run.mjs --suite all
 *   node e2e/run.mjs --suite routing_one_chat --headed
 *   node e2e/run.mjs --suite judging --against https://aspire.eccugenai.app
 *
 * The frontend must already be serving on --web (start it from .claude/launch.json).
 * The backend is started here, because the harness needs to slice its log per turn.
 *
 * `--against <origin>` runs the same suites over a DEPLOYED origin instead: the
 * site and the API are both taken from there, nothing is spawned, and the log
 * slice is unavailable, so `log`/`route` expectations are reported as SKIPPED
 * rather than failed. Two sources instead of three -- which is what the judges
 * will see, and the only way to test the thing that is actually shipped.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { launch, newIdentityContext, newPage } from "./lib/browser.mjs";
import { IDENTITIES, withCredentials } from "./lib/identities.mjs";
import { RemoteBackend } from "./lib/remote.mjs";
import { summarise, writeSuite, writeSummary } from "./lib/report.mjs";
import { Backend } from "./lib/server.mjs";
import { anonymous, signUp } from "./lib/signup.mjs";
import { runSteps } from "./lib/suite.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");

/** Order matters: the safeguarding trigger writes a real ticket, so it runs last. */
export const SUITES = [
	"nova_control",
	"qa_agent",
	"qa_agent_limited",
	"qa_agent_public",
	"learn_curriculum",
	"learn_tutor",
	"learning_sample",
	"learning_preview",
	"register_agent",
	"register_agent_step1",
	"cards_games",
	"cards_eligibility",
	"routing_one_chat",
	"escalate_adult",
	"escalate_child",
];

function parseArgs(argv) {
	const args = { suite: null, headed: false, slowMo: 0, preflight: false, web: "http://localhost:3000", port: 8010, against: null };
	for (let i = 0; i < argv.length; i++) {
		const flag = argv[i];
		if (flag === "--preflight") args.preflight = true;
		else if (flag === "--headed") args.headed = true;
		else if (flag === "--suite") args.suite = argv[++i];
		else if (flag === "--slowmo") args.slowMo = Number(argv[++i]);
		else if (flag === "--web") args.web = argv[++i];
		else if (flag === "--port") args.port = Number(argv[++i]);
		else if (flag === "--run-id") args.runId = argv[++i];
		else if (flag === "--against") args.against = argv[++i];
	}
	// A deployed origin serves the site and the API from one host, so it is both.
	// Set after the loop so flag order does not matter.
	if (args.against) args.web = args.against.replace(/\/$/, "");
	return args;
}

async function checkWeb(url) {
	try {
		const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
		if (!response.ok) throw new Error(`status ${response.status}`);
	} catch (error) {
		throw new Error(
			`the site is not serving at ${url} (${error.message}). Start the "frontend" ` +
				`launch config first — it points VITE_ASPIRE_API_URL at the backend.`,
		);
	}
}

/**
 * Is the site actually talking to the backend this run owns?
 *
 * Nothing connects the two. The harness spawns a backend on --port, but the
 * site's API base is baked into its bundle from VITE_ASPIRE_API_URL and falls
 * back to `http://localhost:8000` when that is unset (src/lib/config.ts). Point
 * the harness at a dev server someone else started and the run is green, the
 * log slice is empty, and every result came from a service nobody is testing --
 * which is exactly what happened the first time this ran.
 *
 * Read after the first page load, off the browser's own resource timings, so it
 * reports where the requests really went rather than where they should have.
 */
async function checkWiring(page, args) {
	const calls = await page.evaluate(() =>
		performance
			.getEntriesByType("resource")
			.map((entry) => entry.name)
			.filter((name) => /\/(api|v2)\//.test(name)),
	);
	if (!calls.length) return;

	const hosts = [...new Set(calls.map((name) => {
		try {
			return new URL(name).host;
		} catch {
			return name;
		}
	}))];

	// Locally the site says `localhost` and the backend binds 127.0.0.1, so the
	// port is the only part worth comparing. A deployed run shares one origin.
	const want = args.against ? new URL(args.against).host : String(args.port);
	const ok = hosts.some((host) => (args.against ? host === want : host.endsWith(`:${want}`)));
	if (ok) return;

	throw new Error(
		`the site at ${args.web} is calling ${hosts.join(", ")}, not ${args.against || `port ${args.port}`}.\n` +
			`Nothing this run measures would come from the backend it started. Start the ` +
			`"frontend-e2e" launch config (port 3001, VITE_ASPIRE_API_URL=http://localhost:8010) ` +
			`and pass --web http://localhost:3001.`,
	);
}

/** Everything that must be true before a run means anything. */
function preflight(backend) {
	const problems = [];
	const notes = [];
	const log = backend.lines.join("\n");

	const concepts = log.match(/Concepts loaded: (\d+) servable of (\d+), (\d+) with embeddings/);
	if (!concepts) {
		problems.push("no 'Concepts loaded' line — the concept store never initialised");
	} else {
		const [, servable, total, embedded] = concepts.map(Number);
		notes.push(`concepts: ${servable} servable of ${total}, ${embedded} with embeddings`);
		if (!servable) {
			problems.push(
				"0 servable concepts: the tutor branch never runs, so the routing test would " +
					"silently measure a different system. Seed with backend/tests/scripts/seed_concepts.py",
			);
		} else if (!embedded) {
			problems.push("0 concepts with embeddings: the tutor resolves nothing and always declines");
		}
	}

	if (/there is no \w+ key; routing will use CHAT_MODEL/.test(log)) {
		problems.push("the classifier model is unreachable and routing silently fell back to CHAT_MODEL");
	}
	if (/Could not register app\.agents/.test(log)) {
		problems.push("an agent module failed to import and is serving a stub");
	}
	if (/each turn starts from a fresh state and nothing resumes/.test(log)) {
		problems.push("NO CHECKPOINTER: every turn starts fresh, so multi-turn tests are meaningless");
	}

	return { problems, notes };
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const runId = args.runId || new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
	const root = path.join(HERE, "artifacts", runId);
	fs.mkdirSync(root, { recursive: true });

	console.log(`run ${runId} -> ${path.relative(REPO, root)}`);

	await checkWeb(args.web);

	// A deployed run takes the service as it is: no spawning, and none of the env
	// below. That is the point of it -- the caches, the rate limits and the voice
	// flag are whatever production has, which is what a judge will meet.
	const backend = args.against
		? new RemoteBackend({ baseUrl: args.against })
		: new Backend({
				repoRoot: REPO,
				port: args.port,
				logPath: path.join(root, "backend.log"),
				env: {
					ASPIRE_CACHE_NAMESPACE: `e2e-${runId}`,
					// A layer-1 hit reports agent "cache" and never runs the graph, which would
					// turn a routing failure into a pass. Off for the whole run.
					RESPONSE_CACHE_ENABLED: "false",
					SEMANTIC_CACHE_ENABLED: "false",
					// No Valkey on this machine: left set, every turn pays several connect
					// timeouts and buries the log in tracebacks. It fails open either way.
					VALKEY_URL: "",
					CHAT_MESSAGES_PER_WINDOW: "1000",
					ANONYMOUS_SESSIONS_PER_IP_PER_HOUR: "1000",
					VOICE_ENABLED: "false",
				},
			});

	console.log(args.against ? `waiting for ${args.against} to answer...` : "starting the backend...");
	await backend.start();
	console.log(`backend ready on ${backend.baseUrl}`);

	// Preflight reads the startup log, so a deployed run cannot run it. `/ready`
	// answering is the whole of the check there, and `start()` has just done it.
	const checks = args.against
		? { problems: [], notes: ["deployed run: startup preflight skipped, /ready answered"] }
		: preflight(backend);
	for (const note of checks.notes) console.log(`  ${note}`);
	fs.writeFileSync(path.join(root, "preflight.json"), JSON.stringify(checks, null, 2));

	if (checks.problems.length) {
		console.error("\npreflight failed:");
		for (const problem of checks.problems) console.error(`  - ${problem}`);
		await backend.stop();
		process.exit(2);
	}
	console.log("preflight: clear");

	if (args.preflight) {
		await backend.stop();
		return;
	}

	const browser = await launch({ headed: args.headed, slowMo: args.slowMo });
	const contexts = new Map();
	const accounts = {};

	async function identityContext(key) {
		if (contexts.has(key)) return contexts.get(key);

		const identity = withCredentials(IDENTITIES[key], runId);
		const context = await newIdentityContext(browser);
		const page = await newPage(context);

		const session = identity.anonymous
			? await anonymous(page, args.web)
			: await signUp(page, args.web, identity);

		// First half of the echo check. The account's persona is derived from the DOB
		// server-side, so a typo shows up here. The band only reaches the client when a
		// graph session is minted, which happens on the first turn — checked below.
		const want = identity.expect;
		if (!identity.anonymous && session?.persona !== want.persona) {
			throw new Error(
				`identity ${key} registered as persona ${session?.persona}, wanted ` +
					`${want.persona} — every assertion downstream would be meaningless`,
			);
		}

		accounts[key] = { email: identity.email || null, ...want, routable: identity.routable };
		await page.close();

		const entry = { context, identity, session };
		contexts.set(key, entry);
		console.log(`  identity ${key}: ${identity.label} (${want.persona}/${want.age_band})`);
		return entry;
	}

	const names = args.suite && args.suite !== "all" ? args.suite.split(",") : SUITES;
	const results = [];
	let wiringChecked = false;

	try {
		for (const name of names) {
			const module = await import(`./scripts/${name}.mjs`);
			const suite = module.suite;
			console.log(`\n=== ${suite.name} (identity ${suite.identity}) ===`);

			const { context } = await identityContext(suite.identity);
			const console_ = [];
			const errors = [];
			const page = await newPage(context, {
				onConsole: (entry) => console_.push(entry),
				onPageError: (error) => errors.push(error),
			});
			await page.goto(args.web, { waitUntil: "networkidle2" });
			await page.waitForSelector("#aspire-composer", { visible: true });
			// Once is enough: the bundle's API base cannot change mid-run.
			if (!wiringChecked) {
				await checkWiring(page, args);
				wiringChecked = true;
			}

			const dir = path.join(root, suite.name);
			const ctx = {
				page,
				backend,
				baseUrl: args.web,
				dir,
				onStep: (record) => {
					const mark = record.pass ? "ok  " : "FAIL";
					const agent = record.wire?.usage?.agent ?? "—";
					console.log(`  ${mark} ${record.n}. [${agent}] ${String(record.label).slice(0, 62)}`);
					for (const reason of record.pass ? [] : record.reasons) console.log(`       ${reason}`);
				},
			};

			let records;
			try {
				records = await runSteps(ctx, await module.steps(ctx));
			} catch (error) {
				records = [{ n: 0, label: "(suite crashed)", pass: false, reasons: [String(error.message || error)] }];
			}

			if (module.report) await module.report(ctx, records);

			// Second half of the echo check: the band the graph session was actually minted
			// with. A wrong band silently changes which agents are reachable at all.
			const mint = (await page.evaluate(() => window.__aspire_aux || []))
				.filter((call) => call.url.includes("/v2/session"))
				.pop();
			const minted = mint?.response || {};
			const want = IDENTITIES[suite.identity].expect;
			if (minted.persona !== want.persona || minted.age_band !== want.age_band) {
				records.unshift({
					n: 0,
					label: "identity echo",
					pass: false,
					reasons: [
						`graph session minted as ${minted.persona}/${minted.age_band}, wanted ` +
							`${want.persona}/${want.age_band}`,
					],
				});
			}

			fs.mkdirSync(dir, { recursive: true });
			fs.writeFileSync(path.join(dir, "console.log"), console_.map((e) => `${e.type}: ${e.text}`).join("\n"));
			if (errors.length) fs.writeFileSync(path.join(dir, "pageerrors.log"), errors.join("\n"));
			writeSuite(dir, suite, records, { pageErrors: errors });

			const summary = summarise(suite, records);
			// The persona picker hydrates with a different title and label than the server
			// rendered, on every page load. Real, pre-existing, and nothing to do with
			// routing — recorded once rather than failing all fourteen suites.
			const real = errors.filter((error) => !/Hydration failed|hydrat/i.test(error));
			summary.hydrationMismatch = errors.length > real.length;
			if (real.length) {
				summary.failed += 1;
				summary.failures.push({ n: 0, label: "page error", reasons: real });
			}
			results.push(summary);
			await page.close();
		}
	} finally {
		fs.writeFileSync(path.join(root, "identities.json"), JSON.stringify(accounts, null, 2));

		// Run-wide negatives: an unbuilt agent must never answer anybody. Both are
		// read off the log, so a deployed run cannot assert them either way --
		// silence here would read as a pass, so say nothing rather than imply one.
		const log = backend.lines.join("\n");
		const runWide = [];
		if (!args.against) {
			if (/Stub agent (\S+) handled a turn/.test(log)) runWide.push("a stub agent handled a turn");
			if (/active_agent.?.?servicing_agent/.test(log)) runWide.push("servicing_agent appeared");
		}
		if (runWide.length) results.push({ suite: "(run-wide)", identity: "-", total: runWide.length, passed: 0, failed: runWide.length, failures: runWide.map((reason) => ({ n: 0, label: "run-wide", reasons: [reason] })) });

		console.log(`\n${writeSummary(root, results)}`);
		await browser.close().catch(() => {});
		await backend.stop();
	}

	process.exit(results.some((result) => result.failed) ? 1 : 0);
}

main().catch(async (error) => {
	console.error(`\n${error.stack || error}`);
	process.exit(3);
});
