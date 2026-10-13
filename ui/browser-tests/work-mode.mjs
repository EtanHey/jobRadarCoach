// Synthetic APIs against the real JobBoard; run via run-suite-capped.sh.
import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const base = process.env.GLOBE_QA_URL;
assert.equal(new URL(base).hostname, '127.0.0.1');
const output = process.env.GLOBE_QA_OUTPUT;
await mkdir(output, {recursive:true});
const jobs = ['hybrid','remote','on-site',null].map((work_mode,n)=>({
 id:`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`, title:`Mode role ${n}`,
 company:`Fixture ${n}`, source:'fixture', location:'Tel Aviv, Israel', work_mode,
 remote:work_mode==='remote'?true:work_mode==='on-site'?false:null,
 last_seen_at:'2026-10-05T00:00:00Z',first_seen_at:'2026-10-05T00:00:00Z',
 experience:null,description_available:false,seniority_origin:'unknown',extraction_state:'not-extracted',
 seniority:null,stack:[],salary:null,url:'https://example.test',apply_url:null,posted_at:null,
 status:'new',status_reason:null,score:80,fit_line:null,recommendation:'apply',alive:true,
}));
const browser=await chromium.launch({headless:true});
try {
 for(const width of [1440,390]) {
  const context=await browser.newContext({viewport:{width,height:900},colorScheme:'dark'});
  try {
   await context.addInitScript(()=>{
    if(!localStorage.getItem('job-radar.board-preferences'))localStorage.setItem('job-radar.board-preferences',JSON.stringify({version:3,filter:'all',view:{search:'',source:'',location:'',seniority:'',fit:'',statuses:[],availability:'active',sort:'fit'}}));
    window.EventSource=class extends EventTarget {close(){this.closed=true;}};
   });
   const page=await context.newPage(); const errors=[];
   page.on('pageerror',error=>errors.push(error.message));
   await page.route('**/api/**',route=>route.fulfill({json:{jobs}}));
   await page.goto(base);
   await expect(page.locator('article[data-posting-id]')).toHaveCount(4);
   if(width===390)await page.getByRole('button',{name:/^Filters/}).click();
   const select=page.getByRole('combobox',{name:'Work mode',exact:true}).filter({visible:true});
   for(const [label,n] of [['Hybrid',0],['Remote',1],['On-site',2]]){
    await select.click();await page.getByRole('option',{name:label,exact:true}).click();
    await expect(page.locator('article[data-posting-id]')).toHaveCount(1);
    await expect(page.locator('article[data-posting-id]')).toHaveAttribute('data-posting-id',jobs[n].id);
   }
   await select.click(); await page.getByRole('option',{name:'Hybrid',exact:true}).click();
   if(width===390){
    const show=page.getByRole('button',{name:'Show roles',exact:true});
    await show.click();await expect(show).toBeHidden();
   }
   await page.screenshot({path:`${output}/hybrid-${width}.png`});
   await page.reload();await expect(page.locator('article[data-posting-id]')).toHaveCount(1);
   assert.deepEqual(errors,[]);
   console.log(`PASS ${width}: Hybrid/Remote/On-site distinct; unknown excluded; saved Hybrid restored`);
  } finally {await context.close();}
 }
} finally {await browser.close();}
