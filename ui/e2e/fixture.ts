import type { Browser } from '@e2e-dev/web';
export const role = { id: '00000000-0000-4000-8000-000000000001', title: 'Pilot engineer', company: 'Synthetic Labs',
  source: 'fixture', last_seen_at: '2026-10-04T00:00:00Z', first_seen_at: '2026-10-04T00:00:00Z',
  posted_at: '2026-09-01T00:00:00Z', last_published_at: '2026-10-03T00:00:00Z', experience: null,
  description_available: true, seniority_origin: 'title', extraction_state: 'not-extracted', location: 'Rehovot, Israel',
  remote: true, seniority: 'Junior', stack: ['React'], salary: null, url: 'https://example.test',
  apply_url: null, status: 'new', status_reason: null, score: 85, fit_line: null, recommendation: 'apply', alive: true };
export async function installFixture(browser: { addInitScript(script: string): Promise<unknown>; route: Browser['route'] }, base: string | undefined) {
  if (!base || new URL(base).hostname !== '127.0.0.1') throw new Error('Synthetic loopback origin required');
  const origin = new URL(base).origin;
  const state = { patches: 0, listReads: 0, pollReads: 0, addRole: false };
  let status = role.status;
  await browser.addInitScript(`window.EventSource = class { listeners = new Map(); constructor(){ window.fixtureEvents = this; } addEventListener(n,f){this.listeners.set(n,f)} close(){this.listeners.clear()} };`);
  await browser.route('**/*', async route => {
    const url = new URL(route.request.url);
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname === '/api/jobs/sources') return route.fulfill({ json: { sources: [role.source] } });
    if (url.pathname === '/api/jobs') {
      const since = url.searchParams.get('since');
      if (since) state.pollReads++; else state.listReads++;
      let jobs = [{ ...role, status }];
      if (state.addRole) jobs.push({ ...role, id: '00000000-0000-4000-8000-000000000002', title: 'Incoming engineer', first_seen_at: '2026-10-05T00:00:00Z', status: 'new' });
      const query = url.searchParams.get('query') ?? '';
      jobs = jobs.filter(job => (!since || job.first_seen_at > since) && job.title.toLowerCase().includes(query.toLowerCase()));
      return route.fulfill({ json: { jobs } });
    }
    if (url.pathname === `/api/jobs/${role.id}/status` && route.request.method === 'PATCH') {
      state.patches++;
      status = JSON.parse(route.request.postData ?? '{}').status;
      return route.fulfill({ json: { status, reason: null } });
    }
    if (url.pathname === `/api/jobs/${role.id}`) return route.fulfill({ json: { job: { ...role, status,
      raw_jd: 'Synthetic description for the pilot.', reasons: [], score_payload: null, brain: null, scored_at: null } } });
    return route.fulfill({ status: 404, json: { error: 'Synthetic fixture only' } });
  });
  return state;
}

export const modelEnabled = !process.env.CI && Boolean(process.env.JRC_E2E_MODEL_CONFIG);
