/**
 * Ground-truth contrast for the landing screen's genuinely visible text.
 *
 * The detector reports a colour pair by walking the DOM for a background, which
 * cannot resolve a transparent control stacked on a white panel stacked on the
 * page gradient. This samples the ACTUAL rendered pixels immediately around
 * each text run from a screenshot, and computes WCAG contrast against the
 * darkest and lightest background pixel found there — so a gradient is judged
 * at its worst point under the text, not at an average.
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://localhost:4173";

const lin = (c) => {
	const s = c / 255;
	return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => {
	const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m);
	return (x + 0.05) / (y + 0.05);
};
const hex = ([r, g, b]) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;

const browser = await puppeteer.launch({ headless: "new" });
const p = await browser.newPage();
await p.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
await p.goto(BASE, { waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 1200));

/* Visible text runs worth judging, plus their computed colour and font. */
const targets = await p.evaluate(() => {
	const sels = [".hero__title", ".hero__sub", ".tool-btn__label", ".disclaimer", ".starter", ".composer textarea"];
	const out = [];
	for (const sel of sels) {
		for (const el of document.querySelectorAll(sel)) {
			// The element box is not the text box: a centred h1 spans its whole
			// container, so most of its box is background the glyphs never touch.
			// A Range over the text node gives the real painted run.
			const node = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
			let r = el.getBoundingClientRect();
			if (node) {
				const range = document.createRange();
				range.selectNodeContents(node);
				const rr = range.getBoundingClientRect();
				if (rr.width > 0 && rr.height > 0) r = rr;
			}
			if (r.width === 0 || r.height === 0) continue;
			const s = getComputedStyle(el);
			if (Number.parseFloat(s.opacity) === 0) continue;
			out.push({
				sel,
				color: s.color,
				fontSize: Number.parseFloat(s.fontSize),
				fontWeight: Number.parseInt(s.fontWeight, 10),
				box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
				text: (el.textContent ?? el.placeholder ?? "").trim().slice(0, 40),
			});
			break;
		}
	}
	return out;
});

/* Decode the screenshot in the page with canvas — no new dependency. */
const shot = await p.screenshot({ type: "png", encoding: "base64" });
const pixels = await p.evaluate(async (b64) => {
	const blob = await (await fetch(`data:image/png;base64,${b64}`)).blob();
	const bmp = await createImageBitmap(blob);
	const cv = new OffscreenCanvas(bmp.width, bmp.height);
	const ctx = cv.getContext("2d");
	ctx.drawImage(bmp, 0, 0);
	const d = ctx.getImageData(0, 0, bmp.width, bmp.height);
	return { w: bmp.width, h: bmp.height, data: [...d.data] };
}, shot);

const at = (x, y) => {
	const i = (pixels.w * y + x) << 2;
	return [pixels.data[i], pixels.data[i + 1], pixels.data[i + 2]];
};

console.log("Landing screen — measured against real pixels\n");
let fails = 0;
for (const t of targets) {
	const rgb = t.color.match(/\d+/g).slice(0, 3).map(Number);
	// The background is the MODAL colour in the box, not the worst pixel: a
	// glyph's antialiased edge runs the whole way from ink to background, so
	// "worst pixel" just rediscovers the antialiasing. Text never covers most
	// of its own box, so the mode is the background. Quantised to 8 levels per
	// channel so a gradient's neighbouring shades group together.
	const hist = new Map();
	const { x, y, w, h } = t.box;
	for (let sy = y + 1; sy < Math.min(y + h - 1, pixels.h - 1); sy += 1)
		for (let sx = x + 1; sx < Math.min(x + w - 1, pixels.w - 1); sx += 1) {
			const px = at(sx, sy);
			const key = px.map((v) => v >> 3).join(",");
			const e = hist.get(key) ?? { n: 0, px };
			e.n += 1;
			hist.set(key, e);
		}
	if (!hist.size) {
		console.log(`  ${t.sel}: no background pixels sampled`);
		continue;
	}
	// Over a gradient the text spans several shades; judge the worst of the
	// bands that actually occupy a meaningful share of the box.
	const total = [...hist.values()].reduce((n, e) => n + e.n, 0);
	// Drop the band that IS the ink. Over a gradient the background is spread
	// across many quantised bands while the glyphs concentrate into one, so the
	// text colour can out-count any single background band.
	const bands = [...hist.values()].filter(
		(e) => e.n / total > 0.05 && ratio(e.px, rgb) > 1.15,
	);
	const pool = bands.length ? bands : [[...hist.values()].sort((a, b) => b.n - a.n)[0]];
	const worst = pool.reduce((acc, e) => (ratio(e.px, rgb) < ratio(acc, rgb) ? e.px : acc), pool[0].px);
	const large = t.fontSize >= 24 || (t.fontSize >= 18.66 && t.fontWeight >= 700);
	const need = large ? 3 : 4.5;
	const got = ratio(worst, rgb);
	const ok = got >= need;
	if (!ok) fails += 1;
	console.log(
		`  ${ok ? "PASS" : "FAIL"}  ${t.sel.padEnd(20)} ${hex(rgb)} on ${hex(worst)}  ` +
			`${got.toFixed(2)}:1 (need ${need}, ${t.fontSize}px/${t.fontWeight})  "${t.text}"`,
	);
}
console.log(`\n${fails} genuine contrast failure${fails === 1 ? "" : "s"} on visible landing text.`);
await browser.close();
