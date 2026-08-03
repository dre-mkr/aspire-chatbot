/**
 * Triage for the detector's low-contrast findings on the landing screen.
 *
 * DESIGN.md warns that a naive scan reports the layer behind a folded-away
 * subtree as a defect: on landing the rail is zero-width but present, and in
 * chat the hero is opacity:0 but present. Both keep real text in the DOM.
 *
 * So: find every text node whose colour matches a reported pair, and say
 * whether it is ACTUALLY VISIBLE — walking ancestors for inert, zero opacity,
 * zero size, visibility:hidden, or display:none. Anything visible is a real
 * accessibility defect and must be fixed, not ignored.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";
const browser = await puppeteer.launch({ headless: "new" });
const p = await browser.newPage();
await p.setViewport({ width: 1280, height: 800 });
await p.goto(BASE, { waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 900));

const report = await p.evaluate(() => {
	const hidden = (el) => {
		for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
			const s = getComputedStyle(n);
			if (s.display === "none") return `display:none on ${n.className || n.tagName}`;
			if (s.visibility === "hidden") return `visibility:hidden on ${n.className || n.tagName}`;
			if (Number.parseFloat(s.opacity) === 0) return `opacity:0 on ${n.className || n.tagName}`;
			if (n.inert) return `inert on ${n.className || n.tagName}`;
			if (n.hasAttribute?.("inert")) return `inert attr on ${n.className || n.tagName}`;
			const r = n.getBoundingClientRect();
			if (r.width === 0 || r.height === 0)
				return `zero-size (${Math.round(r.width)}x${Math.round(r.height)}) on ${n.className || n.tagName}`;
			if (s.overflow === "hidden" && r.width === 0) return `collapsed on ${n.className || n.tagName}`;
		}
		return null;
	};

	const out = [];
	for (const el of document.querySelectorAll("*")) {
		const text = [...el.childNodes]
			.filter((n) => n.nodeType === 3)
			.map((n) => n.textContent.trim())
			.join(" ")
			.trim();
		if (!text) continue;
		const s = getComputedStyle(el);
		const why = hidden(el);
		out.push({
			tag: el.tagName.toLowerCase(),
			cls: (el.className || "").toString().slice(0, 44),
			color: s.color,
			text: text.slice(0, 46),
			visible: why === null,
			why,
		});
	}
	return out;
});

const visible = report.filter((r) => r.visible);
const hiddenOnes = report.filter((r) => !r.visible);

console.log(`Text-bearing elements on landing: ${report.length}`);
console.log(`  genuinely visible: ${visible.length}`);
console.log(`  in a hidden subtree: ${hiddenOnes.length}\n`);

console.log("── HIDDEN (detector false positives) ──");
for (const r of hiddenOnes) console.log(`  ${r.cls.padEnd(30)} ${r.color.padEnd(22)} ${r.why}  "${r.text}"`);

console.log("\n── VISIBLE (must meet AA) ──");
for (const r of visible) console.log(`  ${r.cls.padEnd(30)} ${r.color.padEnd(22)} "${r.text}"`);

await browser.close();
