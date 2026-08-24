import express from 'express';
import { createRequire } from 'node:module';
import process from 'node:process';

const require = createRequire(import.meta.url);

// Production-like auth mode: do not enable the local auth bypass.
delete process.env.RQS_MASTERING_V2_LOCAL_OUTPUT;
delete process.env.RQS_MASTERING_V2_DIRECT_UPLOAD;
process.env.RQS_PYTHON_BIN = process.env.RQS_PYTHON_BIN || 'python';

const masteringV2Router = require('../src/controllers/mastering-v2');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use('/mastering/v2', masteringV2Router);

const server = app.listen(0, '127.0.0.1');
await new Promise((resolve, reject) => {
  server.once('listening', resolve);
  server.once('error', reject);
});

const address = server.address();
const baseUrl = `http://127.0.0.1:${address.port}`;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

try {
  const capabilities = await fetch(`${baseUrl}/mastering/v2/capabilities`);
  assert(capabilities.status === 200, `Capabilities must stay public; got ${capabilities.status}.`);

  const presigned = await fetch(`${baseUrl}/mastering/v2/presigned-url?filename=test.wav`);
  assert(presigned.status === 401, `Expected presigned URL without JWT to return 401, got ${presigned.status}.`);
  const presignedPayload = await presigned.json();
  assert(presignedPayload.code === 'AUTH_REQUIRED', 'Missing AUTH_REQUIRED code for presigned URL.');

  const form = new FormData();
  form.append('destination', 'streaming');
  form.append('platform', 'spotify');
  form.append('atmosphere', 'clear_sky');
  form.append('intensity_percent', '50');
  form.append('preview', 'true');

  const processResponse = await fetch(`${baseUrl}/mastering/v2/process`, {
    method: 'POST',
    body: form,
  });
  assert(processResponse.status === 401, `Expected process without JWT to return 401, got ${processResponse.status}.`);
  const processPayload = await processResponse.json();
  assert(processPayload.code === 'AUTH_REQUIRED', 'Missing AUTH_REQUIRED code for process route.');

  console.log('MASTERING_V2_CAPABILITIES_PUBLIC_HTTP: PASS');
  console.log('MASTERING_V2_PRESIGNED_AUTH_HTTP: PASS');
  console.log('MASTERING_V2_PROCESS_AUTH_HTTP: PASS');
} finally {
  await new Promise(resolve => server.close(resolve));
}
