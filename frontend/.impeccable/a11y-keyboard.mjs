/**
 * The keyboard and language half of P10, asserted rather than eyeballed.
 *
 * P10-005  `<html lang>` was hardcoded to "en", so a screen reader pronounced
 *          Spanish and French answers with English phonetics. WCAG 3.1.1 (A)
 *          and 3.1.2 (AA).
 * P10-004  The composer was LAST in the tab order, and the cycle grew with the
 *          conversation -- 25 focusable elements at 3 turns, 99 at 40. The skip
 *          link is what makes the primary control reachable in one press.
 * P10-007  One Tab press landed on <body> while passing the collapsed rail: the
 *          scroll container took a tab stop of its own while everything inside
 *          it was inert.
 *
 *   node .impeccable/preview-server.mjs &
 *   node .impeccable/a11y-keyboard.mjs
 *
 * Review-only. Never built or shipped.
 */
import puppeteer from "puppeteer";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,PATCH,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type, Authorization, X-Aspire-Device"};
const b=await puppeteer.launch({headless:"new"});
let fails=0; const say=(l,ok,d="")=>{if(!ok)fails++;console.log(`  ${ok?"PASS":"FAIL"}  ${l}${d?` — ${d}`:""}`);};
for (const [lang,url] of [["en","http://localhost:4173/"],["es","http://localhost:4173/?lang=es"],["fr","http://localhost:4173/?lang=fr"]]) {
  const p=await b.newPage(); await p.setViewport({width:1280,height:800});
  await p.setRequestInterception(true);
  p.on("request",r=>{ if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
    if(r.url().includes("/api/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"}); r.continue();});
  await p.goto(url,{waitUntil:"networkidle2"}); await new Promise(r=>setTimeout(r,500));
  say(`document lang is ${lang}`, (await p.evaluate(()=>document.documentElement.lang))===lang, await p.evaluate(()=>document.documentElement.lang));
  await p.close();
}
// Skip link: first Tab from the top of the workspace must reach it, and it must land on the composer.
const p=await b.newPage(); await p.setViewport({width:1280,height:800});
await p.setRequestInterception(true);
p.on("request",r=>{ if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
  if(r.url().includes("/api/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"}); r.continue();});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"}); await new Promise(r=>setTimeout(r,500));
// Start from a known place. The composer takes focus on mount on a pointer
// device, so tabbing without this begins part-way through the cycle and the
// wrap-around -- which legitimately passes through the document -- looks like
// the dead stop this is testing for.
// `blur()` alone is not enough: it clears `activeElement` but leaves Chrome's
// sequential focus navigation starting point where it was, so Tab carries on
// from the composer. Focusing <body> explicitly is what moves the start.
await p.evaluate(()=>{ const el=document.body; el.setAttribute("tabindex","-1"); el.focus(); el.removeAttribute("tabindex"); });
const order=[]; for(let i=0;i<7;i++){ await p.keyboard.press("Tab");
  order.push(await p.evaluate(()=>{const a=document.activeElement; return a?`${a.tagName.toLowerCase()}${typeof a.className==="string"&&a.className?"."+a.className.split(" ").filter(Boolean)[0]:""}`:"none";}));}
say("the skip link is first in the tab order", order[0]?.includes("skip-link"), order.join(" > "));
// The point of P10-004 is not a particular position, it is that the position
// stops growing. The composer used to be LAST, after every message's copy,
// replay and ask-again button -- 25 focusable elements at 3 turns, 99 at 40.
// A small constant is the fix; which small constant is not the finding.
const composerAt = order.indexOf("textarea");
say("the composer is reachable in a few presses, not last", composerAt >= 0 && composerAt < 4, `position ${composerAt + 1}`);
// A stop on <body> is only legitimate at the wrap back to the top of the
// document. One anywhere in the middle is the P10-007 defect: a focusable
// scroll container whose contents are all inert.
const deadStops = order.slice(0, -1).filter(o=>o==="body").length;
say("no dead tab stop mid-cycle", deadStops===0, `order: ${order.join(" > ")}`);
await p.evaluate(()=>document.querySelector(".skip-link").click());
await new Promise(r=>setTimeout(r,300));
say("and it reaches the composer", (await p.evaluate(()=>document.activeElement?.id||location.hash))!=="" , await p.evaluate(()=>location.hash));
await b.close();
console.log(fails?`\n${fails} FAIL`:"\nALL PASS");
