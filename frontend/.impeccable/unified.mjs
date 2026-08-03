/** Confirms the extracted primitives actually landed, measured in the browser. */
import puppeteer from "puppeteer";
const API="http://localhost:8000", BASE="http://localhost:4173";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,PATCH,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type, Authorization, X-Aspire-Device"};
const b=await puppeteer.launch({headless:"new"});
async function card(kind,gameType){
  const p=await b.newPage(); await p.setViewport({width:1280,height:1400});
  await p.setRequestInterception(true);
  p.on("request",r=>{
    if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
    if(r.url().endsWith("/chat")){
      const t=JSON.parse(r.postData()??"{}").thread_id;
      const url=kind==="elig"?`${API}/api/eligibility/start`:`${API}/api/games/start`;
      const body=kind==="elig"?{thread_id:t,language:"en"}:{thread_id:t,persona:"orion",language:"en",game_type:gameType};
      const ann=kind==="elig"?{eligibility_started:{check:"aspire_eligibility",language:"en"}}:{game_started:{game_type:gameType}};
      return void fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).catch(()=>{})
        .then(()=>r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify({reply:"",thread_id:t,sources:[],follow_ups:[],...ann})}));
    }
    r.continue();
  });
  await p.goto(`${BASE}/`,{waitUntil:"networkidle2"});
  await p.type("#aspire-composer","go"); await p.keyboard.press("Enter");
  await p.waitForSelector(kind==="elig"?".elig":".game",{timeout:20000});
  await new Promise(r=>setTimeout(r,700)); return p;
}
const g=(p,sel,prop)=>p.$eval(sel,(el,pr)=>getComputedStyle(el)[pr],prop).catch(()=>null);
const out={};
for(const [k,t,label] of [["game","word_scramble","scramble"],["game","true_false","truefalse"],["elig",null,"eligibility"]]){
  const p=await card(k,t);
  out[label]={
    leaveRadius: await g(p,".game__leave","borderRadius"),
    stepShape: await p.evaluate(()=>{const s=document.querySelector(".game__step");return s?`${Math.round(s.getBoundingClientRect().width)}x${Math.round(s.getBoundingClientRect().height)} r=${getComputedStyle(s).borderRadius}`:"none";}),
    stepCount: await p.evaluate(()=>document.querySelectorAll(".game__step").length),
    eyebrowFs: await g(p,".game__eyebrow","fontSize"),
    disabledToken: await p.evaluate(()=>getComputedStyle(document.querySelector(".game")).getPropertyValue("--disabled").trim()),
    choiceRadius: await g(p,".tf__choice","borderRadius"),
    optionRadius: await g(p,".elig__option","borderRadius"),
    btnRadius: await g(p,".game__btn","borderRadius"),
  };
  await p.close();
}
await b.close();
console.log(JSON.stringify(out,null,2));
