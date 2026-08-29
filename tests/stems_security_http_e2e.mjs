import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { Readable } from 'node:stream';
import test from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const express = require('express');
const {
  RqsHttpError,
} = require('../src/lib/supabase-server.js');
const {
  createStemsRouter,
  validateProbeResult,
} = require('../src/controllers/stem-splitter.js');

const USER_A = '11111111-1111-4111-8111-111111111111';
const USER_B = '22222222-2222-4222-8222-222222222222';

function authVerifier(calls) {
  return async (req) => {
    calls.auth += 1;
    const header = String(req.headers.authorization || '');
    if (!header) throw new RqsHttpError(401, 'Authentication required.', 'AUTH_REQUIRED');
    if (header !== 'Bearer valid-a') {
      throw new RqsHttpError(401, 'Invalid or expired session.', 'AUTH_INVALID');
    }
    return { id: USER_A };
  };
}

async function startServer(router) {
  const app = express();
  app.use(express.json({ limit: '1mb' }));
  app.use('/stems', router);
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    server,
    async close() {
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

async function makeTempRoot() {
  return fs.promises.mkdtemp(path.join(os.tmpdir(), 'rqs-stems-http-test-'));
}

async function removeTempRoot(tempRoot) {
  await fs.promises.rm(tempRoot, { recursive: true, force: true });
}

async function pathExists(targetPath) {
  return fs.promises.stat(targetPath).then(() => true, () => false);
}

async function waitForEmptyDirectory(directory, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await fs.promises.readdir(directory)).length === 0) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.equal((await fs.promises.readdir(directory)).length, 0);
}

async function waitForMissingPath(targetPath, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!await pathExists(targetPath)) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.equal(await pathExists(targetPath), false);
}

function makeHarness({
  maxInputBytes = 1024,
  maxDurationSeconds = 600,
  probeResult = { durationSeconds: 60, formatName: 'wav' },
  getStorageConfig,
  runDemucs,
  verifyUser,
} = {}) {
  const calls = {
    auth: 0,
    demucs: [],
    probe: [],
    s3: [],
    signed: [],
  };
  const outputInputs = [];
  const client = {
    async send(command, options = {}) {
      const type = command.constructor.name;
      calls.s3.push({ type, input: command.input, options });
      if (type === 'HeadObjectCommand') {
        return { ContentLength: 16, ContentType: 'audio/wav' };
      }
      if (type === 'GetObjectCommand') {
        return { Body: Readable.from(Buffer.from('valid-audio-data')) };
      }
      if (type === 'PutObjectCommand') {
        outputInputs.push(command.input);
        return {};
      }
      throw new Error(`Unexpected S3 command: ${type}`);
    },
  };
  const router = createStemsRouter({
    verifyUser: verifyUser || authVerifier(calls),
    getStorageConfig: getStorageConfig || (() => ({
      environment: 'staging',
      region: 'sa-east-1',
      bucketName: 'rqs-staging-bucket',
      localOutput: false,
    })),
    makeS3Client: () => client,
    signUrl: async (s3Client, command, options) => {
      calls.signed.push({ s3Client, command, options });
      return 'https://signed.invalid/stems-download';
    },
    probeAudio: async (args) => {
      calls.probe.push(args);
      return validateProbeResult(probeResult, args.extension, args.maximumSeconds);
    },
    runDemucs: runDemucs || (async (args) => {
      calls.demucs.push(args);
      const zipPath = path.join(args.outputDir, 'result.zip');
      await fs.promises.writeFile(zipPath, 'zip-data');
      return zipPath;
    }),
    maxInputBytes,
    maxDurationSeconds,
  });
  return { calls, client, outputInputs, router };
}

async function postS3(baseUrl, s3Key, authorization = 'Bearer valid-a') {
  return fetch(`${baseUrl}/stems/split-s3`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(authorization ? { authorization } : {}),
    },
    body: JSON.stringify({ s3Key }),
  });
}

