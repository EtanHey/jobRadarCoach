// Real isolated JobBoard, synthetic APIs, no account access. Run via the suite cap.
import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, open } from 'node:fs/promises';
const output=process.env.GLOBE_QA_OUTPUT;
assert.ok(output);
await mkdir(output,{recursive:true});
const log=await open(`${output}/server.log`,'w');
const server=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','--webpack','--port','4491'],{cwd:`${output}/fixture-app`,stdio:['ignore',log.fd,log.fd],env:{...process.env,NODE_OPTIONS:'--max-old-space-size=1024'}});
const base='http://127.0.0.1:4491';
let browser;
const job=(n,overrides={})=>({id:`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,title:n===1?'Frontend Engineer':'Principal Engineer',company:`Synthetic ${n}`,source:'fixture',last_seen_at:'2026-10-07T08:00:00Z',first_seen_at:'2026-10-07T08:00:00Z',experience:null,description_available:true,seniority_origin:'title',extraction_state:'not-extracted',location:'Tel Aviv, Israel',remote:true,seniority:n===1?'Junior':'Staff',stack:['React'],salary:null,url:'https://example.test',apply_url:null,posted_at:null,status:'new',status_reason:null,score:n===1?80:null,fit_line:null,recommendation:n===1?'apply':null,alive:true,relevance_filtered:n===2,relevance_rule:n===2?'leadership-title-strict':null,...overrides});
try {
  for(let i=0;i<120;i++){assert.equal(server.exitCode,null,'fixture server exited');try {const r=await fetch(base);if(r.ok)break;}catch{} if(i===119)throw Error('fixture server not ready');await new Promise(r=>setTimeout(r,500));}
  browser=await chromium.launch({headless:true});
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
    const context=await browser.newContext({viewport,reducedMotion:'reduce',colorScheme:viewport.width===390?'dark':'light'});
    const page=await context.newPage();const errors=[];let rescued=false,attempts=0,seen=0;
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/**',route=>{
      const req=route.request(),url=new URL(req.url());
      const archived=job(2,{relevance_filtered:!rescued});
      if(url.pathname.endsWith('/score-anyway')){attempts++;if(attempts===1)return route.fulfill({status:503,json:{error:'Synthetic retry needed.'}});rescued=true;return route.fulfill({json:{...archived,relevance_filtered:false,raw_jd:'Synthetic description',reasons:[],score_payload:null,brain:null,scored_at:null}});}
      if(url.pathname.endsWith('/status')){seen++;return route.fulfill({json:{status:'seen',reason:null}});}
      if(url.pathname==='/api/jobs'){const filter=url.searchParams.get('filter');return route.fulfill({json:{jobs:filter==='not-scored'?(rescued?[]:[archived]):[job(1),...(rescued?[archived]:[])]}});}
      if(url.pathname===`/api/jobs/${archived.id}`)return route.fulfill({json:{...archived,raw_jd:'Synthetic description',reasons:[],score_payload:null,brain:null,scored_at:null}});
      return route.fulfill({status:404,json:{error:'fixture only'}});
    });
    await page.goto(base);
    for(const tab of ['All roles','Seen','New for me']){await page.getByRole('button',{name:tab,exact:true}).click();await expect(page.locator(`article[data-posting-id="${job(2).id}"]`)).toHaveCount(0);}
    await page.getByRole('button',{name:'Not scored',exact:true}).click();
    await expect(page.locator('article')).toHaveCount(1);
    await expect(page.getByText('Not scored (filtered)',{exact:true})).toBeVisible();
    await expect(page.getByText('Leadership or staff-level role',{exact:true})).toBeVisible();
    await page.screenshot({path:`${output}/${viewport.width}-archive.png`});
    await page.getByRole('button',{name:'Open Principal Engineer at Synthetic 2'}).click();
    await page.getByRole('button',{name:'Score anyway',exact:true}).click();
    await expect(page.getByText('Synthetic retry needed.',{exact:true})).toBeVisible();
    assert.equal(rescued,false);assert.equal(seen,0,'archive open must not mark Seen');
    await page.getByRole('button',{name:'Score anyway',exact:true}).click();
    await expect(page.getByRole('status').filter({hasText:'Queued for scoring'})).toBeVisible();
    await expect(page.locator('article')).toHaveCount(0);
    await page.screenshot({path:`${output}/${viewport.width}-queued.png`});
    assert.deepEqual(errors,[]);assert.equal(attempts,2);
    console.log(`PASS ${viewport.width}: archive-only / reason / failed-save preserved / retry / override`);
    await context.close();
  }
} finally {await browser?.close();server.kill('SIGTERM');await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));await log.close();}
