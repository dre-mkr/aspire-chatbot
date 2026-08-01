import puppeteer from "puppeteer";
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:1280,height:600});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
// Seed a long history directly, so the rail definitely scrolls.
await p.evaluate(()=>{
  const now=Date.now();
  const items=Array.from({length:16},(_,i)=>({
    threadId:`t${i}`, title:`Conversation number ${i+1} about money`,
    updatedAt: now - i*1000,
    messages:[{role:"user",text:`Question ${i+1}`},{role:"assistant",blocks:[{kind:"paragraph",text:"An answer."}],sources:[],followUps:[]}],
  }));
  localStorage.setItem("aspire.conversations.v1", JSON.stringify(items));
});
await p.reload({waitUntil:"networkidle2"});
await new Promise(r=>setTimeout(r,700));
// get into the chat phase so the rail is a real column
await p.type("#aspire-composer","hello"); await p.keyboard.press("Enter");
await new Promise(r=>setTimeout(r,2500));
const info=await p.evaluate(()=>{
  const body=document.querySelector(".rail__body");
  body.scrollTop=body.scrollHeight;
  const rows=[...document.querySelectorAll(".history-row")];
  return {rows:rows.length, scrolls: body.scrollHeight>body.clientHeight+1,
    bodyH:Math.round(body.clientHeight), contentH:Math.round(body.scrollHeight)};
});
await new Promise(r=>setTimeout(r,300));
await p.evaluate(()=>{const rows=[...document.querySelectorAll(".history-row")];
  rows[rows.length-1].querySelector(".history-more").click();});
await new Promise(r=>setTimeout(r,500));
const clip=await p.evaluate(()=>{
  const m=document.querySelector(".row-menu"); const body=document.querySelector(".rail__body");
  if(!m) return {menu:false};
  const mr=m.getBoundingClientRect();
  const hit=document.elementFromPoint(mr.left+mr.width/2, mr.top+mr.height/2);
  // The menu is fixed, so it is allowed to extend past the scrolling rail body
  // -- that is the whole point. The real constraint is the viewport.
  const outside = Math.max(0, mr.bottom-innerHeight) + Math.max(0, -mr.top)
                + Math.max(0, mr.right-innerWidth) + Math.max(0, -mr.left);
  return {menu:true, outsideViewportPx:Math.round(outside), reachable:!!hit&&(m===hit||m.contains(hit))};
});
console.log("rail:",JSON.stringify(info));
console.log("menu on LAST row:",JSON.stringify(clip));
console.log(clip.outsideViewportPx>0 ? `  FAIL ${clip.outsideViewportPx}px outside the viewport` : "  PASS fully on screen");
console.log(clip.reachable ? "  PASS reachable" : "  FAIL unreachable");
await p.screenshot({path:".impeccable/tb-clip.png"});
await b.close();
