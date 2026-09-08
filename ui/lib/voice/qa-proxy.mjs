import http from 'node:http';
import https from 'node:https';
import crypto from 'node:crypto';
import { AccessToken, TrackSource } from 'livekit-server-sdk';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));

function parseOrigin(value, browserFacing = false) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password
    || url.pathname !== '/' || url.search || url.hash
    || (browserFacing && url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('Invalid QA origin');
  }
  return url.origin;
}

// verifyAgent is supplied by the runner after checking the real coach-owned receipt.
// A browser flag or this process's environment cannot attest an agent's read-only mode.
export async function startQaProxy({ upstream, key, secret, serverUrl, qaSessionId,
  verifyAgent = async () => false, upstreamOrigin, publicOrigin, port = 0 }) {
  const targetOrigin = new URL(parseOrigin(upstream));
  const logicalOrigin = new URL(parseOrigin(upstreamOrigin ?? upstream));
  const browserOrigin = publicOrigin === undefined ? undefined : parseOrigin(publicOrigin, true);
  const signal = new URL(serverUrl);
  if (!UUID.test(qaSessionId) || !key || !secret || !['http:', 'https:'].includes(targetOrigin.protocol)
    || signal.protocol !== 'wss:' || signal.username || signal.password || signal.search || signal.hash) {
    throw new Error('Invalid QA runtime configuration');
  }
  let revoked = false;
  let origin;
  let mutationAttempts = 0;
  let micCalls = 0;
  const streams = new Set();
  const requests = new Set();
  const rooms = [];
  let mic = { client_id: null, revision: '0', updated_at: new Date().toISOString() };
  const qaReady = async () => {
    if (revoked) return false;
    try { return await verifyAgent() === true && !revoked; } catch { return false; }
  };
  const attestation = () => ({ version: 1, session_id: qaSessionId, read_only: true });
  const frame = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
  const json = (res, status, value) => {
    res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(value));
  };
  const body = async req => {
    let text = '';
    for await (const chunk of req) {
      text += chunk;
      if (Buffer.byteLength(text) > 4096) throw new Error('Invalid request');
    }
    return JSON.parse(text);
  };
  const closeStreams = () => { for (const stream of streams) stream.end(); streams.clear(); };
  const server = http.createServer(async (req, res) => {
    try {
      const path = decodeURIComponent(new URL(req.url, 'http://qa.invalid').pathname);
      const voicePost = req.method === 'POST' && ['/api/livekit/mic', '/api/livekit/token'].includes(path);
      if (req.method !== 'GET' && !voicePost) {
        mutationAttempts++; revoked = true; closeStreams();
        return json(res, 403, { error: 'QA forbids upstream mutations' });
      }
      if (voicePost && req.headers.origin !== (browserOrigin ?? origin)) return json(res, 403, { error: 'Invalid origin' });
      if (path === '/api/livekit/qa') {
        if (!await qaReady()) return json(res, 503, { error: 'QA agent is not verified' });
        return json(res, 200, { version: 1, qa_mode: true, session_id: qaSessionId,
          browser_mutations_blocked: true, mic_isolated: true, agent_qa_verified: true, dispatch_mode: 'automatic' });
      }
      if (path === '/api/livekit/events') {
        if (!await qaReady()) return json(res, 503, { error: 'QA agent is not verified' });
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
        streams.add(res); res.write(frame('ownership', mic) + frame('ready', {}));
        req.on('close', () => streams.delete(res)); return;
      }
      if (path === '/api/livekit/mic') {
        if (req.method === 'POST') {
          if (!await qaReady()) return json(res, 503, { error: 'QA agent is not verified' });
          const input = await body(req);
          if (!exact(input, ['action', 'client_id']) || !UUID.test(input.client_id)
            || !['claim', 'release'].includes(input.action)) return json(res, 400, { error: 'Invalid request' });
          if (!await qaReady()) return json(res, 503, { error: 'QA readiness changed' });
          micCalls++;
          if (input.action === 'claim' || mic.client_id === input.client_id) {
            mic = { client_id: input.action === 'claim' ? input.client_id : null,
              revision: String(BigInt(mic.revision) + 1n), updated_at: new Date().toISOString() };
            for (const stream of streams) stream.write(frame('ownership', mic));
          }
        }
        return json(res, 200, { mic });
      }
      if (path === '/api/livekit/token') {
        if (!voicePost) return json(res, 405, { error: 'POST required' });
        if (req.headers['x-voice-qa-session'] !== qaSessionId || !await qaReady()) {
          return json(res, 503, { error: 'QA session is not verified' });
        }
        const input = await body(req);
        if (!exact(input, ['client_id']) || !UUID.test(input.client_id)) return json(res, 400, { error: 'Invalid request' });
        if (rooms.length >= 1000) return json(res, 503, { error: 'Start a fresh QA run' });
        const room_name = 'qa-voice-' + crypto.randomUUID();
        const participant_identity = `web:${input.client_id}:${crypto.randomUUID()}`;
        const token = new AccessToken(key, secret, { identity: participant_identity, ttl: 300,
          metadata: JSON.stringify({ qa: attestation() }) });
        token.addGrant({ room: room_name, roomJoin: true, canPublish: true, canSubscribe: true,
          canPublishData: true, canPublishSources: [TrackSource.MICROPHONE], canUpdateOwnMetadata: false });
        const jwt = await token.toJwt();
        if (!await qaReady()) return json(res, 503, { error: 'QA readiness changed' });
        rooms.push({ room_name, participant_identity, client_id: input.client_id, dispatch_mode: 'automatic' });
        return json(res, 200, { server_url: serverUrl, token: jwt, room_name, participant_identity,
          dispatch_mode: 'automatic', qa: attestation() });
      }
      // Relative targets only; unrecognized voice endpoints cannot reach a borrowed runtime.
      if (path.startsWith('/api/livekit/')) return json(res, 404, { error: 'Unknown QA endpoint' });
      const target = new URL(targetOrigin.origin + req.url);
      const transport = target.protocol === 'https:' ? https : http;
      const forward = transport.request(target, { method: 'GET', headers: { ...req.headers, host: logicalOrigin.host, origin: logicalOrigin.origin } }, response => {
        res.writeHead(response.statusCode, response.headers); response.pipe(res);
      });
      requests.add(forward);
      forward.on('close', () => requests.delete(forward));
      res.on('close', () => forward.destroy());
      forward.on('error', () => { if (!res.headersSent) json(res, 502, { error: 'QA upstream unavailable' }); else res.destroy(); });
      forward.end();
    } catch { if (!res.headersSent) json(res, 400, { error: 'Invalid QA request' }); else res.destroy(); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  origin = `http://127.0.0.1:${server.address().port}`;
  const heartbeat = setInterval(() => { for (const stream of streams) stream.write(': heartbeat\n\n'); }, 10000);
  return {
    origin, get rooms() { return rooms.map(room => ({ ...room })); }, qaUrl: `${browserOrigin ?? origin}/mic?qa=${qaSessionId}`,
    receipt: () => ({ session_id: qaSessionId, rooms: rooms.map(room => ({ ...room })),
      isolatedMicCalls: micCalls, ownerMicCalls: 0, mutationAttempts, revoked }),
    invalidateQa: () => { revoked = true; closeStreams(); },
    close: async () => { revoked = true; clearInterval(heartbeat); closeStreams();
      for (const request of requests) request.destroy();
      server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); },
  };
}
