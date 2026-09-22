// Headless synthetic geography tests; all data/network writes stay in loopback fixtures.
import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
const base=process.env.GLOBE_QA_URL??'http://127.0.0.1:4325',output=process.env.GLOBE_QA_OUTPUT;
assert.equal(new URL(base).hostname,'127.0.0.1');assert.ok(output);await mkdir(output,{recursive:true});
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const titles=['Here','Far side','Berlin','New York','Unresolved','Unavailable','Duplicate','Duplicate'];
const jobs=titles.map((title,n)=>({id:id(n),title,company:title,source:'fixture',last_seen_at:'2026-09-22',experience:null,description_available:false,seniority_origin:'unknown',extraction_state:'not-extracted',location:title,remote:n%2===0,seniority:null,stack:[],salary:null,url:'https://example.test',apply_url:null,posted_at:null,first_seen_at:n===7?'2026-09-21':'2026-09-22',status:'new',status_reason:null,score:90-n,fit_line:null,recommendation:null,alive:n!==5}));
jobs[5].company = 'LongCompanyName'.repeat(40); // Long real-cohort labels must not set implicit grid width.
const coords=[[31.8928,34.8113],[-31.8928,-145.1887],[52.52,13.405],[40.7128,-74.006],null,[31.8928,34.8113],[-31.8928,-145.1887],[31.8928,34.8113]];
const points=coords.flatMap((coord,n)=>coord?[{posting_id:id(n),lat:coord[0],lng:coord[1],precision:'city',source:'Synthetic viewport regression',resolved_at:'2026-09-22T00:00:00Z'}]:[]);
const payload={jobs,points,total_count:8,resolved_count:7,unresolved_count:1,attribution:'© OpenStreetMap contributors'};
const browser=await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const receipts=[];
try{for(const mobile of [false,true]){
 const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1100},reducedMotion:'reduce'});
 const page=await context.newPage(),errors=[],requests=[];page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.EventSource=class {addEventListener(type,callback){if(type==='refresh')window.emitGlobeRefresh=callback;}close(){}};});
 await page.addInitScript(()=>localStorage.setItem('job-radar.board-preferences',JSON.stringify({version:3,filter:'all',view:{search:'',source:'',location:'',seniority:'',fit:'',statuses:[],availability:'all',sort:'fit'}})));
 await page.route('**/*',async route=>{const r=route.request(),u=new URL(r.url());if(u.hostname!=='127.0.0.1')return u.hostname.endsWith('.cartocdn.com')?route.continue():route.abort();if(!u.pathname.startsWith('/api/'))return route.continue();requests.push({method:r.method(),path:u.pathname,query:u.search});if(u.pathname==='/api/jobs/globe'){await new Promise(resolve=>setTimeout(resolve,500));return route.fulfill({json:payload});}if(u.pathname==='/api/jobs')return route.fulfill({json:{jobs}});if(u.pathname==='/api/events')return route.fulfill({contentType:'text/event-stream',body:'event: ready\ndata: {}\n\n'});return route.fulfill({status:404,json:{error:'Fixture boundary'}});});
 const section=kind=>page.locator(`[data-globe-section="${kind}"] [data-posting-id]`);
 const ids=kind=>section(kind).evaluateAll(rows=>rows.map(r=>r.dataset.postingId));
 const parity=async expected=>{const on=await ids('visible'),off=await ids('outside');assert.deepEqual([...on,...off].sort(),expected);assert.deepEqual(on,[...on].sort());assert.deepEqual(off,[...off].sort());assert.ok(!on.includes(id(4))&&!on.includes(id(5)),'unresolved/unavailable stay outside');return {on,off};};
 const name=mobile?'mobile':'desktop';
 try{
  await page.goto(base);await page.getByRole('button',{name:'Globe',exact:true}).click();
  await page.getByText('Loading all posting locations…').waitFor();
  assert.equal(await page.getByText('No roles in this part of the globe. Pan or zoom to explore.').count(),0);
  assert.equal(await page.getByRole('heading',{name:'Outside of screen',exact:true}).count(),0,'do not render an outside-only partition before geography arrives');
  await page.getByText('Drag to explore',{exact:false}).waitFor({timeout:30000});
  await page.getByRole('heading',{name:'Outside of screen',exact:true}).waitFor();await page.waitForTimeout(600);
  const initial=await parity(Array.from({length:7},(_,n)=>id(n)));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'long labels cannot widen viewport sections');assert.ok(initial.on.includes(id(0))&&initial.on.includes(id(6)));assert.ok(initial.off.includes(id(1)),'back-facing point must not count as visible');
  assert.equal(await page.getByText('2 roles not on globe',{exact:true}).count(),1);assert.equal(await page.getByText('5 roles mapped',{exact:true}).count(),1);
  assert.equal(Number((await page.locator('#globe-visible-heading + span').textContent()).match(/\d+/)[0])+Number((await page.locator('#globe-outside-heading + span').textContent()).match(/\d+/)[0]),7);
  await page.locator('.job-globe').scrollIntoViewIfNeeded();await page.screenshot({path:`${output}/${name}-initial.png`,fullPage:true});
  await page.locator(`[data-posting-id="${id(0)}"] > button`).click();await page.waitForTimeout(350);
  for(let i=0;i<4;i++){await page.getByRole('button',{name:'Zoom in',exact:true}).click({force:true});await page.waitForTimeout(350);}
  await page.waitForTimeout(350);
  const zoomBeforeRefresh=Number(await page.locator('[data-projection]').getAttribute('data-zoom'));
  const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/jobs/globe');
  await page.evaluate(()=>window.emitGlobeRefresh());await refreshed;await page.locator('[data-globe-section="outside"]').waitFor();
  assert.ok(Math.abs(Number(await page.locator('[data-projection]').getAttribute('data-zoom'))-zoomBeforeRefresh)<0.02,'unchanged point refresh preserves user zoom');
  const zoomed=await parity(Array.from({length:7},(_,n)=>id(n)));assert.ok(zoomed.off.includes(id(2)),'front-face point outside actual canvas bounds goes below');
  await page.screenshot({path:`${output}/${name}-zoomed.png`,fullPage:true});
  for(let i=0;i<4;i++){await page.getByRole('button',{name:'Zoom out',exact:true}).click({force:true});await page.waitForTimeout(350);}
  const box=await page.locator('.job-globe').boundingBox();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.5);await page.mouse.down();await page.mouse.move(box.x+box.width*.15,box.y+box.height*.5,{steps:30});await page.mouse.up();await page.waitForTimeout(2200);
  const panned=await parity(Array.from({length:7},(_,n)=>id(n)));assert.notDeepEqual(panned.on,initial.on,'pan updates the viewport partition');
  await page.screenshot({path:`${output}/${name}-panned.png`,fullPage:true});
  await page.getByPlaceholder('Search title, company, or stack').fill('Duplicate');await page.locator('[data-globe-section="outside"]').waitFor();const filtered=await parity([id(6)]);await page.getByText('1 role mapped',{exact:true}).waitFor();await page.getByText('0 roles not on globe',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);assert.ok(requests.every(r=>r.method==='GET'));assert.ok(requests.filter(r=>r.path.endsWith('/globe')).every(r=>!r.query.includes('limit')));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  receipts.push({name,initial,zoomed,panned,filtered,requests,errors});
 }catch(error){await page.screenshot({path:`${output}/${name}-failure.png`,fullPage:true});throw error;}finally{await context.close();}
}}finally{await browser.close();await writeFile(`${output}/viewport-receipt.json`,JSON.stringify(receipts,null,2));}
console.log(JSON.stringify(receipts));
