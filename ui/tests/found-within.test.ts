import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient } from '@supabase/supabase-js';
import { makeGetJobs } from '../app/api/jobs/route';
import { selectSummaries, type ApiStore } from '../lib/server';
import { defaultBoardPreferences, readBoardPreferences, writeBoardPreferences, isDefaultBoardPreferences } from '../lib/job-board-preferences';
import { jobListRequestPath } from '../lib/job-board-state';
import { newRolesRequestPath } from '../lib/new-roles';
import { filterJobGroups } from '../lib/job-filters';
import type { JobSummary } from '../lib/contracts';

test('found window persists, validates, and older preferences keep their settings', () => {
  let raw: string | null = null;
  const storage = {getItem:()=>raw,setItem:(_k:string,v:string)=>{raw=v;},removeItem:()=>{raw=null;}};
  for (const found_within of ['24h','3d','7d','30d'] as const) {
    const selected = {...defaultBoardPreferences(),view:{...defaultBoardPreferences().view, found_within}};
    writeBoardPreferences(storage,selected);
    assert.deepEqual(readBoardPreferences(storage),selected);
    assert.equal(isDefaultBoardPreferences(selected),false);
  }
  raw=JSON.stringify({version:3,filter:'all',view:{...defaultBoardPreferences().view,location:'israel'}});
  assert.equal(readBoardPreferences(storage).view.location,'israel');
  raw=JSON.stringify({version:3,filter:'all',view:{...defaultBoardPreferences().view,found_within:'2d'}});
  assert.deepEqual(readBoardPreferences(storage),defaultBoardPreferences());
});

test('board and poll requests carry the found window', () => {
  assert.match(jobListRequestPath({filter:'all',availability:'all',limit:1000,found_within:'7d'}),/found_within=7d/);
  assert.match(newRolesRequestPath({filter:'all',availability:'all',since:'2026-10-01T00:00:00Z',found_within:'24h'}),/found_within=24h/);
});

test('board RPC and poll predicate both receive a validated window', async () => {
  const calls: {url:string;body:unknown}[]=[];
  const db=createClient('https://database.example.test','synthetic',{global:{fetch:async(url,init)=>{
    calls.push({url:String(url),body:init?.body?JSON.parse(String(init.body)):null});
    return Response.json([]);
  }}});
  const handler=makeGetJobs({listJobs:input=>selectSummaries(db,input)} as ApiStore);
  assert.equal((await handler(new Request('https://example.test/api/jobs?filter=all&found_within=7d&sort=fit'))).status,200);
  assert.equal((calls[0].body as Record<string,unknown>).found_within,'7d');
  const before=Date.now();
  assert.equal((await handler(new Request('https://example.test/api/jobs?filter=all&found_within=24h&since=1970-01-01T00:00:00Z'))).status,200);
  const predicates=new URL(calls[1].url).searchParams.getAll('first_seen_at');
  assert.ok(predicates.some(v=>v.startsWith('gt.1970')));
  const cutoff=predicates.find(v=>v.startsWith('gte.'));
  assert.ok(cutoff);
  assert.ok(Date.parse(cutoff.slice(4))>=before-86400000 && Date.parse(cutoff.slice(4))<=Date.now()-86400000);
  assert.equal((await handler(new Request('https://example.test/api/jobs?found_within=2d'))).status,400);
});

test('shared list/globe filtering excludes expired retained rows and keeps the inclusive boundary', () => {
  const now=Date.now();
  const row={id:'fixture',title:'Engineer',company:'Example',source:'fixture',location:null,stack:[],status:'new',score:90,recommendation:'apply',posted_at:null,last_seen_at:new Date(now).toISOString(),first_seen_at:new Date(now).toISOString(),experience:null,description_available:false,seniority_origin:'unknown',extraction_state:'not-extracted',remote:null,seniority:null,salary:null,url:'https://example.test',apply_url:null,status_reason:null,fit_line:null,alive:true} satisfies JobSummary;
  const rows=[{...row,id:'old',company:'Old example',first_seen_at:new Date(now-86400001).toISOString()},{...row,id:'edge',first_seen_at:new Date(now-86400000).toISOString()}];
  const original=Date.now;Date.now=()=>now;
  try {assert.deepEqual(filterJobGroups(rows,{...defaultBoardPreferences().view,found_within:'24h'}).map(g=>g.job.id),['edge']);}
  finally {Date.now=original;}
});
