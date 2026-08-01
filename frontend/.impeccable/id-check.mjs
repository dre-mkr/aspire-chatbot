import puppeteer from "puppeteer";
const b=await puppeteer.launch({headless:"new"});
const p=await b.newPage(); await p.setViewport({width:1280,height:800});
await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
await new Promise(r=>setTimeout(r,600));
const t=await p.evaluate(()=>{const e=document.querySelector(".hero__identity");
 const rs=[];for(const n of e.childNodes){if(n.nodeType!==3||!n.textContent.trim())continue;
  const r=document.createRange();r.selectNodeContents(n);
  for(const q of r.getClientRects()) if(q.width>1&&q.height>1) rs.push({x:q.left,y:q.top,w:q.width,h:q.height});}
 return {color:getComputedStyle(e).color,px:parseFloat(getComputedStyle(e).fontSize),rects:rs};});
await p.addStyleTag({content:"*,*::before,*::after{color:transparent!important}"});
await new Promise(r=>setTimeout(r,250));
const shot=await p.screenshot({encoding:"base64"});
const out=await p.evaluate(async(b64,t)=>{const img=new Image();img.src="data:image/png;base64,"+b64;await img.decode();
 const c=document.createElement("canvas");c.width=img.width;c.height=img.height;
 const x=c.getContext("2d",{willReadFrequently:true});x.drawImage(img,0,0);const dpr=img.width/innerWidth;
 const lum=([r,g,bb])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4};return .2126*f(r)+.7152*f(g)+.0722*f(bb)};
 const ratio=(a,b)=>{const[m,n]=[lum(a),lum(b)].sort((u,v)=>v-u);return (m+.05)/(n+.05)};
 const fg=t.color.match(/[\d.]+/g).map(Number); const a=fg[3]??1;
 const pts=[];for(const r of t.rects)for(let gx=1;gx<=6;gx++)for(let gy=1;gy<=3;gy++){
  const px=Math.round((r.x+r.w*gx/7)*dpr),py=Math.round((r.y+r.h*gy/4)*dpr);
  const d=x.getImageData(px,py,1,1).data;pts.push([d[0],d[1],d[2]]);}
 const s=pts.slice().sort((m,n)=>lum(m)-lum(n));
 const over=bg=>fg.slice(0,3).map((v,k)=>v*a+bg[k]*(1-a));
 return {samples:pts.length,worst:+Math.min(ratio(over(s[0]),s[0]),ratio(over(s[s.length-1]),s[s.length-1])).toFixed(2),px:t.px};},shot,t);
console.log(` ${out.worst>=4.5?"PASS":"FAIL"}  .hero__identity ${out.worst}:1 (need 4.5) @${out.px}px, ${out.samples} samples`);
await b.close();
