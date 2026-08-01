/**
 * Review-only preview server.
 *
 * Production `server.mjs` deliberately does not serve `dist/client` -- nginx
 * does that in front of it. For the design review we need one origin that
 * answers both, so the detector and the probes see the real production page
 * with its real CSS rather than an unstyled SSR shell.
 *
 * The dev server is not usable for this: the detector's URL scan waits for
 * `networkidle0`, which never settles against Vite, and dev renders
 * <TanStackDevtools> into the page.
 *
 * Not part of the app. Never built or shipped.
 */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const clientDir = join(root, "dist", "client");
const handler = (await import(new URL("../dist/server/server.js", import.meta.url).href)).default;

const PORT = Number(process.env.PORT ?? 4173);

const TYPES = {
	".js": "text/javascript",
	".css": "text/css",
	".png": "image/png",
	".jpg": "image/jpeg",
	".svg": "image/svg+xml",
	".ico": "image/x-icon",
	".json": "application/json",
	".webmanifest": "application/manifest+json",
	".woff2": "font/woff2",
};

async function serveStatic(pathname) {
	// normalize() collapses any ../ before it can escape dist/client.
	const rel = normalize(decodeURIComponent(pathname)).replace(/^([/\\])+/, "");
	const file = join(clientDir, rel);
	if (!file.startsWith(clientDir)) return null;
	try {
		if (!(await stat(file)).isFile()) return null;
	} catch {
		return null;
	}
	return {
		body: await readFile(file),
		type: TYPES[extname(file)] ?? "application/octet-stream",
	};
}

createServer(async (req, res) => {
	const url = new URL(req.url, `http://localhost:${PORT}`);

	const asset = await serveStatic(url.pathname);
	if (asset) {
		res.writeHead(200, { "content-type": asset.type });
		res.end(asset.body);
		return;
	}

	const response = await handler.fetch(
		new Request(url, { method: req.method, headers: req.headers }),
	);
	res.writeHead(response.status, Object.fromEntries(response.headers));
	res.end(Buffer.from(await response.arrayBuffer()));
}).listen(PORT, () => {
	console.log(`preview on http://localhost:${PORT}`);
});
