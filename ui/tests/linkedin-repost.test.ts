import assert from 'node:assert/strict';
import { test } from 'node:test';
import { repostNote } from '../lib/job-display';
const summary = {url:'https://www.linkedin.com/jobs/view/1234567890'};

test('LinkedIn repost labels require explicit same-posting evidence, regardless of linked dates', () => {
  const job = {...summary, source:'linkedin', posted_at:'2026-09-01T00:00:00Z', last_published_at:'2026-10-01T00:00:00Z'};
  assert.equal(repostNote(job), null);
  const signal = {label:'Reposted 2 weeks ago', url:job.url, checked_at:'2026-10-07T00:00:00Z'};
  assert.equal(repostNote({...job, linkedin_reposted_signal:signal}), signal.label);
  assert.equal(repostNote({...job, linkedin_reposted_signal:{...signal,url:'https://www.linkedin.com/jobs/view/999'}}), null);
  assert.equal(repostNote({...job, linkedin_reposted_signal:signal}, undefined, true), signal.label);
});
