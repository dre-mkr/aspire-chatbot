/**
 * A deployed backend, which nobody here owns.
 *
 * `Backend` in server.mjs spawns the service so it can attribute stdout to a
 * single turn. Against a deployed origin there is no stdout to attribute, so
 * this stands in its place with the same shape and an empty log.
 *
 * The empty log is the whole point of `remote`. Without that flag every `log`
 * expectation would read as "no line matched" and every suite would fail for a
 * reason that says nothing about the deployed service. `suite.mjs` reads it and
 * records those assertions as SKIPPED instead, so a remote run reports what it
 * actually checked -- the wire and the DOM -- rather than pretending to a third
 * source it cannot see.
 */

export class RemoteBackend {
	/** Marks every log-derived assertion as unverifiable. See `judge` in suite.mjs. */
	remote = true;

	/** Always empty: nothing here reads the deployed service's stdout. */
	lines = [];

	constructor({ baseUrl }) {
		this.baseUrl = baseUrl.replace(/\/$/, "");
	}

	/**
	 * The deployed equivalent of waiting for the "ready" line: ask the service.
	 *
	 * `/health` and `/ready` are NOT usable here. nginx proxies only `/api/` and
	 * `/v2/` to the backend (deploy/nginx-aspire.conf), so every other path --
	 * including both health endpoints -- falls through to the SPA and answers
	 * 404 with HTML. There is no public health check on this deployment.
	 *
	 * So: GET a POST-only route. FastAPI answers 405 as JSON, which proves the
	 * backend is up and routed, costs nothing and changes nothing. HTML back
	 * means the request reached the frontend instead, i.e. the API is down.
	 *
	 * A judge arriving on a cold box is what this guards: without it, a sleeping
	 * service fails every suite for a reason none of them are about.
	 */
	async start({ attempts = 10, waitMs = 3000 } = {}) {
		let last = null;
		for (let attempt = 0; attempt < attempts; attempt++) {
			try {
				const response = await fetch(`${this.baseUrl}/v2/session`, { signal: AbortSignal.timeout(15_000) });
				if ((response.headers.get("content-type") || "").includes("json")) return;
				last = `status ${response.status} answered ${response.headers.get("content-type")} — that is the SPA, not the API`;
			} catch (error) {
				last = error.message;
			}
			await new Promise((resolve) => setTimeout(resolve, waitMs));
		}
		throw new Error(`${this.baseUrl} did not answer as an API (${last}). The deployment may be down or still waking.`);
	}

	cursor() {
		return 0;
	}

	since() {
		return [];
	}

	/** Nothing to flush. Kept so `observe()` does not have to know which backend it has. */
	async settleLog() {}

	/** Not ours to stop. */
	async stop() {}
}
