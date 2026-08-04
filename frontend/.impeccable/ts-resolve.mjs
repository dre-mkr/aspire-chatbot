/**
 * Lets Node import the app's own `.ts` modules by their extensionless specifier.
 *
 * Node strips types natively but will not guess an extension, and the app writes
 * `./knowledge` rather than `./knowledge.ts`. This adds only that: try `.ts`,
 * then `.tsx`, before letting the default resolver fail as it normally would.
 *
 *   node --import ./.impeccable/ts-resolve.mjs .impeccable/whatever.mjs
 *
 * Review-only. Never built or shipped.
 */
import { register } from "node:module";
import { pathToFileURL } from "node:url";

if (!process.env.__ASPIRE_TS_RESOLVE) {
	process.env.__ASPIRE_TS_RESOLVE = "1";
	register("./ts-resolve-hooks.mjs", pathToFileURL(`${import.meta.dirname}/`));
}
