// Isolated loopback fixture. API writes are refused; no owner session or production service is used.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const base = process.env.GLOBE_QA_URL ?? "http://127.0.0.1:4331";
const output = process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname, "127.0.0.1");
assert.ok(output);
await mkdir(output, { recursive: true });
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const locations = ["Rehovot, Israel", "Beer Yaakov, Israel", "Tel Aviv, Israel", "Tel Aviv, Israel", "Tel Aviv, Israel", "New York, United States", "Berlin, Germany", "Dead Sea, Israel"];
const coords = [[34.8113,31.8928],[34.94,31.95],[34.782,32.085],[34.782,32.085],[34.782,32.085],[-74.006,40.7128],[13.405,52.52],[35.47,31.8928]];
const jobs = locations.map((location,n) => ({id:id(n),title:`Fixture role ${n}`,company:"Fixture",source:"fixture",last_seen_at:"2026-09-22T00:00:00Z",experience:null,description_available:false,seniority_origin:"unknown",extraction_state:"not-extracted",location,remote:false,seniority:null,stack:[],salary:null,url:"https://example.test",apply_url:null,posted_at:null,first_seen_at:"2026-09-22T00:00:00Z",status:"new",status_reason:null,score:80,fit_line:null,recommendation:null}));
const payload = {jobs,points:coords.map(([lng,lat],n)=>({posting_id:id(n),lng,lat,precision:"city",source:"Synthetic fixture",resolved_at:"2026-09-22T00:00:00Z"})),total_count:jobs.length,resolved_count:jobs.length,unresolved_count:0,attribution:"© OpenStreetMap contributors"};
const browser = await chromium.launch({headless:true,args:["--use-angle=swiftshader","--enable-unsafe-swiftshader"]});
const receipt = [];
try { for (const theme of ["light","dark"]) for (const mobile of [false,true]) {
  const name = `${theme}-${mobile?"mobile":"desktop"}`;
  if (process.env.GLOBE_QA_ONLY && name !== process.env.GLOBE_QA_ONLY) continue;
  const context = await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:900},reducedMotion:"reduce"});
  await context.addInitScript(({theme}) => {
    localStorage.setItem("job-radar-theme",theme);
    if (!localStorage.getItem("job-radar.board-preferences")) localStorage.setItem("job-radar.board-preferences",JSON.stringify({version:3,filter:"all",view:{search:"",source:"",location:"",seniority:"",fit:"",statuses:[],availability:"active",sort:"fit"}}));
    class FixtureEvents extends EventTarget { constructor() { super(); window.fixtureEvents=this; setTimeout(()=>this.dispatchEvent(new Event("ready")),20); } close() {} }
    window.EventSource=FixtureEvents;
  },{theme});
  const page = await context.newPage(), errors=[];
  page.on("pageerror",error=>errors.push(error.message));
  let fetches=0,shiftSelected=false;
  await page.route("**/*",route=>{
    const request=route.request(),url=new URL(request.url());
    if (url.hostname!=="127.0.0.1") return url.hostname.endsWith(".cartocdn.com")?route.continue():route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (request.method()!=="GET") return route.fulfill({status:405,json:{error:"Read-only fixture"}});
    if (url.pathname==="/api/jobs/globe") {fetches++;return route.fulfill({json:{...payload,jobs:jobs.map(job=>({...job,title:`${job.title} refresh ${fetches}`})),points:payload.points.map(point=>point.posting_id===id(1)&&shiftSelected?{...point,lng:point.lng+.01}:point)}});}
    if (url.pathname==="/api/jobs") return route.fulfill({json:{jobs:jobs.map(job=>({...job,title:`${job.title} refresh ${fetches}`}))}});
    const job=jobs.find(job=>url.pathname===`/api/jobs/${job.id}`);
    return job?route.fulfill({json:{job:{...job,raw_jd:null,reasons:[],score_payload:null,brain:null,scored_at:null}}}):route.fulfill({status:404,json:{error:"Fixture only"}});
  });
  const camera=()=>page.locator('[data-projection="globe"]').evaluate(el=>({center:el.dataset.center.split(",").map(Number),zoom:Number(el.dataset.zoom),starts:Number(el.dataset.cameraStarts||0)}));
  const cornersInside=()=>page.locator('[data-projection="globe"]').evaluate(el=>{const corners=JSON.parse(el.dataset.locationCorners||"[]");return {corners,width:el.clientWidth,height:el.clientHeight,inside:corners.length===4&&corners.every(([x,y])=>Number.isFinite(x)&&Number.isFinite(y)&&x>=0&&y>=0&&x<=el.clientWidth&&y<=el.clientHeight)};});
  const step={name,frames:[],errors};
  const shot=async label=>{const path=`${output}/${name}-${label}.png`;await page.screenshot({path});step.frames.push({label,path,camera:await camera()});};
  try {
    await page.goto(base);
    await page.getByRole("button",{name:"Globe",exact:true}).filter({visible:true}).click();
    await page.locator('[data-projection="globe"]').waitFor({timeout:30000});
    await page.locator('.globe-cluster').first().waitFor();
    await page.locator('.globe-cluster').first().hover();
    assert.equal(await page.locator('.globe-cluster').first().evaluate(node => getComputedStyle(node).scale), "1.06", "cluster hover scale composes with MapLibre marker translation");
    await shot("initial");
    if (!mobile && theme==="dark") {
      await page.evaluate(()=>{window.markerChurn=0;const globe=document.querySelector('.job-globe');window.markerObserver=new MutationObserver(records=>{for(const record of records)for(const node of [...record.addedNodes,...record.removedNodes])if(node.nodeType===1&&(node.matches?.('.globe-cluster')||node.querySelector?.('.globe-cluster')))window.markerChurn++;});window.markerObserver.observe(globe,{childList:true,subtree:true});});
      const before=await camera();
      for(let n=0;n<5;n++){await page.evaluate(()=>window.fixtureEvents.dispatchEvent(new Event("refresh")));await page.waitForTimeout(400);}
      await page.waitForTimeout(30000);
      const after=await camera(),churn=await page.evaluate(()=>window.markerChurn);
      assert.ok(fetches>=2,`SSE did not refetch: ${fetches}`);
      assert.ok(Math.abs(after.center[0]-before.center[0])<=1e-6&&Math.abs(after.center[1]-before.center[1])<=1e-6&&Math.abs(after.zoom-before.zoom)<=1e-6);
      assert.equal(after.starts,before.starts,"idle refresh moved the camera");
      assert.equal(churn,0,"unchanged geography replaced cluster markers");
      step.idle={before,after,churn,fetches};
      await page.setViewportSize({width:1400,height:900});await page.waitForTimeout(300);
      const resized=await camera();assert.ok(Math.abs(resized.center[0]-after.center[0])<1e-4&&Math.abs(resized.center[1]-after.center[1])<1e-4);step.resized=resized;
      await page.setViewportSize({width:1440,height:900});
    }
    if (mobile) await page.getByRole("button",{name:/Filters/}).first().click();
    await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).click();
    await page.getByRole("option",{name:"Israel",exact:true}).click();
    if (mobile) await page.getByRole("button",{name:"Show roles"}).click();
    await page.waitForFunction(()=>Number(document.querySelector('[data-projection="globe"]')?.dataset.zoom)>=5,{},{timeout:10000});
    await shot("israel");
    const israel=await camera();assert.ok(israel.zoom>=5);step.israelCorners=await cornersInside();assert.ok(step.israelCorners.inside,JSON.stringify(step.israelCorners));
    if (!mobile) {
      for(let n=0;n<2;n++) await page.getByRole("button",{name:"Zoom in"}).click();
      await page.waitForFunction(()=>Number(document.querySelector('[data-projection="globe"]')?.dataset.zoom)>=7.99);
      await page.locator(`[data-posting-id="${id(0)}"] > button`).click();
      await page.waitForTimeout(100);
      const before=await camera();
      const box=await page.locator('.maplibregl-canvas').boundingBox();
      const scale=512*2**before.zoom/360;
      const x=box.x+box.width/2+(coords[1][0]-coords[0][0])*scale;
      const y=box.y+box.height/2-(coords[1][1]-coords[0][1])*scale/Math.cos(coords[0][1]*Math.PI/180);
      for (const [dx,dy] of [[0,0],[3,0],[-3,0],[0,3],[0,-3]]) {await page.mouse.click(x+dx,y+dy);await page.waitForTimeout(120);if(await page.getByRole("dialog").count()) break;}
      await page.getByRole("dialog").waitFor({timeout:3000});
      assert.match(await page.getByRole("dialog").innerText(),/Fixture role 1/);
      await page.waitForTimeout(100);
      const after=await camera();assert.ok(after.zoom>=7.99,`dot click zoomed out ${before.zoom} -> ${after.zoom}`);
      step.dot={before,after};await shot("dot");
      if (theme==="dark") {const count=fetches;shiftSelected=true;await page.evaluate(()=>window.fixtureEvents.dispatchEvent(new Event("refresh")));await page.waitForTimeout(700);assert.ok(fetches>count);const refreshed=await camera();assert.equal(refreshed.starts,after.starts,"changed selected geography moved camera without another click");step.selectedRefresh=refreshed;}
      await page.getByRole("dialog").getByRole("button",{name:"Close"}).click();
      await page.getByRole("dialog").waitFor({state:"hidden"});
      const edgeBefore=await camera(),canvas=await page.locator('.maplibregl-canvas').boundingBox();
      const edgeScale=512*2**edgeBefore.zoom/360,edgeX=canvas.x+canvas.width/2+(coords[7][0]-edgeBefore.center[0])*edgeScale,edgeY=canvas.y+canvas.height/2-(coords[7][1]-edgeBefore.center[1])*edgeScale/Math.cos(edgeBefore.center[1]*Math.PI/180);
      for (const [dx,dy] of [[0,0],[3,0],[-3,0],[0,3],[0,-3]]) {await page.mouse.click(edgeX+dx,edgeY+dy);await page.waitForTimeout(120);if(await page.getByRole("dialog").count()) break;}
      await page.getByRole("dialog").waitFor({timeout:3000});assert.match(await page.getByRole("dialog").innerText(),/Fixture role 7/);
      await page.waitForFunction(before=>Number(document.querySelector('[data-projection="globe"]')?.dataset.cameraStarts||0)>before,edgeBefore.starts);
      const edgeAfter=await camera();assert.ok(edgeAfter.zoom>=edgeBefore.zoom);step.drawerClearance={before:edgeBefore,after:edgeAfter};await shot("drawer-clearance");
      await page.getByRole("dialog").getByRole("button",{name:"Close"}).click();
      await page.getByRole("dialog").waitFor({state:"hidden"});
    }
    if (mobile) await page.getByRole("button",{name:/Filters/}).first().click();
    await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).click();
    await page.getByRole("option",{name:"United States",exact:true}).click();
    if (mobile) await page.getByRole("button",{name:"Show roles"}).click();
    await shot("united-states");
    step.usCorners=await cornersInside();assert.ok(step.usCorners.inside,JSON.stringify(step.usCorners));
    if (mobile) await page.getByRole("button",{name:/Filters/}).first().click();
    await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).click();
    await page.getByRole("option",{name:"Other",exact:true}).click();
    if (mobile) {await page.getByRole("button",{name:"Show roles"}).click();await page.getByRole("button",{name:/Filters/}).first().click();}
    const other=await camera();assert.ok(Math.abs(other.center[0]-13.405)<.01&&Math.abs(other.center[1]-52.52)<.01,JSON.stringify(other));step.other=other;
    await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).click();
    await page.getByRole("option",{name:"All locations",exact:true}).click();
    if (mobile) await page.getByRole("button",{name:"Show roles"}).click();
    await page.waitForTimeout(100);await shot("world");
    const world=await camera();assert.ok(Math.abs(world.center[0]-34.8113)<.01&&Math.abs(world.center[1]-31.8928)<.01);
    const reset=page.getByRole("button",{name:"Reset view",exact:true}).filter({visible:true});
    if (!mobile) {const box=await page.locator('.maplibregl-canvas').boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+100,box.y+box.height/2,{steps:8});await page.mouse.up();}
    else await page.getByRole("button",{name:"Zoom in"}).click();
    await page.waitForTimeout(350);
    assert.ok(await reset.isEnabled());await reset.click();await page.waitForTimeout(100);
    const home=await camera();assert.ok(Math.abs(home.center[0]-34.8113)<.01&&Math.abs(home.center[1]-31.8928)<.01);step.home=home;await shot("reset");
    if (!mobile && theme==="light") {
      const toggle=page.getByRole("button",{name:"Globe",exact:true});
      await toggle.click();
      await page.getByRole("combobox",{name:"Location",exact:true}).click();
      await page.getByRole("option",{name:"Israel",exact:true}).click();
      await toggle.click();await page.waitForTimeout(550);
      const offIsrael=await camera();
      assert.ok(offIsrael.zoom>=5 && Math.abs(offIsrael.center[0]-35.05)<.5,`off→Israel→on restored the old camera: ${JSON.stringify(offIsrael)}`);
      step.offIsrael=offIsrael;
      await page.emulateMedia({reducedMotion:"no-preference"});
      await page.getByRole("combobox",{name:"Location",exact:true}).click();
      await page.getByRole("option",{name:"United States",exact:true}).click();
      await page.waitForTimeout(1100);
      const beforeOffReset=await camera();assert.ok(beforeOffReset.center[0]<-90,JSON.stringify(beforeOffReset));
      await toggle.click();
      await page.getByRole("button",{name:"Reset view",exact:true}).click();
      await toggle.click();await page.waitForTimeout(1100);
      const offReset=await camera();
      assert.ok(Math.abs(offReset.center[0]-34.8113)<.01 && Math.abs(offReset.center[1]-31.8928)<.01 && offReset.zoom<=1.91,`off→Reset→on restored the old camera: ${JSON.stringify(offReset)}`);
      step.offReset={before:beforeOffReset,after:offReset};
    }
    if (!mobile && theme==="light") for (const [location,expectedLng] of [["israel",35.05],["other",13.405]]) {
      await page.waitForTimeout(300);
      await page.evaluate(location=>{const key="job-radar.board-preferences",saved={version:3,filter:"all",view:{search:"",source:"",location,seniority:"",fit:"",statuses:[],availability:"active",sort:"fit"}};localStorage.setItem(key,JSON.stringify(saved));},location);
      await page.reload();await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).waitFor();
      const selectedLocation=await page.getByRole("combobox",{name:"Location",exact:true}).filter({visible:true}).innerText();assert.match(selectedLocation,new RegExp(location==="israel"?"Israel":"Other"));
      await page.getByRole("button",{name:"Globe",exact:true}).filter({visible:true}).click();await page.locator('[data-projection="globe"]').waitFor({timeout:30000});
      await page.waitForFunction(expected=>Math.abs(Number(document.querySelector('[data-projection="globe"]')?.dataset.center?.split(",")[0])-expected)<.01,expectedLng,{timeout:30000});
      const first=await camera();assert.ok(Math.abs(first.center[0]-expectedLng)<.01&&(location==="israel"?first.zoom>=5:first.zoom<=1.91),`first ${location} camera was ${JSON.stringify(first)}`);
      step[`first-${location}`]=first;
    }
  } catch(error) {step.failure=String(error);step.failureCamera=await camera().catch(()=>null);step.focusDecision=await page.locator('[data-projection="globe"]').getAttribute('data-focus-decision').catch(()=>null);await page.screenshot({path:`${output}/${name}-failure.png`}).catch(()=>{});throw error;}
  finally {await context.close();receipt.push(step);}
}}
finally {await browser.close();await writeFile(`${output}/receipt.json`,JSON.stringify(receipt,null,2));}
console.log(JSON.stringify(receipt.map(({name,failure,idle,dot,home,offIsrael,offReset})=>({name,failure,idle,dot,home,offIsrael,offReset}))));
