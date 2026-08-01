import puppeteer from "puppeteer";
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:1280,height:800});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.evaluate(()=>{const now=Date.now();
  localStorage.setItem("aspire.conversations.v1", JSON.stringify(Array.from({length:16},(_,i)=>({
    threadId:`t${i}`,title:`Conversation ${i+1}`,updatedAt:now-i*1000,
    messages:[{role:"user",text:"q"},{role:"assistant",blocks:[{kind:"paragraph",text:"a"}],sources:[],followUps:[]}]}))));});
await p.reload({waitUntil:"networkidle2"});
await p.type("#aspire-composer","hi"); await p.keyboard.press("Enter");
await new Promise(r=>setTimeout(r,2500));
const out=await p.evaluate(()=>{
  const res=[];
  for(const el of document.querySelectorAll("*")){
    const s=getComputedStyle(el);
    const clips=["hidden","auto","scroll"].includes(s.overflowX)||["hidden","auto","scroll"].includes(s.overflowY);
    if(!clips) continue;
    const kids=[...el.querySelectorAll("*")].filter(k=>{
      const ks=getComputedStyle(k); return ks.position==="absolute"||ks.position==="fixed";});
    if(!kids.length) continue;
    const er=el.getBoundingClientRect();
    res.push({el:`${el.tagName.toLowerCase()}${el.id?"#"+el.id:""}.${[...el.classList].join(".")}`.slice(0,50),
      overflow:`${s.overflowX}/${s.overflowY}`,
      children:kids.map(k=>{const kr=k.getBoundingClientRect();
        return {k:`${k.tagName.toLowerCase()}.${[...k.classList].join(".")}`.slice(0,40),
          pos:getComputedStyle(k).position,
          size:`${Math.round(kr.width)}x${Math.round(kr.height)}`,
          escapes: kr.right>er.right+1||kr.bottom>er.bottom+1||kr.left<er.left-1||kr.top<er.top-1};}).slice(0,6)});
  }
  return res;});
for(const r of out){console.log(`\n${r.el}  [${r.overflow}]`);
  for(const c of r.children) console.log(`   ${c.escapes?"ESCAPES":"inside "}  ${c.k} ${c.pos} ${c.size}`);}
await b.close();
