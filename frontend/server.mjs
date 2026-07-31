/**
 * Production entry for the SSR build.
 *
 * `vite build` emits `dist/server/server.js`, which exports a Web-standard
 * `{ fetch(Request): Response }` handler — deliberately not a listening server,
 * so the same build runs on Node, Bun, Deno or an edge runtime. This file is the
 * Node half: srvx binds the handler to a port.
 *
 * Static assets are NOT served here. `dist/client/` is served by nginx, which
 * does it faster and can set immutable cache headers on the hashed filenames.
 * Anything nginx does not find as a file is proxied here and rendered.
 *
 *   HOST  interface to bind (default 127.0.0.1 — nginx is in front, so there is
 *         no reason to listen on a public interface)
 *   PORT  port to bind (default 3000)
 */

import { serve } from "srvx";
import handler from "./dist/server/server.js";

const port = Number(process.env.PORT ?? 3000);
const hostname = process.env.HOST ?? "127.0.0.1";

serve({
	port,
	hostname,
	fetch: (request) => handler.fetch(request),
});

console.log(`ASPIRE frontend listening on http://${hostname}:${port}`);
