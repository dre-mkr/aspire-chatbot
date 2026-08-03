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

const DEVICE = "x-aspire-device";

/** Matches the client's own truncation, and the service's. */
function provisionalTitle(question) {
	const clean = question.trim().replace(/\s+/g, " ");
	if (!clean) return "";
	return clean.length > 60 ? `${clean.slice(0, 59)}…` : clean;
}

export function createConversationStore() {
	/** id → { ownerKey, title, titleSource, updatedAt, messages[] } */
	const rows = new Map();

	const owner = (request) => request.headers()[DEVICE] ?? null;

	return {
		rows,

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
		async handle(request, respond) {
			const url = new URL(request.url());
			if (!url.pathname.startsWith("/api/conversations")) return false;

			const who = owner(request);
			if (!who) {
				respond(401, { detail: "No device identity was supplied." });
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
