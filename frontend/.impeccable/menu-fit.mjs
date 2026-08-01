import puppeteer from "puppeteer";
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:320,height:568});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await p.evaluate(()=>{const now=Date.now();
 localStorage.setItem("aspire.conversations.v1",JSON.stringify(Array.from({length:14},(_,i)=>({
  threadId:`t${i}`,title:`Conversation ${i+1}`,updatedAt:now-i*1000,
  messages:[{role:"user",text:"q"},{role:"assistant",blocks:[{kind:"paragraph",text:"a"}],sources:[],followUps:[]}]}))));});
await p.reload({waitUntil:"networkidle2"});
await p.type("#aspire-composer","hi"); await p.keyboard.press("Enter");
await new Promise(r=>setTimeout(r,2500));
await p.evaluate(()=>document.querySelector(".titlebar__menu")?.click());
await new Promise(r=>setTimeout(r,600));
await p.evaluate(()=>{const bd=document.querySelector(".rail__body"); bd.scrollTop=bd.scrollHeight;});
await new Promise(r=>setTimeout(r,300));
await p.evaluate(()=>{const rows=[...document.querySelectorAll(".history-row")];
 rows[rows.length-1].querySelector(".history-more").click();});
await new Promise(r=>setTimeout(r,500));
const m=await p.evaluate(()=>{const menu=document.querySelector(".row-menu");
 if(!menu) return {menu:false};
 const r=menu.getBoundingClientRect();
 const items=[...menu.querySelectorAll(".row-menu__item")].map(i=>{const ir=i.getBoundingClientRect();
  const hit=document.elementFromPoint(ir.left+ir.width/2, ir.top+ir.height/2);
  return {label:i.textContent.trim(), reachable: !!hit&&(i===hit||i.contains(hit))};});
 return {menu:true,h:Math.round(r.height),bottom:Math.round(r.bottom),vh:innerHeight,
  overshoot:Math.max(0,Math.round(r.bottom-innerHeight)),items};});
console.log(JSON.stringify(m,null,1));
console.log(m.overshoot===0?"  PASS menu fits the viewport":`  FAIL overshoots by ${m.overshoot}px`);
console.log(m.items?.every(i=>i.reachable)?"  PASS all items reachable":"  FAIL "+JSON.stringify(m.items?.filter(i=>!i.reachable)));
await b.close();
