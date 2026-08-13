/** Where the FastAPI service lives. Override with VITE_ASPIRE_API_URL. */

/** Read defensively: `import.meta.env` is undefined outside the Vite bundle. */
function resolve(): string {
	const configured =
		typeof import.meta !== "undefined" && import.meta.env
			? import.meta.env.VITE_ASPIRE_API_URL
			: undefined;
	return (configured ?? "http://localhost:8000").replace(/\/$/, "");
}

export const API_URL = resolve();
