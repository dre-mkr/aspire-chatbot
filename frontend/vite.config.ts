import babel from "@rolldown/plugin-babel";
import tailwindcss from "@tailwindcss/vite";
import { devtools } from "@tanstack/devtools-vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const config = defineConfig({
	resolve: { tsconfigPaths: true },
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
		tanstackStart(),
		viteReact(),
		babel({ presets: [reactCompilerPreset()] }),
	],
});

export default config;
