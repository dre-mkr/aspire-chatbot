import puppeteer from "puppeteer";
const [,,out,vp]=process.argv; const [w,h]=vp.split("x").map(Number);
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"};
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:w,height:h});
let minted=0;
await p.setRequestInterception(true);
p.on("request",async r=>{if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
 if(r.url().endsWith("/chat")){const s=JSON.parse(r.postData()||"{}");
  return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify({reply:"A certificate is issued once you complete every module.\n\n- Ask your mentor\n- Keep it safe",thread_id:s.thread_id||`t-${++minted}`,sources:[],follow_ups:["How long does it take?"]})});}
 if(r.url().endsWith("/api/title"))return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify({title:"Completion certificate details"})});
 if(r.url().includes("/api/games/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"});
 r.continue();});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.evaluate(()=>localStorage.clear()); await p.reload({waitUntil:"networkidle2"});
for (const q of ["Do I get a certificate when I finish?","Who is eligible to join ASPIRE?"]) {
  await p.evaluate(()=>document.querySelector(".btn-new")?.click());
  await new Promise(r=>setTimeout(r,300));
  await p.type("#aspire-composer",q); await p.keyboard.press("Enter");
  await p.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:20000});
  await new Promise(r=>setTimeout(r,900));
}
await p.screenshot({path:out}); await b.close(); console.log("wrote",out);
