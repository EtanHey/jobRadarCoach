import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient } from '@supabase/supabase-js';
import { GlobeJobSchema } from '../lib/globe-contract';
import { defaultBoardPreferences } from '../lib/job-board-preferences';
import { getNewRolesStore } from '../lib/new-roles-server';
import { makePostNewRoles } from '../app/api/jobs/new-roles/route';
const id = '00000000-0000-4000-8000-000000000001';
const row = {id,title:'Engineer',company:'Synthetic',source:'fixture',location:null,remote:null,seniority:null,stack:[],url:'https://example.test',apply_url:null,posted_at:null,first_seen_at:'2026-10-07T00:00:00Z',status:'new',status_reason:null,score:90,recommendation:'apply',alive:true};
test('globe projection retains filter identity but drops card/detail fields', () => {
  const full = {...row,fit_line:'large card text',salary:'unused',experience:'unused',last_seen_at:'unused',description_available:true,seniority_origin:'title',extraction_state:'extracted'};
  const slim = GlobeJobSchema.parse(full);
  assert.ok(!('fit_line' in slim)); assert.ok(!('salary' in slim)); assert.equal(slim.title,row.title);
});
test('poll returns count only and uses narrow SQL snapshot with view and loaded ids', async () => {
  let body: unknown;
  const db = createClient('https://database.example.test','synthetic',{global:{fetch: async (_url,init) => {
    body=JSON.parse(String(init?.body));
    return Response.json({current:[],incoming:[row]});
  }}});
  const handler=makePostNewRoles(getNewRolesStore(db));
  const requestBody={filter:'all',availability:'inactive',since:'2026-10-06T00:00:00.123456Z',found_within:'24h',ids:[id],view:defaultBoardPreferences().view};
  const response=await handler(new Request('https://example.test/api/jobs/new-roles',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(requestBody)}));
  assert.equal(response.status,200); assert.deepEqual(await response.json(),{count:1,truncated:false});
  assert.match(response.headers.get('cache-control') ?? '',/no-store/);
  assert.deepEqual(body,{filter:'all',availability:'inactive',since:requestBody.since,found_within:'24h',ids:[id]});
  assert.equal((await handler(new Request('https://example.test/api/jobs/new-roles',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...requestBody,found_within:'2d'})}))).status,400);
});
