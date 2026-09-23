// Isolated loopback replay only; optional full cohort JSON never contains credentials.
import {chromium} from '@playwright/test';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const base=process.env.GLOBE_QA_URL??'http://127.0.0.1:4318', output=process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname,'127.0.0.1');assert.ok(output);await mkdir(output,{recursive:true});
const job={id:'00000000-0000-4000-8000-000000000001',title:'Camera fixture engineer',company:'Camera fixture',source:'fixture',last_seen_at:'2026-09-22T00:00:00Z',experience:null,description_available:false,seniority_origin:'unknown',extraction_state:'not-extracted',location:'Rehovot, Israel',remote:true,seniority:null,stack:[],salary:null,url:'https://example.test',apply_url:null,posted_at:null,first_seen_at:'2026-09-22T00:00:00Z',status:'new',status_reason:null,score:80,fit_line:null,recommendation:null};
const payload=process.env.GLOBE_CAMERA_COHORT?JSON.parse(await readFile(process.env.GLOBE_CAMERA_COHORT,'utf8')):{jobs:[job],points:[{posting_id:job.id,lat:31.8928,lng:34.8113,precision:'city',source:'Development fixture',resolved_at:'2026-09-22T00:00:00Z'}],total_count:1,resolved_count:1,unresolved_count:0,attribution:'© OpenStreetMap contributors'};
const view={search:'',source:'',location:'',seniority:'',fit:'',statuses:[],availability:'all',sort:'fit'};
const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const receipts=[];
try {for(const mobile of [false,true])for(const reducedMotion of ['reduce','no-preference']){
 const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1100},reducedMotion});
 await context.addInitScript(view=>localStorage.setItem('job-radar.board-preferences',JSON.stringify({version:3,filter:'all',view})),view);
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/**',route=>{const path=new URL(route.request().url()).pathname;if(path==='/api/jobs/globe')return route.fulfill({json:payload});if(path==='/api/jobs')return route.fulfill({json:{jobs:payload.jobs}});if(path==='/api/events')return route.fulfill({contentType:'text/event-stream',body:'event: ready\ndata: {}\n\n'});return route.fulfill({status:404,json:{error:'Isolated read-only replay'}});});
 const name=`${mobile?'mobile':'desktop'}-${reducedMotion}`;
 try{
  await page.goto(base);await page.getByRole('button',{name:'Globe',exact:true}).waitFor();
  // Mount and load inside a genuinely hidden panel, then expose its real dimensions.
  const hidden=await page.addStyleTag({content:'.globe-slot {display:none !important}'});
  await page.getByRole('button',{name:'Globe',exact:true}).click();
  await page.waitForTimeout(2100);
  assert.equal(await page.locator('[data-projection]').count(),0,`${name}: a zero-size slot must not construct a map`);
  await hidden.evaluate(el=>el.remove());
  await page.waitForFunction(()=>document.querySelector('[data-projection="globe"]'),{},{timeout:30000});
  await page.getByRole('heading',{name:'On screen',exact:true}).waitFor();
  const state=()=>page.locator('[data-projection]').evaluate(el=>({projection:el.dataset.projection,zoom:Number(el.dataset.zoom),width:el.clientWidth,height:el.clientHeight}));
  const initial=await state();assert.equal(initial.projection,'globe');assert.ok(initial.width>300&&initial.height>300);
  assert.ok(initial.zoom>=1.2&&initial.zoom<=1.9,`${name}: hidden-load landing must show a useful, unclipped sphere, got ${initial.zoom}`);
  // The same transient zero-area condition occurs in responsive/full-page capture.
  const collapsed=await page.addStyleTag({content:'.globe-slot {display:none !important}'});await page.waitForTimeout(150);await collapsed.evaluate(el=>el.remove());await page.waitForTimeout(300);
  const restored=await state();assert.ok(Math.abs(restored.zoom-initial.zoom)<0.05,`${name}: hidden/visible resize corrupted zoom ${initial.zoom} -> ${restored.zoom}`);
  await page.screenshot({path:`${output}/${name}.png`,fullPage:!mobile});await page.waitForTimeout(250);
  assert.ok(Math.abs((await state()).zoom-initial.zoom)<0.05,`${name}: capture resize corrupted zoom`);
  if (!mobile) {
    await page.setViewportSize({width:390,height:844});
    await page.waitForFunction(()=>document.querySelector('[data-projection]')?.clientWidth <= 390);
    await page.waitForFunction(()=>Number(document.querySelector('[data-projection]')?.getAttribute('data-zoom')) <= 1.5,{},{timeout:3000});
    assert.ok((await state()).zoom <= 1.5,`${name}: untouched landing must cap zoom on mobile resize`);
    await page.setViewportSize({width:1440,height:1100});
  }
  const ids=await page.locator('[data-posting-id]').evaluateAll(rows=>rows.map(row=>row.dataset.postingId));
  const point=payload.points.find(point=>ids.includes(point.posting_id));assert.ok(point);
  await page.locator(`[data-posting-id="${point.posting_id}"] > button`).click();await page.waitForTimeout(1500);
  assert.equal(await page.locator('[data-globe-posting]').getAttribute('data-globe-posting'),point.posting_id);
  const selected=await state();assert.equal(selected.projection,'globe');assert.ok(Number.isFinite(selected.zoom)&&selected.zoom>=1.2&&selected.zoom<=1.9);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);
  receipts.push({name,initial,restored,selected,postings:payload.jobs.length,mapped:payload.points.length,errors});
 }catch(error){await page.screenshot({path:`${output}/${name}-failure.png`,fullPage:false});throw error;}finally{await context.close();}
 }}finally{await browser.close();await writeFile(`${output}/camera-receipt.json`,JSON.stringify(receipts,null,2));}
console.log(JSON.stringify(receipts));
