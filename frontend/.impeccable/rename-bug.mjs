import puppeteer from "puppeteer";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"};
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:1280,height:800});
let minted=0;
await p.setRequestInterception(true);
p.on("request",async r=>{if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
 if(r.url().endsWith("/chat")){const s=JSON.parse(r.postData()||"{}");
  return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify({reply:"Yes, a certificate is issued.",thread_id:s.thread_id||`t-${++minted}`,sources:[],follow_ups:[]})});}
 if(r.url().endsWith("/api/title")){await new Promise(x=>setTimeout(x,2500));
  return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify({title:"Completion certificate details"})});}
 if(r.url().includes("/api/games/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"});
 r.continue();});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.evaluate(()=>localStorage.clear()); await p.reload({waitUntil:"networkidle2"});
await p.type("#aspire-composer","Do I get a certificate when I finish the programme?");
await p.keyboard.press("Enter");
await p.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:20000});
await new Promise(r=>setTimeout(r,300));

// R2: is the bar empty during the first answer / before the title lands?
const early=await p.evaluate(()=>{const t=document.querySelector(".titlebar__text");const btn=document.querySelector(".titlebar__title");
 const r=btn?btn.getBoundingClientRect():null;
 return {text:t?t.textContent:null, btnH:r?Math.round(r.height):null, btnW:r?Math.round(r.width):null};});
console.log("during first answer:", JSON.stringify(early));
console.log(early.text ? "  PASS bar shows something" : `  FAIL bar empty, button ${early.btnW}x${early.btnH}`);

// R1: open the rename editor BEFORE the title lands, press Enter without typing.
await p.click(".titlebar__title"); await new Promise(r=>setTimeout(r,200));
await new Promise(r=>setTimeout(r,2600));   // generated title arrives while editing
await p.keyboard.press("Enter"); await new Promise(r=>setTimeout(r,500));
const s=await p.evaluate(()=>JSON.parse(localStorage.getItem("aspire.conversations.v1")||"[]"));
console.log("after bare Enter mid-generation:", JSON.stringify({title:s[0]?.title,src:s[0]?.titleSource}));
console.log(s[0]?.title==="Completion certificate details" ? "  PASS generated title kept" : `  FAIL generated title destroyed, locked as ${s[0]?.titleSource}`);
await b.close();
