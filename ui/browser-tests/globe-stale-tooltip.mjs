import assert from "node:assert/strict";
import { chromium } from "@playwright/test";
const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4351";
assert.equal(new URL(base).hostname, "127.0.0.1");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`; const coords = [[34.60, 31.70], [35.10, 32.30], [35.30, 31.60]];
const jobs = coords.map((_, n) => ({id:id(n),title:`Fixture role ${n}`,company:"Fixture",source:"fixture",last_seen_at:"2026-09-22T00:00:00Z",experience:null,description_available:false,seniority_origin:"unknown",extraction_state:"not-extracted",location:"Tel Aviv-Yafo, Israel",remote:false,seniority:null,stack:[],salary:null,url:"https://example.test",apply_url:null,posted_at:null,first_seen_at:"2026-09-22T00:00:00Z",status:"new",status_reason:null,score:80,fit_line:null,recommendation:null}));
const payload = {jobs,points:coords.map(([lng,lat],n)=>({posting_id:id(n),lng,lat,precision:"city",source:"fixture",resolved_at:"2026-09-22T00:00:00Z"})),total_count:3,resolved_count:3,unresolved_count:0,attribution:"© OpenStreetMap contributors"};
const browser = await chromium.launch({headless:true,args:["--use-angle=swiftshader","--enable-unsafe-swiftshader"]});
try {
  const context = await browser.newContext({viewport:{width:1440,height:900},reducedMotion:"no-preference"});
  try {
    const page = await context.newPage();
    await page.addInitScript(() => {
      localStorage.setItem("job-globe-dragged","1");
      localStorage.setItem("job-radar.board-preferences",JSON.stringify({version:3,filter:"all",view:{search:"",source:"",location:"",seniority:"",fit:"",statuses:[],availability:"active",sort:"fit"}}));
      window.EventSource = class { addEventListener() {} close() {} };
    });
    await page.route("**/*",route=>{const request=route.request(),url=new URL(request.url());if(url.hostname!=="127.0.0.1")return url.hostname.endsWith(".cartocdn.com")?route.continue():route.abort();if(!url.pathname.startsWith("/api/"))return route.continue();if(request.method()!=="GET")return route.fulfill({status:405,json:{}});if(url.pathname==="/api/jobs/globe")return route.fulfill({json:payload});if(url.pathname==="/api/jobs")return route.fulfill({json:{jobs}});return route.fulfill({status:404,json:{}});});
    await page.goto(base);
    await page.getByRole("button",{name:"Globe",exact:true}).click();
    const bubble=page.locator(".globe-cluster").first();
    await bubble.waitFor({timeout:30000});
    await page.waitForTimeout(1200);
    const box=await bubble.boundingBox();
    await page.evaluate(()=>document.addEventListener("pointerdown",event=>{const bubble=[...document.querySelectorAll(".globe-cluster")].some(button=>{const r=button.getBoundingClientRect();return event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top&&event.clientY<=r.bottom;});if(bubble)window.bubblePointerTrusted=event.isTrusted;},true));
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
    await page.getByRole("tooltip").waitFor();
    await page.waitForTimeout(200);
    const tooltipBeforeClick=await page.getByRole("tooltip").innerText();
    assert.match(tooltipBeforeClick,/3 roles near Tel Aviv/);
    await page.mouse.down(); await page.mouse.up();
    assert.equal(await page.evaluate(()=>window.bubblePointerTrusted),true,"bubble activation began with a trusted pointer event");
    await page.getByRole("button",{name:/Clear bubble filter/}).waitFor();
    // A detached marker can disappear without delivering mouseleave.
    await bubble.evaluate(element=>{element.onmouseleave=null;});
    await page.waitForFunction(()=>document.querySelectorAll(".globe-cluster").length===0,null,{timeout:15000});
    await page.waitForTimeout(1500);
    const staleTooltipCount=await page.getByRole("tooltip").count(); assert.equal(staleTooltipCount,0,"bubble tooltip clears immediately after its marker is removed");
    await page.mouse.move(box.x+box.width/2+40,box.y+box.height/2+40,{steps:5});
    const camera=await page.locator("[data-projection]").evaluate(el=>({center:el.dataset.center.split(",").map(Number),zoom:Number(el.dataset.zoom),rect:el.getBoundingClientRect().toJSON()})); const scale=512*2**camera.zoom/360;
    const x=camera.rect.x+camera.rect.width/2+(coords[0][0]-camera.center[0])*scale;
    const y=camera.rect.y+camera.rect.height/2-(coords[0][1]-camera.center[1])*scale/Math.cos(camera.center[1]*Math.PI/180);
    let hovered=false;
    for(const [dx,dy] of [[0,0],[3,0],[-3,0],[0,3],[0,-3]]){await page.mouse.move(x+dx,y+dy,{steps:3});await page.waitForTimeout(250);if(await page.locator(`[data-globe-hover="${id(0)}"]`).count()){hovered=true;break;}}
    assert.equal(hovered,true,"a trusted pointer hover reveals the dot card after the bubble click");
    assert.equal(await page.getByRole("tooltip").count(),0,"dot hover leaves no bubble tooltip over the card");
  } finally { await context.close(); }
} finally { await browser.close(); }
