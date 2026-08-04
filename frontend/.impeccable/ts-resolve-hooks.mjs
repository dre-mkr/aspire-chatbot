/**
 * The resolve hook itself. See `ts-resolve.mjs`.
 *
 * Review-only. Never built or shipped.
 */
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export async function resolve(specifier, context, next) {
	if (specifier.startsWith(".") || specifier.startsWith("#/")) {
		const base = specifier.startsWith("#/")
			? new URL(`../src/${specifier.slice(2)}`, import.meta.url)
			: new URL(specifier, context.parentURL);
		for (const ext of ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]) {
			const candidate = new URL(base.href + ext);
			if (ext && existsSync(fileURLToPath(candidate))) {
				return { url: candidate.href, shortCircuit: true, format: "module-typescript" };
			}
		}
	}
	return next(specifier, context);
}
