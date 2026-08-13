/**
 * The backend under test, owned by the harness.
 *
 * The harness starts it rather than attaching to a running one for two reasons:
 * the log is the only channel that says WHY a turn routed where it did, and it must
 * be sliceable per turn; and the run needs its own cache namespace and limits.
 *
 * `python -m app.serve`, never uvicorn: on Windows uvicorn picks its own event loop
 * and the Postgres checkpointer silently returns None, which turns every multi-turn
 * test into a single-turn test that still passes its first assertion.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const READY_TIMEOUT = 120_000;

export class Backend {
	constructor({ repoRoot, port = 8010, logPath, env = {} }) {
		this.repoRoot = repoRoot;
		this.port = port;
		this.logPath = logPath;
		this.env = env;
		this.lines = [];
		this.child = null;
		this.stream = null;
	}

	get baseUrl() {
		return `http://127.0.0.1:${this.port}`;
	}

	async alreadyRunning() {
		try {
			const response = await fetch(`${this.baseUrl}/ready`, {
				signal: AbortSignal.timeout(3000),
			});
			return response.status < 500 || response.status === 503;
		} catch {
			return false;
		}
	}

	async start() {
		if (await this.alreadyRunning()) {
			throw new Error(
				`something is already serving ${this.baseUrl}. The harness must own the ` +
					`backend so it can slice the log per turn — stop it and re-run.`,
			);
		}

		fs.mkdirSync(path.dirname(this.logPath), { recursive: true });
		this.stream = fs.createWriteStream(this.logPath, { flags: "a" });

		const backend = path.join(this.repoRoot, "backend");
		this.child = spawn(
			path.join(backend, ".venv", "Scripts", "python.exe"),
			["-m", "app.serve", "--host", "127.0.0.1", "--port", String(this.port)],
			{
				cwd: backend,
				env: {
					...process.env,
					// Without this, Python buffers and the log arrives after the turn it explains.
					PYTHONUNBUFFERED: "1",
					LOG_LEVEL: "INFO",
					...this.env,
				},
				windowsHide: true,
			},
		);

		const absorb = (chunk) => {
			const text = chunk.toString();
			this.stream.write(text);
			for (const line of text.split(/\r?\n/)) {
				if (line.trim()) this.lines.push(line);
			}
		};
		this.child.stdout.on("data", absorb);
		this.child.stderr.on("data", absorb);

		this.child.on("exit", (code) => {
			this.exited = code;
		});

		await this.waitReady();
		return this;
	}

	async waitReady() {
		const deadline = Date.now() + READY_TIMEOUT;
		for (;;) {
			if (this.exited !== undefined) {
				throw new Error(
					`backend exited with ${this.exited}. Last lines:\n` +
						this.lines.slice(-25).join("\n"),
				);
			}
			try {
				const response = await fetch(`${this.baseUrl}/ready`, {
					signal: AbortSignal.timeout(5000),
				});
				if (response.ok) return JSON.parse(await response.text());
			} catch {}
			if (Date.now() > deadline) {
				throw new Error(
					`backend never became ready. Last lines:\n${this.lines.slice(-25).join("\n")}`,
				);
			}
			await new Promise((resolve) => setTimeout(resolve, 500));
		}
	}

	/** Where the log is now; pair with `since()` to attribute lines to one turn. */
	cursor() {
		return this.lines.length;
	}

	since(cursor) {
		return this.lines.slice(cursor);
	}

	/** Give the logger a moment to flush before slicing. */
	async settleLog(ms = 350) {
		await new Promise((resolve) => setTimeout(resolve, ms));
	}

	async stop() {
		if (!this.child || this.exited !== undefined) return;
		this.child.kill();
		await new Promise((resolve) => setTimeout(resolve, 400));
		if (this.exited === undefined) this.child.kill("SIGKILL");
		if (this.stream) this.stream.end();
	}
}

/** The lines that say why a turn went where it did. */
export const SIGNALS = {
	route: /^.*\broute session=(\S+) agent=(\S+) confidence=([0-9.]+) sticky=(\w+) coerced=(\w+) active=(\S+) reason=(.*)$/,
	turn: /\bturn session=(\S+) agent=(\S+) directives=(\d+) chips=(\d+)/,
	sticky: /Staying in (\S+) for session (\S+): (\S+) proposed at ([0-9.]+), below the ([0-9.]+)/,
	escaped: /Classifier escaped the allowed list/,
	coerced: /Classifier proposed .* which is not in/,
	classifierDown: /Classifier call failed for session/,
	learnTurn: /learn_turn concept_id=(\S+)/,
	placement: /placement session=(\S+) -> (\S+)/,
	cardOpened: /(eligibility|game|signup) card opened/,
	escalatingWithoutRouter: /Escalating as (\S+) without the router/,
	ticket: /escalation ticket=(\S+) priority=(\S+) category=(\S+)/,
	qaHandoff: /QA handing a lesson request to (\S+)/,
	stub: /Stub agent (\S+) handled a turn/,
	cacheHit: /cache hit session=/,
	collected: /\[collected: (\S+)\]/,
	skipped: /\[skipped: (\S+)\]/,
};

/** Parse the one line that records a routing decision. */
export function readRoute(lines) {
	for (const line of lines) {
		const match = line.match(SIGNALS.route);
		if (match) {
			return {
				session: match[1],
				agent: match[2],
				confidence: Number(match[3]),
				sticky: match[4] === "True",
				coerced: match[5] === "True",
				active: match[6] === "None" ? null : match[6],
				reason: match[7],
			};
		}
	}
	return null;
}

export function readSticky(lines) {
	for (const line of lines) {
		const match = line.match(SIGNALS.sticky);
		if (match) {
			return {
				kept: match[1],
				proposed: match[3],
				confidence: Number(match[4]),
				threshold: Number(match[5]),
			};
		}
	}
	return null;
}

export function has(lines, signal) {
	return lines.some((line) => signal.test(line));
}
