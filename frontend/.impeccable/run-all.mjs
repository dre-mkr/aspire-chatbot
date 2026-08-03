/**
 * Every regression suite in .impeccable, in one command.
 *
 *   node .impeccable/run-all.mjs            # build, serve, run everything
 *   node .impeccable/run-all.mjs --no-build # against whatever is already built
 *   node .impeccable/run-all.mjs auth       # only suites matching "auth"
 *
 * There was no runner before this, which meant "the suite is green" was a claim
 * assembled by hand from however many scripts somebody remembered to run, and
 * the ones nobody remembered were quietly not being run at all.
 *
 * It also owns the preview server, because getting that wrong looks exactly
 * like the product being broken: the server reads dist/client/index.html once,
 * so after a rebuild it serves markup pointing at bundle hashes that no longer
 * exist. Every asset 404s, the app never hydrates, and every suite fails on a
 * page with no JavaScript. Rebuilding and restarting are therefore one step
 * here rather than two things to remember in the right order.
 *
 * Suites are the scripts that exit non-zero when they fail. The rest of the
 * directory is one-off diagnostics — screenshotters and probes kept because
 * they were useful once — and they are deliberately not run.
 *
 * Review-only. Never built or shipped.
 */
import { spawn, spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const PORT = 4173;
const BASE = `http://localhost:${PORT}`;

const args = process.argv.slice(2);
const build = !args.includes("--no-build");
const filter = args.find((a) => !a.startsWith("--"));

/** A suite is a harness that fails the process when it fails an assertion. */
const suites = readdirSync(HERE)
	.filter((f) => f.endsWith(".mjs"))
	.map((f) => f.replace(/\.mjs$/, ""))
	.filter((name) => name !== "run-all" && name !== "preview-server")
	.filter((name) => /process\.exit(Code)?\(/.test(readFileSync(join(HERE, `${name}.mjs`), "utf8")))
	.filter((name) => !filter || name.includes(filter))
	.sort();

const run = (command, cmdArgs, options = {}) =>
	spawnSync(command, cmdArgs, { cwd: ROOT, encoding: "utf8", shell: true, ...options });

function freePort() {
	// Windows holds the port until the owning process is gone, and a failed
	// restart is silent — the old server keeps answering, with the old HTML.
	const found = run("powershell", [
		"-NoProfile",
		"-Command",
		`"Get-NetTCPConnection -LocalPort ${PORT} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"`,
	]);
	for (const pid of (found.stdout ?? "").split(/\s+/).filter(Boolean)) {
		run("powershell", ["-NoProfile", "-Command", `"Stop-Process -Id ${pid} -Force"`]);
	}
}

async function waitForServer(timeoutMs = 30000) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			const response = await fetch(BASE, { signal: AbortSignal.timeout(2000) });
			if (response.ok) return true;
		} catch {
			// Not up yet.
		}
		await new Promise((r) => setTimeout(r, 400));
	}
	return false;
}

if (build) {
	process.stdout.write("building… ");
	const built = run("npm", ["run", "build"]);
	if (built.status !== 0) {
		console.log("FAILED\n");
		console.log(built.stdout ?? "", built.stderr ?? "");
		process.exit(1);
	}
	console.log("ok");
}

freePort();
const server = spawn("node", [join(HERE, "preview-server.mjs")], {
	cwd: ROOT,
	stdio: "ignore",
	detached: false,
});
if (!(await waitForServer())) {
	console.log(`preview server never answered on ${BASE}`);
	server.kill();
	process.exit(1);
}

console.log(`\nrunning ${suites.length} suites against ${BASE}\n`);

const results = [];
for (const name of suites) {
	const started = Date.now();
	process.stdout.write(`  ${name.padEnd(20)} `);
	const out = run("node", [join(HERE, `${name}.mjs`)], { timeout: 15 * 60 * 1000 });
	const seconds = Math.round((Date.now() - started) / 1000);
	const text = `${out.stdout ?? ""}${out.stderr ?? ""}`;
	// A suite that crashed printed no verdict; say so rather than calling it a
	// failed assertion, which sends whoever reads this looking in the wrong place.
	// Suites do not all announce themselves the same way — "3 FAIL", "8 CHECK(S)
	// FAILED", "All green". Anything matching none of them exited without
	// reaching its own verdict, which is a different problem from a failed
	// assertion and sends whoever reads this to a different place.
	const crashed =
		out.status !== 0 && !/\d+ FAIL|\d+ CHECK\(S\) FAILED|ALL PASS|All green/i.test(text);
	const failures = [...text.matchAll(/^\s*FAIL\s+(.*)$/gm)].map((m) => m[1].trim());
	results.push({ name, ok: out.status === 0, crashed, seconds, failures, text });
	console.log(`${out.status === 0 ? "PASS" : crashed ? "CRASH" : "FAIL"}  ${seconds}s`);
}

server.kill();
freePort();

const failed = results.filter((r) => !r.ok);
console.log(`\n${"─".repeat(62)}`);
if (failed.length === 0) {
	console.log(`ALL ${results.length} SUITES PASS`);
} else {
	console.log(`${failed.length} of ${results.length} suites failing\n`);
	for (const suite of failed) {
		console.log(`  ${suite.name}${suite.crashed ? "  (crashed — see output)" : ""}`);
		for (const failure of suite.failures) console.log(`      ${failure}`);
		if (suite.crashed) {
			console.log(
				suite.text
					.split("\n")
					.filter((l) => l.trim())
					.slice(-6)
					.map((l) => `      ${l}`)
					.join("\n"),
			);
		}
	}
}
process.exit(failed.length === 0 ? 0 : 1);
