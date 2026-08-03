import puppeteer from "puppeteer";
import { serveStream } from "./fake-stream.mjs";
import { serveAnonymousAuth } from "./fake-conversations.mjs";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,PATCH,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type, Authorization, X-Aspire-Device"};
const A={reply:"ok",thread_id:"t",sources:[],follow_ups:[]};
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:1280,height:800});
await p.setRequestInterception(true);
p.on("request",r=>{if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
 if (serveAnonymousAuth(r, CORS)) return;
 // The real transport. Without this the client falls back to `/chat`,
 // and this suite only passes while nothing is listening on :8000.
 if (serveStream(r, CORS, (sent) => { void sent; return { reply: A.reply }; })) return;
 if(r.url().endsWith("/chat"))return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify(A)});
 if(r.url().includes("/api/games/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"});
 r.continue();});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.evaluate(()=>localStorage.clear());
await p.reload({waitUntil:"networkidle2"});

// two conversations
for (const q of ["First question","Second question"]) {
  await p.evaluate(()=>{const b=document.querySelector(".btn-new"); if(b) b.click();});
  await new Promise(r=>setTimeout(r,400));
  await p.type("#aspire-composer",q); await p.keyboard.press("Enter");
  await p.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:20000});
  await new Promise(r=>setTimeout(r,500));
}
// set speed 1.5 and FR
await p.click(".tool-btn--icon"); await new Promise(r=>setTimeout(r,400));
await p.evaluate(()=>{[...document.querySelectorAll(".voice-choice")].find(b=>b.textContent.includes("1.5"))?.click();});
await p.evaluate(()=>{[...document.querySelectorAll(".voice-choice--lang")].find(b=>b.textContent.includes("FR"))?.click();});
await new Promise(r=>setTimeout(r,300));
const set=await p.evaluate(()=>({speed:[...document.querySelectorAll(".voice-choice")].find(b=>b.getAttribute("aria-pressed")==="true"&&!b.classList.contains("voice-choice--lang"))?.textContent.trim(),lang:[...document.querySelectorAll(".voice-choice--lang")].find(b=>b.getAttribute("aria-pressed")==="true")?.textContent.trim()}));
await p.keyboard.press("Escape"); await new Promise(r=>setTimeout(r,300));
console.log("set to:", JSON.stringify(set));

const read=async(label)=>{await p.click(".tool-btn--icon");await new Promise(r=>setTimeout(r,400));
 const v=await p.evaluate(()=>({speed:[...document.querySelectorAll(".voice-choice")].find(b=>b.getAttribute("aria-pressed")==="true"&&!b.classList.contains("voice-choice--lang"))?.textContent.trim(),lang:[...document.querySelectorAll(".voice-choice--lang")].find(b=>b.getAttribute("aria-pressed")==="true")?.textContent.trim()}));
 await p.keyboard.press("Escape");await new Promise(r=>setTimeout(r,300));
 const ok=v.speed===set.speed&&v.lang===set.lang;
 console.log(`  ${ok?"PASS":"FAIL"}  ${label} — ${JSON.stringify(v)}`); return ok;};

// switch conversation via the rail
await p.evaluate(()=>{document.querySelectorAll(".history-item")[1]?.click();});
await new Promise(r=>setTimeout(r,700));
const a=await read("survives switching conversation");
await p.reload({waitUntil:"networkidle2"}); await new Promise(r=>setTimeout(r,800));
const c=await read("survives a full refresh");
const where=await p.evaluate(()=>Object.keys(localStorage));
console.log("  storage keys:", JSON.stringify(where));
await b.close();
process.exit(a&&c?0:1);
