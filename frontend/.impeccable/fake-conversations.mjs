/**
 * An in-memory stand-in for the conversation service, per browser page.
 *
 * History moved out of localStorage and onto the server, which means every
 * harness that used to get history "for free" (the browser simply had it) now
 * needs something to talk to. A 404 would leave the rail permanently empty and
 * quietly turn a dozen assertions about the sidebar into assertions about
 * nothing.
 *
 * Stateful on purpose, and scoped to one page, because the interesting cases
 * are sequences: send a message and the row appears; send another and it moves;
 * rename it and the name sticks; reload and it is still there. A stub that
 * returns a fixed list cannot fail any of those.
 *
 * It also enforces ownership the way the real service does — a request with a
 * different device header sees nothing — so a harness cannot accidentally pass
 * because everything was visible to everyone.
 *
 * Review-only. Never built or shipped.
 */

/**
 * Authorisation is a bearer token now, never the device id.
 *
 * The header this used to read was the vulnerability: it is not a secret, so
 * anyone holding another person's could read their conversations. The stub
 * mirrors the real rule — a device id seeds a session and proves nothing.
 */
const AUTH = "authorization";

/** Matches the client's own truncation, and the service's. */
function provisionalTitle(question) {
	const clean = question.trim().replace(/\s+/g, " ");
	if (!clean) return "";
	return clean.length > 60 ? `${clean.slice(0, 59)}…` : clean;
}

export function createConversationStore() {
	/** id → { ownerKey, title, titleSource, updatedAt, messages[] } */
	const rows = new Map();

	/** Sessions this stub has issued: token -> user id. */
	const sessions = new Map();
	let nextUser = 0;

	const owner = (request) => {
		const header = request.headers()[AUTH] ?? "";
		const token = header.toLowerCase().startsWith("bearer ") ? header.slice(7).trim() : "";
		return sessions.get(token) ?? null;
	};

	return {
		rows,

		/** Who a request is, for harnesses recording turns. */
		ownerOf: (request) => owner(request),

		/**
		 * Creates the conversation and records the question, before answering.
		 *
		 * Mirrors `_open_conversation`: the question is stored whether or not a
		 * reply can be produced for it, which is what leaves a failed first send
		 * reopenable instead of vanishing from the rail.
		 */
		openConversation(threadId, ownerKey, question) {
			const existing = rows.get(threadId);
			if (existing) {
				existing.updatedAt = Date.now();
				existing.messages.push({ role: "user", text: question });
				return;
			}
			rows.set(threadId, {
				ownerKey,
				title: provisionalTitle(question),
				titleSource: null,
				updatedAt: Date.now(),
				messages: [{ role: "user", text: question }],
			});
		},

		/** Appends the answer, once there is one. */
		recordTurn(threadId, ownerKey, question, answer) {
			const row = rows.get(threadId);
			if (!row) return;
			row.updatedAt = Date.now();
			row.messages.push(answer);
		},

		/**
		 * Handles a conversations request, or returns false so the caller can
		 * carry on to its own routes.
		 */
		/** Issues a session. Always a NEW identity, exactly as the service does. */
		issueSession() {
			const token = `tok-${++nextUser}-${Math.random().toString(36).slice(2, 8)}`;
			const userId = `user-${nextUser}`;
			sessions.set(token, userId);
			return { token, user_id: userId, account_type: "anonymous", expires_in: 2592000 };
		},

		async handle(request, respond) {
			const url = new URL(request.url());

			// A brand-new anonymous identity, never a lookup by device id.
			if (url.pathname === "/api/auth/anonymous") {
				respond(200, this.issueSession());
				return true;
			}
			if (url.pathname === "/api/auth/session") {
				const who = owner(request);
				respond(200, who ? { token: "", user_id: who, account_type: "anonymous" } : null);
				return true;
			}

			if (!url.pathname.startsWith("/api/conversations")) return false;

			const who = owner(request);
			if (!who) {
				respond(401, { detail: "A valid session is required." });
				return true;
			}

			const mine = (id) => {
				const row = rows.get(id);
				return row && row.ownerKey === who ? row : null;
			};

			// POST /api/conversations/claim
			if (url.pathname.endsWith("/claim") && request.method() === "POST") {
				const { thread_ids = [] } = JSON.parse(request.postData() || "{}");
				let claimed = 0;
				for (const id of thread_ids) {
					const row = rows.get(id);
					// Only ever adopts a row nobody owns — the same rule the service
					// relies on to make replaying somebody else's ids worthless.
					if (row && row.ownerKey == null) {
						row.ownerKey = who;
						claimed += 1;
					}
				}
				respond(200, { claimed });
				return true;
			}

			// GET /api/conversations
			if (url.pathname === "/api/conversations" && request.method() === "GET") {
				const conversations = [...rows.entries()]
					.filter(([, row]) => row.ownerKey === who)
					.sort((a, b) => b[1].updatedAt - a[1].updatedAt)
					.map(([id, row]) => ({
						thread_id: id,
						title: row.title,
						title_source: row.titleSource,
						updated_at: row.updatedAt,
					}));
				respond(200, { conversations });
				return true;
			}

			const id = decodeURIComponent(url.pathname.split("/").pop());

			// PATCH /api/conversations/{id}
			if (request.method() === "PATCH") {
				const row = mine(id);
				if (!row) {
					respond(404, { detail: "No such conversation." });
					return true;
				}
				const body = JSON.parse(request.postData() || "{}");
				row.title = body.title;
				row.titleSource = body.title_source ?? null;
				respond(204, null);
				return true;
			}

			// GET /api/conversations/{id}
			const row = mine(id);
			if (!row) {
				// "Not yours" and "not there" are the same answer, as they are in
				// the service — otherwise the API is an oracle for real ids.
				respond(404, { detail: "No such conversation." });
				return true;
			}
			respond(200, {
				thread_id: id,
				title: row.title,
				title_source: row.titleSource,
				updated_at: row.updatedAt,
				messages: row.messages,
			});
			return true;
		},
	};
}

/**
 * A session, for suites that need one and are not testing auth.
 *
 * Every page asks for an anonymous session on first paint. A suite that lets
 * that through spends one of the thirty an address is allowed per hour — and a
 * full run is far more than thirty pages, so the product's own abuse control
 * starts refusing, and whichever suite is unlucky fails with a 429 that looks
 * like a regression and is not. Exactly the problem `backend/tests/conftest.py`
 * solves on the other side of the wire.
 *
 * Fixed token on purpose: these suites do not care who they are, only that they
 * are somebody.
 *
 *     if (serveAnonymousAuth(r, CORS)) return;
 */
export function serveAnonymousAuth(request, cors) {
	const path = new URL(request.url()).pathname;
	if (path !== "/api/auth/anonymous" && path !== "/api/auth/session") return false;
	request.respond({
		status: 200,
		contentType: "application/json",
		headers: cors,
		body: JSON.stringify({
			token: "harness-token",
			user_id: "harness-user",
			account_type: "anonymous",
			email: null,
			display_name: null,
			avatar_url: null,
			expires_in: 2592000,
		}),
	});
	return true;
}
