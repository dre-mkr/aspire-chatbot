import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { devtools } from "@tanstack/devtools-vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact, { reactCompilerPreset } from "@vitejs/plugin-react";
import { createRunnableDevEnvironment, defineConfig } from "vite";

const config = defineConfig(({ command }) => {
	// A production build without VITE_ASPIRE_API_URL silently emits a bundle that
	// calls http://localhost:8000 -- it builds clean, deploys clean, and every
	// request fails in the browser. deploy/update.sh sets it; nothing made
	// forgetting it loud.
	//
	// Gated on `command === "build"` rather than on NODE_ENV. `vite preview` also
	// runs with NODE_ENV=production and only serves an existing bundle, so a
	// NODE_ENV check refused to start the preview server -- which is how this
	// guard broke the very harness used to verify the rest of this work.
	if (command === "build" && !process.env.VITE_ASPIRE_API_URL) {
		throw new Error(
			"VITE_ASPIRE_API_URL is not set. A production build without it points the " +
				"client at http://localhost:8000 and fails for every user. Build with " +
				'VITE_ASPIRE_API_URL="https://your.host" (see deploy/update.sh).',
		);
	}

	return {
	resolve: { tsconfigPaths: true },
	// Vite 8 no longer gives the `ssr` environment a runnable dev environment by
	// default, and TanStack Start needs one: its dev middleware runs the server
	// entry in-process. Without this `vite dev` starts cleanly, logs nothing, and
	// answers every route with a bare 404 — the plugin quietly declines to install
	// its SSR handler when the environment is not runnable. `vite build` is
	// unaffected, which is why the production bundle was fine throughout and only
	// development was broken.
	environments: {
		ssr: {
			dev: {
				createEnvironment: (name, config) => createRunnableDevEnvironment(name, config),
			},
		},
	},
	// @tanstack/react-store reaches into use-sync-external-store with a named
	// import, but that shim is CJS. If the optimizer prebundles react-store and
	// leaves the shim raw, the browser gets `module.exports = require(...)` and
	// the named import throws at parse time — which kills hydration for the whole
	// app, not just the store. Prebundle the shim so it arrives as real ESM.
	//
	// @tanstack/react-router-ssr-query is reached only from src/router.tsx, which
	// the scanner does not walk — Start supplies the client entry virtually — so
	// the optimizer discovers it one pass late, after react-query has already been
	// bundled. A late discovery is not folded into the existing chunk: rolldown
	// inlines its own copy of react-query into the ssr-query bundle. That gives
	// two QueryClientContext objects, and since the provider comes from
	// ssr-query's copy while every useQueryClient call comes from the app's, every
	// consumer throws "No QueryClient set". Naming it here puts it in the first
	// pass, where it shares the one react-query chunk.
	optimizeDeps: {
		include: [
			"use-sync-external-store/shim/with-selector",
			"@tanstack/react-query",
			"@tanstack/react-router-ssr-query",
		],
	},
	plugins: [
		devtools(),
		tailwindcss(),
		// Asked for explicitly so that failing to install it is loud.
		//
		// Left to itself, Start decides whether to install its SSR middleware and
		// silently declines if the environment does not suit it — which is how a
		// dev server that starts cleanly, logs nothing and answers every route
		// with a bare 404 came about. Demanded rather than inferred, the same
		// situation raises "the SSR environment is not a RunnableDevEnvironment",
		// which says what is wrong and where to fix it.
		tanstackStart({ vite: { installDevServerMiddleware: true } }),
		viteReact(),
		babel({ presets: [reactCompilerPreset()] }),
	],
	};
});

export default config;
