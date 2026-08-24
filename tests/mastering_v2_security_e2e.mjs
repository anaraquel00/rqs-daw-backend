import { spawn } from 'node:child_process';
import process from 'node:process';

const PORT = 18081;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const PYTHON_BIN = process.env.RQS_PYTHON_BIN || 'python';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForHealth(server, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (server.exitCode !== null) {
      throw new Error(`Backend exited before health check. exitCode=${server.exitCode}`);
    }
    try {
      const response = await fetch(`${BASE_URL}/health`);
      if (response.ok) return response;
    } catch {
      // Server is still starting.
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('Timed out waiting for local backend health endpoint.');
}

async function main() {
  const server = spawn(process.execPath, ['scripts/mastering-v2-local-server.js'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PORT: String(PORT),
      RQS_MASTERING_V2_LOCAL_OUTPUT: '1',
      RQS_PYTHON_BIN: PYTHON_BIN,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdout = '';
  let stderr = '';
  server.stdout.on('data', chunk => { stdout += chunk.toString(); });
  server.stderr.on('data', chunk => { stderr += chunk.toString(); });

  try {
    const health = await waitForHealth(server);
    assert(health.headers.get('x-content-type-options') === 'nosniff', 'nosniff header missing.');
    assert(health.headers.get('x-frame-options') === 'DENY', 'X-Frame-Options header missing.');
    assert(health.headers.get('referrer-policy') === 'no-referrer', 'Referrer-Policy header missing.');
    assert(!health.headers.has('x-powered-by'), 'Express X-Powered-By header must be disabled.');

    const invalidForm = new FormData();
    invalidForm.append('audio', new Blob(['not audio'], { type: 'text/plain' }), 'payload.txt');
    invalidForm.append('destination', 'streaming');
    invalidForm.append('platform', 'spotify');
    invalidForm.append('atmosphere', 'clear_sky');
    invalidForm.append('intensity_percent', '50');
    invalidForm.append('soundcloud_mode', 'standard');
    invalidForm.append('preview', 'true');

    const invalidResponse = await fetch(`${BASE_URL}/mastering/v2/process`, {
      method: 'POST',
      body: invalidForm,
    });
    assert(invalidResponse.status === 400, `Expected invalid extension HTTP 400, got ${invalidResponse.status}.`);
    const invalidPayload = await invalidResponse.json();
    assert(
      typeof invalidPayload.error === 'string' && invalidPayload.error.includes('WAV or MP3'),
      `Unexpected invalid upload error: ${JSON.stringify(invalidPayload)}`,
    );

    const multiForm = new FormData();
    multiForm.append('audio', new Blob(['a'], { type: 'audio/wav' }), 'one.wav');
    multiForm.append('audio', new Blob(['b'], { type: 'audio/wav' }), 'two.wav');
    const multiResponse = await fetch(`${BASE_URL}/mastering/v2/process`, {
      method: 'POST',
      body: multiForm,
    });
    assert(multiResponse.status === 400, `Expected multi-file HTTP 400, got ${multiResponse.status}.`);

    console.log('MASTERING_V2_SECURITY_HEADERS: PASS');
    console.log('MASTERING_V2_UPLOAD_BOUNDARIES: PASS');
  } catch (error) {
    console.error('MASTERING_V2_SECURITY_E2E: FAIL');
    console.error(error);
    console.error('--- backend stdout ---');
    console.error(stdout);
    console.error('--- backend stderr ---');
    console.error(stderr);
    process.exitCode = 1;
  } finally {
    if (server.exitCode === null) {
      server.kill('SIGTERM');
      await new Promise(resolve => {
        const timer = setTimeout(resolve, 3000);
        server.once('exit', () => {
          clearTimeout(timer);
          resolve();
        });
      });
      if (server.exitCode === null) server.kill('SIGKILL');
    }
  }
}

await main();
