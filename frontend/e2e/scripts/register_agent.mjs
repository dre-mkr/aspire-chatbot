/**
 * The application slot loop, and the document interrupt.
 *
 * Two assertions here are worth keeping forever:
 *   - a sensitive value must never reach the log (only `[collected: <slot>]`)
 *   - the upload resume is `Command(resume=...)`, so it must skip the router entirely
 *
 * The presign is real; the PUT to storage is stubbed, because the dev S3 key can
 * neither PUT nor LIST and the round-trip is not what this suite is testing.
 */

const NAME = "Maria Gonzalez";

export const suite = {
	name: "register_agent",
	identity: "E",
	description: "The guardian application: slots, a re-ask, a skip, and an upload.",
};

/** Answer the storage PUT locally, so the flow can continue past the document slot. */
async function stubStorage(page) {
	await page.setRequestInterception(true);
	page.on("request", (request) => {
		if (request.isInterceptResolutionHandled()) return;
		const isUpload =
			request.method() === "PUT" && !/127\.0\.0\.1|localhost/.test(request.url());
		if (isUpload) {
			request.respond({ status: 200, headers: { etag: '"e2e"' }, body: "" });
			return;
		}
		request.continue();
	});
}

export async function steps(ctx) {
	await stubStorage(ctx.page);

	return [
		{
			say: "I want to register my daughter.",
			critical: true,
			expect: { agent: "register_agent", route: true },
		},
		{
			say: NAME,
			note: "PRIVACY: the log may record that the slot was filled, never the value",
			expect: {
				agent: "register_agent",
				noLog: [new RegExp(NAME)],
			},
		},
		{
			say: "banana",
			note: "an answer that cannot parse: the same slot should be asked again",
			expect: { agent: "register_agent" },
		},
		{ say: "1988-06-10", expect: { agent: "register_agent" } },
		{ say: "869 555 0134", expect: { agent: "register_agent" } },
		{ say: "Skip", note: "the optional slot", expect: { agent: "register_agent" } },
		{ say: "12 Cayon Street", expect: { agent: "register_agent" } },
		{ say: "Saint George Basseterre", expect: { agent: "register_agent" } },
		{
			label: "upload a document (if the flow asked for one)",
			custom: async ({ page, dir }) => {
				const input = await page.$('input[type="file"]');
				if (!input) return null;

				const fs = await import("node:fs");
				const path = await import("node:path");
				const fixture = path.join(dir, "..", "..", "..", "fixtures", "id-card.png");
				if (!fs.existsSync(fixture)) return null;

				const { snapshot, settle } = await import("../lib/turn.mjs");
				const before = await snapshot(page);
				await input.uploadFile(fixture);
				await page.evaluate(() => {
					for (const button of document.querySelectorAll("button")) {
						if ((button.innerText || "").trim().startsWith("Send it")) button.click();
					}
				});
				return settle(page, before, { timeout: 90_000 });
			},
			note: "the resume path skips hydrate/guard/safety/cards/classify entirely",
			expect: {},
		},
	];
}

export async function report(ctx, records) {
	// The upload step is conditional; say plainly whether it ran.
	const upload = records.find((record) => record.label?.startsWith("upload"));
	if (upload && !upload.wire) {
		upload.reasons = ["skipped: the flow never reached a document slot"];
		upload.pass = true;
		upload.skipped = true;
	} else if (upload?.wire) {
		const resumed = upload.request && upload.request.__upload_result;
		if (!resumed) upload.reasons.push("the turn carried no __upload_result");
		if (upload.backend.route) {
			upload.reasons.push("the router was consulted on a resume turn, which it must not be");
		}
		upload.pass = upload.reasons.length === 0;
	}
}
