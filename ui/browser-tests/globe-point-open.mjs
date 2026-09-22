// Isolated synthetic boundary regression: never use an owner session or hosted writes.
import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.GLOBE_QA_URL??'http://127.0.0.1:4325',output=process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname,'127.0.0.1');assert.ok(output);await mkdir(output,{recursive:true});
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const job={id:id(0),title:'Exact alternate engineer',company:'Point fixture',source:'fixture',last_seen_at:'2026-09-22',experience:null,description_available:true,seniority_origin:'unknown',extraction_state:'not-extracted',location:'New York, United States',remote:true,seniority:null,stack:[],salary:null,url:'https://example.test',apply_url:null,posted_at:null,first_seen_at:'2026-09-22',status:'new',status_reason:null,score:80,fit_line:null,recommendation:null,alive:true};
const jobs=[job,{...job,id:id(1),first_seen_at:'2026-09-21',location:'Rehovot, Israel'}];
const points=[[40.7128,-74.006],[31.8928,34.8113]].map(([lat,lng],n)=>({posting_id:id(n),lat,lng,precision:'city',source:'Synthetic regression',resolved_at:'2026-09-22T00:00:00Z'}));
const payload={jobs,points,total_count:2,resolved_count:2,unresolved_count:0,attribution:'© OpenStreetMap contributors'};
const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const receipts=[];
try{for(const mobile of [false,true]){
 const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1100},reducedMotion:'reduce'});
 const page=await context.newPage(),requests=[],errors=[];page.setDefaultTimeout(10000);
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('job-radar.board-preferences',JSON.stringify({version:3,filter:'all',view:{search:'',source:'',location:'',seniority:'',fit:'',statuses:[],availability:'all',sort:'fit'}})));
 await page.route('**/*',route=>{const req=route.request(),url=new URL(req.url());
  if(url.hostname!=='127.0.0.1')return url.hostname.endsWith('.cartocdn.com')?route.continue():route.abort();
  if(!url.pathname.startsWith('/api/'))return route.continue();
  requests.push({method:req.method(),path:url.pathname});
  if(url.pathname==='/api/jobs/globe')return route.fulfill({json:payload});
  if(url.pathname==='/api/jobs')return route.fulfill({json:{jobs}});
  if(url.pathname==='/api/events')return route.fulfill({contentType:'text/event-stream',body:'event: ready\ndata: {}\n\n'});
  if(url.pathname.endsWith('/status'))return route.fulfill({json:{status:'seen',reason:null}});
  const selected=jobs.find(j=>url.pathname===`/api/jobs/${j.id}`);
  if(selected)return route.fulfill({json:{job:{...selected,raw_jd:`Fixture body ${selected.id}`,reasons:[],score_payload:null,brain:null,scored_at:null}}});
  return route.fulfill({status:404,json:{error:'Fixture boundary'}});
 });
 const name=mobile?'mobile':'desktop';
 try{
  await page.goto(base);await page.getByRole('button',{name:'Globe',exact:true}).click();
  await page.getByText('Drag to explore',{exact:false}).waitFor({timeout:30000});await page.waitForTimeout(700);
  await page.locator('.job-globe').scrollIntoViewIfNeeded();await page.screenshot({path:`${output}/${name}-before.png`,fullPage:!mobile});
  const canvas=await page.locator('.maplibregl-canvas').boundingBox();await page.mouse.click(canvas.x+canvas.width/2,canvas.y+canvas.height/2);
  const drawer=page.getByRole('dialog');await drawer.waitFor();
  await drawer.getByText(`Fixture body ${id(1)}`,{exact:true}).waitFor();
  assert.equal(await page.locator('[data-globe-selected="true"] [data-posting-id]').getAttribute('data-posting-id'),id(0),'alternate point keeps representative rail row');
  assert.ok(requests.some(r=>r.path===`/api/jobs/${id(1)}`),'detail read uses exact alternate ID');
  assert.equal(requests.filter(r=>r.method!=='GET').length,0,'Point open cannot mark seen');
  await page.screenshot({path:`${output}/${name}-after.png`,fullPage:!mobile});
  await drawer.getByText('Other listings for this role (1)',{exact:true}).click();
  await drawer.getByRole('button',{name:`Open Exact alternate engineer at Point fixture, listing ${id(0)}`,exact:true}).click();
  await drawer.getByText(`Fixture body ${id(0)}`,{exact:true}).waitFor();
  assert.equal(requests.filter(r=>r.method!=='GET').length,0,'Related listing preserves read-only opening');
  await drawer.getByRole('button',{name:'Close',exact:true}).click();await drawer.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'Globe',exact:true}).click();await page.getByRole('button',{name:'Open Exact alternate engineer at Point fixture',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[role="dialog"]'));
  await page.waitForTimeout(400);assert.ok(requests.some(r=>r.method==='PATCH'),'ordinary list open retains existing seen behavior');
  assert.deepEqual(errors,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  receipts.push({name,requests,errors});
 }catch(error){await page.screenshot({path:`${output}/${name}-failure.png`,fullPage:!mobile});throw error;}finally{await context.close();}
}}finally{await browser.close();await writeFile(`${output}/point-open-receipt.json`,JSON.stringify(receipts,null,2));}
console.log(JSON.stringify(receipts));
