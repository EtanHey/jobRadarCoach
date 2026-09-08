#!/usr/bin/env node
/** Owned QA proxy process. The imported proxy supplies the browser safety boundary. */

import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import { chmod, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const required = name => {
  const value = process.env[name];
  if (!value) throw new Error(`QA NOT READY: ${name.toLowerCase()}_missing`);
  return value;
};
const stableReason = stderr => {
  const match = /^NOT_READY ([a-z0-9_]+)/m.exec(stderr);
  return match?.[1] ?? 'verifier_failed';
};
const atomicJson = async (file, value) => {
  const temporary = `${file}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600 });
  await chmod(temporary, 0o600);
  await rename(temporary, file);
};

async function main() {
  if (process.env.VOICE_QA_MODE !== '1') throw new Error('QA NOT READY: qa_mode_missing');
  const key = required('LIVEKIT_API_KEY');
  const secret = required('LIVEKIT_API_SECRET');
  delete process.env.LIVEKIT_API_KEY;
  delete process.env.LIVEKIT_API_SECRET;
  const sessionId = required('QA_SESSION_ID');
  const expectedWorker = required('QA_EXPECTED_WORKER_ID');
  const verifier = required('QA_VERIFIER_PATH');
  const receiptPath = required('QA_RECEIPT_PATH');
  const expectedServer = required('QA_EXPECTED_LIVEKIT_URL');
  const markerPath = required('QA_RUNTIME_STATE_FILE');
  const modulePath = process.env.QA_PROXY_MODULE
    ?? path.resolve(import.meta.dirname, '../ui/lib/voice/qa-proxy.mjs');
  const intervalMs = Number(process.env.QA_VERIFY_INTERVAL_MS ?? '10000');
  if (!Number.isFinite(intervalMs) || intervalMs < 250) {
    throw new Error('QA NOT READY: verify_interval_invalid');
  }
  let proxy;
  let reason = 'starting';
  let closing = false;
  let revoked = false;
  let timer;
  let receiptTimer;
  let lastReceipt = '';
  let verificationQueue = Promise.resolve();
  let publishQueue = Promise.resolve();
  let proxyStartup = Promise.resolve();
  let closePromise;
  let proxyClosed = false;
  const verifierChildren = new Set();
  const marker = status => ({
    version: 1, status, reason: status === 'READY' ? null : reason,
    session_id: sessionId, worker_id: expectedWorker,
    supervisor_pid: Number(process.env.QA_SUPERVISOR_PID),
    origin: proxy?.origin ?? null, qa_url: proxy?.qaUrl ?? null,
    proxy_receipt: proxy?.receipt() ?? null,
  });
  const publish = status => {
    publishQueue = publishQueue.then(() => {
      const effective = closing && status === 'READY' ? 'STOPPED'
        : revoked && status === 'READY' ? 'NOT_READY' : status;
      return atomicJson(markerPath, marker(effective));
    });
    return publishQueue;
  };
  const runVerifier = () => {
    if (closing || revoked) return Promise.resolve(false);
    return new Promise(resolve => {
    const env = { ...process.env, LIVEKIT_URL: expectedServer, VOICE_QA_MODE: '1' };
    const child = spawn(process.env.QA_PYTHON ?? 'python3', [verifier, receiptPath], {
      detached: true, env, stdio: ['ignore', 'pipe', 'pipe'],
    });
    verifierChildren.add(child);
    let stdout = ''; let stderr = '';
    let settled = false;
    let killTimer;
    const finish = value => {
      if (settled) return;
      settled = true; clearTimeout(timeout); clearTimeout(killTimer);
      verifierChildren.delete(child); resolve(value);
    };
    const terminate = signal => { try { process.kill(-child.pid, signal); } catch {} };
    const timeout = setTimeout(() => {
      reason = 'verifier_timeout'; terminate('SIGTERM');
      killTimer = setTimeout(() => { if (!settled) terminate('SIGKILL'); }, 500);
    }, Number(process.env.QA_VERIFIER_TIMEOUT_MS ?? '20000'));
    child.stdout.on('data', chunk => { if (stdout.length < 4096) stdout += chunk; });
    child.stderr.on('data', chunk => { if (stderr.length < 4096) stderr += chunk; });
    child.on('error', () => { reason = 'verifier_unavailable'; finish(false); });
    child.on('close', code => {
      if (reason === 'verifier_timeout') return finish(false);
      try {
        const value = JSON.parse(stdout);
        const exact = value && Object.keys(value).length === 2
          && value.status === 'READY' && value.worker_id === expectedWorker;
        if (code === 0 && exact) { reason = ''; return finish(true); }
        reason = code === 0 ? 'verifier_output_invalid' : stableReason(stderr);
      } catch { reason = code === 0 ? 'verifier_output_invalid' : stableReason(stderr); }
      finish(false);
    });
    });
  };
  const verify = () => {
    const result = verificationQueue.then(runVerifier, runVerifier);
    verificationQueue = result.then(() => undefined, () => undefined);
    return result;
  };
  const gate = async () => {
    if (revoked || closing) return false;
    const ready = await verify();
    if (!ready || revoked || closing) {
      revoked = true;
      if (proxy) {
        proxy.invalidateQa();
        await publish('NOT_READY');
      }
      return false;
    }
    return true;
  };
  const closeProxy = async () => {
    if (!proxy || proxyClosed) return;
    proxyClosed = true;
    await proxy.close();
  };
  const close = () => {
    if (closePromise) return closePromise;
    closing = true; clearTimeout(timer); clearInterval(receiptTimer);
    for (const child of verifierChildren) { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }
    closePromise = (async () => {
      await verificationQueue;
      try { await proxyStartup; } catch {}
      await closeProxy();
      reason = 'stopped';
      await publish('STOPPED');
    })();
    return closePromise;
  };
  process.on('SIGINT', () => close().finally(() => process.exit(0)));
  process.on('SIGTERM', () => close().finally(() => process.exit(0)));
  if (!await gate()) {
    if (closing) return;
    await publish('NOT_READY');
    throw new Error(`QA NOT READY: ${reason}`);
  }
  try {
    const { startQaProxy } = await import(pathToFileURL(modulePath));
    if (closing) return;
    proxyStartup = startQaProxy({
      upstream: required('QA_UPSTREAM'), upstreamOrigin: required('QA_UPSTREAM_ORIGIN'),
      publicOrigin: process.env.QA_PUBLIC_ORIGIN || undefined,
      port: Number(required('QA_PROXY_PORT')), key, secret,
      serverUrl: required('QA_PUBLIC_LIVEKIT_URL'), qaSessionId: sessionId,
      verifyAgent: gate,
    }).then(created => { proxy = created; return created; });
    await proxyStartup;
  } catch (error) {
    if (closing) return;
    reason = error?.code === 'ERR_MODULE_NOT_FOUND' ? 'proxy_module_unavailable' : 'proxy_start_failed';
    await publish('NOT_READY');
    throw new Error(`QA NOT READY: ${reason}`);
  }
  if (closing) { await close(); return; }
  await publish('READY');
  console.log(`QA proxy ready: ${proxy.qaUrl}`);
  lastReceipt = JSON.stringify(proxy.receipt());
  receiptTimer = setInterval(async () => {
    if (closing || revoked) return;
    const receipt = proxy.receipt();
    const serialized = JSON.stringify(receipt);
    if (serialized === lastReceipt) return;
    lastReceipt = serialized;
    if (receipt.revoked || receipt.mutationAttempts > 0) {
      revoked = true;
      reason = receipt.mutationAttempts > 0 ? 'browser_mutation_attempt' : 'proxy_revoked';
      proxy.invalidateQa();
      await publish('NOT_READY');
    } else {
      await publish('READY');
    }
  }, 250);
  const reverify = async () => {
    if (closing) return;
    if (await gate()) {
      await publish('READY');
      timer = setTimeout(reverify, intervalMs);
    }
  };
  timer = setTimeout(reverify, intervalMs);
}

main().catch(error => {
  console.error(String(error?.message ?? 'QA NOT READY: launcher_failed'));
  process.exitCode = 1;
});
