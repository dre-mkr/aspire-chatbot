import puppeteer from "puppeteer";
const b = await puppeteer.launch({ headless: "new" });
let fails = 0;
const say=(n,l,ok,d="")=>{ if(!ok)fails+=1; console.log(`  ${ok?"PASS":"FAIL"}  ${n}. ${l}${d?" — "+d:""}`); };
const settle=(ms=700)=>new Promise(r=>setTimeout(r,ms));

const look = (page) => page.evaluate(() => {
  const g = (s) => document.querySelector(s);
  const box = (el) => { if(!el) return null; const r=el.getBoundingClientRect();
    return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)}; };
  const op = (el) => el ? Number(getComputedStyle(el).opacity) : null;
  const mark=g(".rail__mark"), word=g(".rail__wordmark"), cell=g(".rail__logo"),
        coll=g(".rail__collapse"), rail=g(".rail"), newchat=g(".btn-new");
  return {
    railW: box(rail)?.w, cell: box(cell), markOp: op(mark), wordOp: op(word),
    markInert: mark?.hasAttribute("inert"), collInert: coll?.hasAttribute("inert"),
    wordAriaHidden: word?.getAttribute("aria-hidden"),
    markBox: box(mark), wordBox: box(word),
    wordNatural: word ? {w:word.naturalWidth,h:word.naturalHeight} : null,
    newChatY: box(newchat)?.y,
    // Opacity is not visibility. The first version of this file checked only
    // opacity and passed while the mark was laid out inside a zero-width
    // container -- present, "opaque", clipped to nothing and unclickable.
    // Hit-testing the centre of each mark is the check that actually holds.
    hitMark: (() => { const r = mark?.getBoundingClientRect(); if (!r) return null;
      const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
      return el ? (mark.contains(el) || el === mark) : false; })(),
    logoW: box(cell)?.w,
    // Accessible names present in the header.
    names: [...document.querySelectorAll(".rail__head img, .rail__head button")].map(el =>
      (el.getAttribute("alt") ?? "") || (el.innerText||"").trim() ||
      (el.querySelector(".sr-only")?.innerText ?? "")).filter(Boolean),
  };
});

const page = await b.newPage();
await page.setViewport({width:1280,height:900});
await page.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await page.evaluate(()=>localStorage.clear());
await page.reload({waitUntil:"networkidle2"});
// Get into the chat phase so the rail is a real column.
await page.type("#aspire-composer","hello");
await page.keyboard.press("Enter");
await page.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:90000});
await settle(1200);

const expanded = await look(page);
say(1,"Expanded: wordmark only, A mark hidden and inert",
  expanded.wordOp===1 && expanded.markOp===0 && expanded.markInert===true,
  `wordOpacity=${expanded.wordOp} markOpacity=${expanded.markOp} markInert=${expanded.markInert}`);
say("1b","Logo cell vertically centred against New chat, fixed height",
  expanded.cell.h===40, `cellHeight=${expanded.cell.h} cellY=${expanded.cell.y} newChatY=${expanded.newChatY}`);

// Sample mid-transition for clipping / height change.
await page.click(".rail__collapse");
await settle(150);
const mid = await look(page);
await settle(900);
const collapsed = await look(page);

say(2,"Collapse: crossfade, no height change, no clipping",
  mid.cell.h===40 && collapsed.cell.h===40 &&
  mid.markOp>0 && mid.markOp<1 && collapsed.markOp===1 && collapsed.wordOp===0,
  `mid markOpacity=${mid.markOp.toFixed(2)} wordOpacity=${mid.wordOp.toFixed(2)} cellH=${mid.cell.h}; settled markOpacity=${collapsed.markOp}`);
say("2b","Collapsed rail fits the mark without clipping, and it is really there",
  collapsed.railW>=76 && collapsed.markBox.w===40 &&
  collapsed.logoW>=40 && collapsed.hitMark===true,
  `railWidth=${collapsed.railW} markWidth=${collapsed.markBox.w} logoCellWidth=${collapsed.logoW} clickable=${collapsed.hitMark}`);

await page.click(".rail__mark");
await settle(900);
const again = await look(page);
say(3,"Expand again reverses cleanly",
  again.wordOp===1 && again.markOp===0 && again.cell.h===40,
  `wordOpacity=${again.wordOp} markOpacity=${again.markOp}`);

// 4 — keyboard reach in both states.
const focusable = async () => page.evaluate(() => {
  const els=[...document.querySelectorAll("#aspire-rail button")].filter(el=>!el.closest("[inert]") && !el.hasAttribute("inert"));
  return els.map(e=>e.className.split(" ")[0]);
});
const expFocus = await focusable();
await page.click(".rail__collapse"); await settle(900);
const colFocus = await focusable();
say(4,"A toggle is keyboard-reachable in BOTH states",
  expFocus.includes("icon-btn") && colFocus.includes("rail__mark"),
  `expanded=[${expFocus.join(",")}] collapsed=[${colFocus.join(",")}]`);

const ring = await page.evaluate(()=>{ const m=document.querySelector(".rail__mark"); m.focus();
  const s=getComputedStyle(m); return {outline:s.outlineWidth, active:document.activeElement===m}; });
say("4b","Collapsed toggle takes focus and shows a ring", ring.active, `outlineWidth=${ring.outline}`);

// 5 — announced once.
say(5,"Header announces the brand once, not twice",
  collapsed.names.filter(n=>/ASPIRE/i.test(n)).length<=1 && again.names.filter(n=>/ASPIRE/i.test(n)).length===1,
  `expanded=${JSON.stringify(again.names)} collapsed=${JSON.stringify(collapsed.names)}`);

// 8 — 2x crispness.
const dens = again.wordNatural.w / again.wordBox.w;
say(8,"Wordmark has the pixels to stay crisp at 2x",
  dens>=2, `natural=${again.wordNatural.w}px rendered=${again.wordBox.w}px density=${dens.toFixed(2)}x`);
await page.close();

// 6 — 320px drawer.
const m = await b.newPage();
await m.setViewport({width:320,height:568});
await m.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await m.evaluate(()=>localStorage.clear());
await m.reload({waitUntil:"networkidle2"});
await m.type("#aspire-composer","hello");
await m.keyboard.press("Enter");
await m.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:90000});
await settle(1200);
await m.click(".titlebar__menu"); await settle(800);
const drawer = await look(m);
say(6,"320px drawer shows the wordmark, no collapsed rail",
  drawer.wordOp===1 && drawer.markOp===0,
  `wordOpacity=${drawer.wordOp} markOpacity=${drawer.markOp}`);
await m.close();

await b.close();
console.log(`\n${fails===0?"All green.":fails+" failing."}\n`);
process.exit(fails===0?0:1);
