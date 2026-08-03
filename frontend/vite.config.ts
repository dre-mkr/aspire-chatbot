import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { devtools } from "@tanstack/devtools-vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact, { reactCompilerPreset } from "@vitejs/plugin-react";
import { createRunnableDevEnvironment, defineConfig } from "vite";

const config = defineConfig({
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
	optimizeDeps: {
		include: ["use-sync-external-store/shim/with-selector"],
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
});

export default config;
