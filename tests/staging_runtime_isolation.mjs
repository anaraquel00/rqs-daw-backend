import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import net from 'node:net';

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForHealth(baseUrl, child) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Backend exited before health check (code ${child.exitCode}).`);
    }
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.status === 200) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Timed out waiting for backend health.');
}

const port = await freePort();
const allowedOrigin = 'https://candidate-preview.example.test';
const baseUrl = `http://127.0.0.1:${port}`;

const env = {
  ...process.env,
  PORT: String(port),
  RQS_PAYMENT_MODE: 'disabled',
  RQS_ALLOWED_ORIGINS: allowedOrigin,
};

delete env.STRIPE_SECRET_KEY;
delete env.STRIPE_WEBHOOK_SECRET;
delete env.SUPABASE_SECRET_KEY;
delete env.SUPABASE_URL;

const child = spawn(process.execPath, ['server.js'], {
  cwd: process.cwd(),
  env,
  stdio: ['ignore', 'pipe', 'pipe'],
});

let stderr = '';
child.stderr.on('data', chunk => { stderr += chunk.toString(); });

try {
  await waitForHealth(baseUrl, child);

  const health = await fetch(`${baseUrl}/health`, {
    headers: { Origin: allowedOrigin },
  });
  assert.equal(health.status, 200);
  assert.equal(health.headers.get('access-control-allow-origin'), allowedOrigin);

  const denied = await fetch(`${baseUrl}/health`, {
    headers: { Origin: 'https://not-allowed.example.test' },
  });
  assert.equal(denied.status, 200);
  assert.equal(denied.headers.get('access-control-allow-origin'), null);

  const payment = await fetch(`${baseUrl}/payment/stripe-webhook`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Origin: allowedOrigin,
    },
    body: JSON.stringify({}),
  });
  assert.equal(payment.status, 503);
  const payload = await payment.json();
  assert.equal(payload.code, 'PAYMENT_DISABLED');

  assert.equal(child.exitCode, null);
  console.log('STAGING_RUNTIME_PAYMENT_DISABLED_BOOT: PASS');
  console.log('STAGING_RUNTIME_EXACT_CORS: PASS');
  console.log('STAGING_RUNTIME_PROD_STRIPE_SECRET_REQUIRED: NO');
} finally {
  child.kill('SIGTERM');
  await new Promise(resolve => {
    const timer = setTimeout(resolve, 3000);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

if (stderr.trim()) {
  console.error(stderr.trim());
  process.exitCode = 1;
}
