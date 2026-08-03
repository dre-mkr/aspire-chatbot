import puppeteer from "puppeteer";
const CORS={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,PATCH,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type, Authorization, X-Aspire-Device"};
const long="The money belongs to the ASPIRE participant, the child. Parents and guardians can view the account but the balance is the child's own. ";
const A={reply:(long+long+long),thread_id:"t",sources:[],follow_ups:[]};
const b=await puppeteer.launch({headless:"new"});
for(const [name,w,h] of [["desktop",1280,800],["mobile",390,844]]){
 const p=await b.newPage(); await p.setViewport({width:w,height:h});
 await p.setRequestInterception(true);
 p.on("request",r=>{if(r.method()==="OPTIONS")return r.respond({status:204,headers:CORS});
  if(r.url().endsWith("/chat"))return r.respond({status:200,contentType:"application/json",headers:CORS,body:JSON.stringify(A)});
  if(r.url().includes("/api/games/"))return r.respond({status:404,contentType:"application/json",headers:CORS,body:"{}"});
  r.continue();});
 await p.goto("http://localhost:4173/",{waitUntil:"networkidle2"});
 for(let i=0;i<3;i++){await p.type("#aspire-composer",`Question ${i}`);await p.keyboard.press("Enter");
  await p.waitForFunction(()=>!document.querySelector(".composer__send--stop"),{timeout:25000});}
 await new Promise(r=>setTimeout(r,600));
 const m=await p.evaluate(()=>{
  const t=document.querySelector(".thread");
  t.scrollTop=Math.floor(t.scrollHeight*0.5);
  return {padTop:getComputedStyle(t).paddingTop, mask:getComputedStyle(t).maskImage.slice(0,80),
   scrollTop:Math.round(t.scrollTop), top:Math.round(t.getBoundingClientRect().top)};});
 await new Promise(r=>setTimeout(r,400));
 // sample the same ink at the top of the scroll viewport vs well below it
 const shot=await p.screenshot({encoding:"base64"});
 const out=await p.evaluate(async(b64,threadTop)=>{
  const img=new Image();img.src="data:image/png;base64,"+b64;await img.decode();
  const c=document.createElement("canvas");c.width=img.width;c.height=img.height;
  const x=c.getContext("2d",{willReadFrequently:true});x.drawImage(img,0,0);
  const dpr=img.width/innerWidth;
  const darkest=(yCss)=>{let best=[255,255,255];
   for(let px=0;px<innerWidth;px+=2){const d=x.getImageData(Math.round(px*dpr),Math.round(yCss*dpr),1,1).data;
    const l=d[0]+d[1]+d[2]; if(l<best[0]+best[1]+best[2]) best=[d[0],d[1],d[2]];}
   return best;};
  const lum=([r,g,bb])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4};return .2126*f(r)+.7152*f(g)+.0722*f(bb)};
  const ratio=(a,bg)=>{const[m,n]=[lum(a),lum(bg)].sort((u,v)=>v-u);return (m+.05)/(n+.05)};
  const white=[255,255,255];
  const near=darkest(threadTop+30), far=darkest(threadTop+140);
  return {nearTop:+ratio(near,white).toFixed(2), wellBelow:+ratio(far,white).toFixed(2)};
 },shot,m.top);
 const loss=+(100-(out.nearTop/out.wellBelow*100)).toFixed(0);
 console.log(`${name}: padTop=${m.padTop} mask=${m.mask.slice(0,46)}...`);
 console.log(`  ink 30px into the viewport: ${out.nearTop}:1   140px in: ${out.wellBelow}:1   loss ${loss}%`);
 console.log(`  ${loss<15?"PASS":"FAIL"} arriving text is not materially dimmed`);
 await p.close();
}
await b.close();
