import puppeteer from "puppeteer";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,PATCH,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type, Authorization, X-Aspire-Device"};
const A={reply:"An index fund holds a little of every company.\n\n- One\n- Two",thread_id:"t",sources:[],follow_ups:["More?"]};
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:390,height:844});
await p.setRequestInterception(true);
p.on("request",r=>{if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
 if(r.url().endsWith("/chat"))return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify(A)});
 if(r.url().includes("/api/games/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"});
 r.continue();});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.type("#aspire-composer","q"); await p.keyboard.press("Enter");
await p.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:20000});
await new Promise(r=>setTimeout(r,600));
await p.click(".tool-btn--icon"); await new Promise(r=>setTimeout(r,500));
const m=await p.evaluate(()=>{
 const s=document.querySelector(".voice-menu"), sc=document.querySelector(".voice-sheet-scrim");
 const c=document.querySelector(".composer");
 const sr=s.getBoundingClientRect(), cr=c.getBoundingClientRect();
 const scr=sc?sc.getBoundingClientRect():null;
 return {vw:innerWidth,vh:innerHeight,
  sheet:{x:Math.round(sr.left),w:Math.round(sr.width),bottom:Math.round(sr.bottom)},
  gapFromBottom:Math.round(innerHeight-sr.bottom), widthShortfall:Math.round(innerWidth-sr.width),
  scrim: scr?{w:Math.round(scr.width),h:Math.round(scr.height),coverage:+((scr.width*scr.height)/(innerWidth*innerHeight)*100).toFixed(1)}:null,
  composerFilter:getComputedStyle(c).backdropFilter,
  composerBox:{x:Math.round(cr.left),w:Math.round(cr.width)}};});
console.log(JSON.stringify(m,null,1));
console.log(m.gapFromBottom===0&&m.widthShortfall===0 ? "PASS sheet pinned to viewport edges" : `FAIL sheet floats ${m.gapFromBottom}px above bottom, ${m.widthShortfall}px narrow`);
console.log(m.scrim&&m.scrim.coverage>90 ? "PASS scrim covers screen" : `FAIL scrim covers only ${m.scrim?.coverage}%`);
await b.close();