test('authentication is required before any S3 or Demucs work', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => { throw new Error('must not run'); },
    makeS3Client: () => { throw new Error('must not run'); },
    probeAudio: () => { throw new Error('must not run'); },
    runDemucs: () => { throw new Error('must not run'); },
    tmpRoot: tempRoot,
  });
  const running = await startServer(harness.router);
  try {
    const missing = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`, null);
    assert.equal(missing.status, 401);
    assert.equal((await missing.json()).code, 'AUTH_REQUIRED');

    const invalid = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`, 'Bearer expired');
    assert.equal(invalid.status, 401);
    assert.equal((await invalid.json()).code, 'AUTH_INVALID');
    assert.equal(harness.calls.demucs.length, 0);
    assert.equal(harness.calls.s3.length, 0);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('own S3 key uses bounded owner-scoped streaming output and finite signed URL', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    signUrl: async (client, command, options) => {
      harness.calls.signed.push({ client, command, options });
      return 'https://signed.invalid/stems-download';
    },
    probeAudio: async (args) => {
      harness.calls.probe.push(args);
      return validateProbeResult({ durationSeconds: 30, formatName: 'wav' }, args.extension);
    },
    runDemucs: async (args) => {
      harness.calls.demucs.push(args);
      const zipPath = path.join(args.outputDir, 'result.zip');
      await fs.promises.writeFile(zipPath, 'zip-data');
      return zipPath;
    },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      success: true,
      downloadUrl: 'https://signed.invalid/stems-download',
    });

    assert.deepEqual(harness.calls.s3.map((entry) => entry.type), [
      'HeadObjectCommand', 'GetObjectCommand', 'PutObjectCommand',
    ]);
    const upload = harness.outputInputs[0];
    assert.match(upload.Key, new RegExp(`^stems/${USER_A}/[0-9a-f-]{36}\\.zip$`));
    assert.equal(Buffer.isBuffer(upload.Body), false);
    assert.equal(typeof upload.Body.pipe, 'function');
    assert.equal(upload.ContentLength, 8);
    assert.equal(upload.ContentType, 'application/zip');
    assert.equal(harness.calls.signed.length, 1);
    assert.equal(harness.calls.signed[0].options.expiresIn, 900);
    assert.ok(harness.calls.signed[0].options.expiresIn <= 900);
    await waitForEmptyDirectory(tempRoot);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('cross-owner and traversal keys fail before HeadObject or GetObject', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    probeAudio: () => { throw new Error('must not run'); },
    runDemucs: () => { throw new Error('must not run'); },
    tmpRoot: tempRoot,
  });
  const running = await startServer(harness.router);
  try {
    const foreign = await postS3(running.baseUrl, `uploads/${USER_B}/foreign.wav`);
    assert.equal(foreign.status, 403);
    assert.equal((await foreign.json()).code, 'S3_KEY_FORBIDDEN');

    const traversal = await postS3(running.baseUrl, `uploads/${USER_A}/../escape.wav`);
    assert.equal(traversal.status, 400);
    assert.equal((await traversal.json()).code, 'S3_KEY_INVALID');

    assert.equal(harness.calls.s3.length, 0);
    assert.equal(harness.calls.demucs.length, 0);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('unsupported extension fails before S3 access', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    tmpRoot: tempRoot,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.flac`);
    assert.equal(response.status, 415);
    assert.equal((await response.json()).code, 'STEMS_INPUT_TYPE_UNSUPPORTED');
    assert.equal(harness.calls.s3.length, 0);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('staging-to-production storage mismatch fails closed before S3 access', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => {
      throw new RqsHttpError(
        503,
        'Staging storage cannot use the production bucket.',
        'MASTERING_STORAGE_ENV_MISMATCH',
      );
    },
    makeS3Client: () => harness.client,
    tmpRoot: tempRoot,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
    assert.equal(response.status, 503);
    const body = await response.json();
    assert.equal(body.code, 'MASTERING_STORAGE_ENV_MISMATCH');
    assert.equal(body.error, 'Stems processing failed safely.');
    assert.equal(harness.calls.s3.length, 0);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('oversized S3 input is rejected after HeadObject and before download or Demucs', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.client.send = async (command, options = {}) => {
    const type = command.constructor.name;
    harness.calls.s3.push({ type, input: command.input, options });
    if (type === 'HeadObjectCommand') {
      return { ContentLength: 1025, ContentType: 'audio/wav' };
    }
    throw new Error('GetObject must not run');
  };
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    probeAudio: () => { throw new Error('must not run'); },
    runDemucs: () => { throw new Error('must not run'); },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
    assert.equal(response.status, 413);
    assert.equal((await response.json()).code, 'STEMS_INPUT_TOO_LARGE');
    assert.deepEqual(harness.calls.s3.map((entry) => entry.type), ['HeadObjectCommand']);
    assert.equal(harness.calls.demucs.length, 0);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('invalid media probe and excessive duration fail before Demucs', async () => {
  for (const scenario of [
    {
      probeResult: { durationSeconds: Number.NaN, formatName: 'wav' },
      expectedStatus: 415,
      expectedCode: 'STEMS_MEDIA_INVALID',
    },
    {
      probeResult: { durationSeconds: 601, formatName: 'wav' },
      expectedStatus: 413,
      expectedCode: 'STEMS_DURATION_TOO_LONG',
    },
  ]) {
    const tempRoot = await makeTempRoot();
    const harness = makeHarness({ probeResult: scenario.probeResult });
    harness.router = createStemsRouter({
      verifyUser: authVerifier(harness.calls),
      getStorageConfig: () => ({
        environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
      }),
      makeS3Client: () => harness.client,
      probeAudio: async (args) => validateProbeResult(
        scenario.probeResult,
        args.extension,
        args.maximumSeconds,
      ),
      runDemucs: async (args) => {
        harness.calls.demucs.push(args);
        throw new Error('must not run');
      },
      tmpRoot: tempRoot,
      maxInputBytes: 1024,
      maxDurationSeconds: 600,
    });
    const running = await startServer(harness.router);
    try {
      const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
      assert.equal(response.status, scenario.expectedStatus);
      assert.equal((await response.json()).code, scenario.expectedCode);
      assert.equal(harness.calls.demucs.length, 0);
      await waitForEmptyDirectory(tempRoot);
    } finally {
      await running.close();
      await removeTempRoot(tempRoot);
    }
  }
});

test('concurrent requests receive distinct temporary roots and both are cleaned', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  const contexts = [];
  let releaseBoth;
  const bothStarted = new Promise((resolve) => { releaseBoth = resolve; });
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    signUrl: async () => 'https://signed.invalid/stems-download',
    probeAudio: async (args) => validateProbeResult(
      { durationSeconds: 30, formatName: 'wav' },
      args.extension,
    ),
    runDemucs: async (args) => {
      contexts.push(args.outputDir);
      if (contexts.length === 2) releaseBoth();
      await bothStarted;
      const zipPath = path.join(args.outputDir, 'result.zip');
      await fs.promises.writeFile(zipPath, 'zip-data');
      return zipPath;
    },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
  });
  const running = await startServer(harness.router);
  try {
    const requests = [
      postS3(running.baseUrl, `uploads/${USER_A}/one.wav`),
      postS3(running.baseUrl, `uploads/${USER_A}/two.wav`),
    ];
    const responses = await Promise.all(requests);
    assert.deepEqual(responses.map((response) => response.status), [200, 200]);
    assert.equal(contexts.length, 2);
    assert.notEqual(contexts[0], contexts[1]);
    await waitForEmptyDirectory(tempRoot);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('timeout returns a stable safe error, performs no upload and cleans request files', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  let requestDirectory;
  let seenTimeout;
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    probeAudio: async (args) => validateProbeResult(
      { durationSeconds: 30, formatName: 'wav' },
      args.extension,
    ),
    runDemucs: async (args) => {
      requestDirectory = args.outputDir;
      seenTimeout = args.timeoutSeconds;
      throw new RqsHttpError(504, 'Stems processing timed out.', 'STEMS_PROCESS_TIMEOUT');
    },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
    demucsTimeoutSeconds: 840,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
    assert.equal(response.status, 504);
    assert.deepEqual(await response.json(), {
      error: 'Stems processing failed safely.',
      code: 'STEMS_PROCESS_TIMEOUT',
    });
    assert.equal(seenTimeout, 840);
    assert.equal(harness.calls.s3.some((entry) => entry.type === 'PutObjectCommand'), false);
    await waitForMissingPath(requestDirectory);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('client disconnect aborts processing, prevents output upload and cleans request files', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  let processingStarted;
  const started = new Promise((resolve) => { processingStarted = resolve; });
  let aborted = false;
  let requestDirectory;
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    probeAudio: async (args) => validateProbeResult(
      { durationSeconds: 30, formatName: 'wav' },
      args.extension,
    ),
    runDemucs: ({ outputDir, signal }) => new Promise((resolve, reject) => {
      requestDirectory = outputDir;
      processingStarted();
      const onAbort = () => {
        aborted = true;
        reject(new RqsHttpError(499, 'cancelled', 'STEMS_REQUEST_ABORTED'));
      };
      if (signal.aborted) onAbort();
      else signal.addEventListener('abort', onAbort, { once: true });
    }),
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
  });
  const running = await startServer(harness.router);
  try {
    const target = new URL(`${running.baseUrl}/stems/split-s3`);
    const payload = JSON.stringify({ s3Key: `uploads/${USER_A}/track.wav` });
    const clientRequest = http.request({
      hostname: target.hostname,
      port: target.port,
      path: target.pathname,
      method: 'POST',
      headers: {
        authorization: 'Bearer valid-a',
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(payload),
      },
    });
    clientRequest.on('error', () => {});
    clientRequest.end(payload);
    await started;
    clientRequest.destroy();

    const deadline = Date.now() + 2_000;
    while (!aborted && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    assert.equal(aborted, true);

    while (requestDirectory && await pathExists(requestDirectory)) {
      if (Date.now() >= deadline) break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    assert.equal(harness.calls.s3.some((entry) => entry.type === 'PutObjectCommand'), false);
    assert.equal(await pathExists(requestDirectory), false);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('internal Demucs details, paths, keys and tokens are never disclosed in a 5xx response', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    getStorageConfig: () => ({
      environment: 'staging', region: 'sa-east-1', bucketName: 'rqs-staging-bucket', localOutput: false,
    }),
    makeS3Client: () => harness.client,
    probeAudio: async (args) => validateProbeResult(
      { durationSeconds: 30, formatName: 'wav' },
      args.extension,
    ),
    runDemucs: async () => {
      throw new Error(`raw stderr /tmp/private Bearer valid-a uploads/${USER_A}/track.wav AWS_SECRET`);
    },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
  });
  const running = await startServer(harness.router);
  try {
    const response = await postS3(running.baseUrl, `uploads/${USER_A}/track.wav`);
    assert.equal(response.status, 500);
    const rawBody = await response.text();
    assert.deepEqual(JSON.parse(rawBody), {
      error: 'Stems processing failed safely.',
      code: 'STEMS_INTERNAL_ERROR',
    });
    assert.doesNotMatch(rawBody, /stderr|\/tmp|Bearer|uploads\/|AWS_SECRET|11111111/i);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('legacy upload route authenticates before parsing a file', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    probeAudio: () => { throw new Error('must not run'); },
    runDemucs: () => { throw new Error('must not run'); },
    tmpRoot: tempRoot,
    maxInputBytes: 8,
  });
  const running = await startServer(harness.router);
  try {
    const form = new FormData();
    form.append('audio', new Blob([Buffer.alloc(32)], { type: 'audio/wav' }), 'unauthenticated.wav');
    const response = await fetch(`${running.baseUrl}/stems/split`, {
      method: 'POST',
      body: form,
    });
    assert.equal(response.status, 401);
    assert.equal((await response.json()).code, 'AUTH_REQUIRED');
    await waitForEmptyDirectory(tempRoot);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('legacy upload enforces the file-size bound and cleans the rejected upload', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    probeAudio: () => { throw new Error('must not run'); },
    runDemucs: () => { throw new Error('must not run'); },
    tmpRoot: tempRoot,
    maxInputBytes: 8,
  });
  const running = await startServer(harness.router);
  try {
    const form = new FormData();
    form.append('audio', new Blob([Buffer.alloc(16)], { type: 'audio/wav' }), 'too-large.wav');
    const response = await fetch(`${running.baseUrl}/stems/split`, {
      method: 'POST',
      headers: { authorization: 'Bearer valid-a' },
      body: form,
    });
    assert.equal(response.status, 413);
    assert.equal((await response.json()).code, 'STEMS_INPUT_TOO_LARGE');
    await waitForEmptyDirectory(tempRoot);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});

test('legacy authenticated bounded happy path returns the ZIP and cleans its request root', async () => {
  const tempRoot = await makeTempRoot();
  const harness = makeHarness();
  const contexts = [];
  harness.router = createStemsRouter({
    verifyUser: authVerifier(harness.calls),
    probeAudio: async (args) => validateProbeResult(
      { durationSeconds: 12, formatName: 'wav' },
      args.extension,
      args.maximumSeconds,
    ),
    runDemucs: async (args) => {
      contexts.push(args.outputDir);
      const zipPath = path.join(args.outputDir, 'legacy-result.zip');
      await fs.promises.writeFile(zipPath, 'legacy-zip-data');
      return zipPath;
    },
    tmpRoot: tempRoot,
    maxInputBytes: 1024,
    maxDurationSeconds: 600,
  });
  const running = await startServer(harness.router);
  try {
    const form = new FormData();
    form.append('audio', new Blob([Buffer.from('wav-data')], { type: 'audio/wav' }), 'track.wav');
    const response = await fetch(`${running.baseUrl}/stems/split`, {
      method: 'POST',
      headers: { authorization: 'Bearer valid-a' },
      body: form,
    });
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-disposition') || '', /rqs_6_stems\.zip/);
    assert.equal(Buffer.from(await response.arrayBuffer()).toString(), 'legacy-zip-data');
    assert.equal(contexts.length, 1);
    await waitForEmptyDirectory(tempRoot);
  } finally {
    await running.close();
    await removeTempRoot(tempRoot);
  }
});
