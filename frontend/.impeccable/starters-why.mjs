import puppeteer from "puppeteer";
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:320,height:720});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await new Promise(r=>setTimeout(r,800));
console.log(JSON.stringify(await p.evaluate(()=>{
  const q=s=>document.querySelector(s);
  const box=el=>el?{w:Math.round(el.getBoundingClientRect().width),client:el.clientWidth,scroll:el.scrollWidth,minW:getComputedStyle(el).minWidth,wrap:getComputedStyle(el).flexWrap}:null;
  return {
    stage: box(q(".stage")),
    starters: box(q(".starters")),
    startersRow: box(q(".starters__row")),
    firstStarter: box(q(".starter")),
    viewport: window.innerWidth,
  };
}),null,2));
await b.close();
