import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Readable } from 'node:stream';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const express = require('express');
const { RqsHttpError } = require('../src/lib/supabase-server');
const { createSetlistRouter } = require('../src/controllers/mix-generator');


const owned = (name) => `uploads/user-1/setlist/${name}.wav`;
const body = (overrides = {}) => ({
  tracks: [owned('track-01'), owned('track-02')],
  vignette: null,
  crossfades: [2],
  curve: 'equal-power',
  loudness: 'off',
  exportName: 'HTTP Contract',
  outputFormat: 'wav',
  ...overrides,
});

const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'rqs-setlist-http-test-'));
const calls = [];
let renderFailure = null;
let uploadFailure = false;
let lastRender = null;
let profileRole = 'premium';
let profileFailure = null;
let profileReadCount = 0;
let renderCount = 0;

const fakeClient = {
  async send(command) {
    const name = command.constructor.name;
    calls.push({ name, input: command.input });
    if (name === 'HeadObjectCommand') return { ContentLength: 1024 };
    if (name === 'GetObjectCommand') return { Body: Readable.from(Buffer.from('test-audio')) };
    if (name === 'PutObjectCommand') {
      if (uploadFailure) throw new Error('PRIVATE_OUTPUT_UPLOAD_DETAIL');
      if (command.input.Body && Symbol.asyncIterator in command.input.Body) {
        for await (const _chunk of command.input.Body) { /* consume stream */ }
      }
      return {};
    }
    throw new Error(`Unexpected command ${name}`);
  },
};

async function verifyUser(req) {
  const auth = String(req.headers.authorization || '');
  if (!auth) throw new RqsHttpError(401, 'Authentication required.', 'AUTH_REQUIRED');
  if (auth === 'Bearer invalid') throw new RqsHttpError(401, 'Invalid or expired session.', 'AUTH_INVALID');
  return { id: 'user-1' };
}

async function renderSetlist(options) {
  if (renderFailure) throw renderFailure;
  renderCount += 1;
  lastRender = options;
  await fs.promises.writeFile(options.outputPath, Buffer.from('RIFF-test-output'));
  return {
    outputDuration: 38,
    outputCodec: 'pcm_s24le',
    outputSampleRate: 48000,
    outputChannels: 2,
  };
}

async function readProfileRole() {
  profileReadCount += 1;
  if (profileFailure) throw profileFailure;
  return profileRole;
}
const app = express();

app.use('/mix', createSetlistRouter({
  verifyUser,
  readProfileRole,
  getStorageConfig: () => ({ region: 'sa-east-1', bucketName: 'test-bucket', localOutput: false }),
  makeS3Client: () => fakeClient,
  signUrl: async (_client, command) => command.constructor.name === 'PutObjectCommand'
    ? 'https://upload.example.test/signed'
    : 'https://download.example.test/signed',
  renderSetlist,
  tmpRoot: tempRoot,
}));

const server = await new Promise((resolve) => {
  const listener = app.listen(0, '127.0.0.1', () => resolve(listener));
});
const baseUrl = `http://127.0.0.1:${server.address().port}`;

async function request(method, pathname, requestBody, token = 'valid') {
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers: {
      ...(requestBody === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
    },
    body: requestBody === undefined ? undefined : JSON.stringify(requestBody),
  });
  const payload = await response.json();
  return { response, payload };
}

try {
  let result = await request('POST', '/mix/generate-s3', body({ padding: 'x'.repeat(33 * 1024) }));
  assert.equal(result.response.status, 413);
  assert.equal(result.payload.code, 'INVALID_REQUEST');

  result = await request('POST', '/mix/generate-s3', body(), null);
  assert.equal(result.response.status, 401);
  assert.equal(result.payload.code, 'AUTH_REQUIRED');

  result = await request('POST', '/mix/generate-s3', body(), 'invalid');
  assert.equal(result.response.status, 401);
  assert.equal(result.payload.code, 'AUTH_INVALID');
  profileRole = 'free';
  for (const trackCount of [2, 3]) {
    calls.length = 0;
    const tracks = Array.from({ length: trackCount }, (_, index) => owned(`free-${index + 1}`));
    result = await request('POST', '/mix/generate-s3', body({
      tracks,
      crossfades: Array(trackCount - 1).fill(2),
    }));
    assert.equal(result.response.status, 200);
  }

  for (const trackCount of [4, 8]) {
    calls.length = 0;
    const rendersBefore = renderCount;
    const tracks = Array.from({ length: trackCount }, (_, index) => owned(`free-limit-${index + 1}`));
    result = await request('POST', '/mix/generate-s3', body({
      tracks,
      crossfades: Array(trackCount - 1).fill(2),
    }));
    assert.equal(result.response.status, 403);
    assert.equal(result.payload.code, 'SETLIST_PLAN_LIMIT_EXCEEDED');
    assert.equal(calls.length, 0);
    assert.equal(renderCount, rendersBefore);
  }

  profileRole = 'premium';
  for (const trackCount of [2, 8]) {
    const tracks = Array.from({ length: trackCount }, (_, index) => owned(`premium-${index + 1}`));
    result = await request('POST', '/mix/generate-s3', body({
      tracks,
      crossfades: Array(trackCount - 1).fill(2),
    }));
    assert.equal(result.response.status, 200);
  }

  const profileReadsBefore = profileReadCount;
  result = await request('POST', '/mix/generate-s3', body({
    tracks: Array.from({ length: 9 }, (_, index) => owned(`premium-limit-${index + 1}`)),
    crossfades: Array(8).fill(2),
  }));
  assert.equal(result.response.status, 400);
  assert.equal(result.payload.code, 'INVALID_TRACK_COUNT');
  assert.equal(profileReadCount, profileReadsBefore);

  for (const invalidRole of [null, 'staff']) {
    calls.length = 0;
    profileRole = invalidRole;
    result = await request('POST', '/mix/generate-s3', body());
    assert.equal(result.response.status, 403);
    assert.equal(result.payload.code, 'SETLIST_PROFILE_INVALID');
    assert.equal(calls.length, 0);
  }

  profileRole = 'premium';
  profileFailure = new RqsHttpError(502, 'Safe profile failure.', 'SETLIST_PROFILE_INVALID');
  calls.length = 0;
  result = await request('POST', '/mix/generate-s3', body());
  assert.equal(result.response.status, 502);
  assert.equal(result.payload.code, 'SETLIST_PROFILE_INVALID');
  assert.equal(JSON.stringify(result.payload).includes('PRIVATE'), false);
  assert.equal(calls.length, 0);
  profileFailure = null;

  calls.length = 0;
  result = await request('POST', '/mix/generate-s3', body({ tracks: ['uploads/user-2/setlist/foreign.wav', owned('track-02')] }));
  assert.equal(result.response.status, 403);
  assert.equal(result.payload.code, 'TRACK_NOT_OWNED');
  assert.equal(calls.length, 0);

  result = await request('POST', '/mix/generate-s3', body({ tracks: [owned('track-01'), 'uploads/user-2/setlist/foreign.wav'] }));
  assert.equal(result.response.status, 403);
  assert.equal(result.payload.code, 'TRACK_NOT_OWNED');

  result = await request('POST', '/mix/generate-s3', body({ vignette: 'uploads/user-2/setlist/vignette.wav' }));
  assert.equal(result.response.status, 403);
  assert.equal(result.payload.code, 'TRACK_NOT_OWNED');

  result = await request('POST', '/mix/generate-s3', body({ tracks: ['uploads/user-1/../foreign.wav', owned('track-02')] }));
  assert.equal(result.response.status, 400);
  assert.equal(result.payload.code, 'INVALID_TRACK_KEY');

  calls.length = 0;
  result = await request('POST', '/mix/generate-s3', body());
  assert.equal(result.response.status, 200);
  assert.equal(result.payload.success, true);
  assert.equal(result.payload.fileName, 'HTTP_Contract.wav');
  assert.deepEqual(lastRender.plan.tracks, [owned('track-01'), owned('track-02')]);
  assert.equal(lastRender.plan.vignette, null);
  assert.match(calls.find((call) => call.name === 'PutObjectCommand').input.Key, /^outputs\/user-1\/setlists\/[0-9a-f-]+\.wav$/);
  assert.equal(Buffer.isBuffer(calls.find((call) => call.name === 'PutObjectCommand').input.Body), false);
  assert.deepEqual(fs.readdirSync(tempRoot), []);

  result = await request('POST', '/mix/generate-s3', body({
    tracks: [owned('track-01'), owned('track-02'), owned('track-03')],
    vignette: owned('vignette'),
    crossfades: [2, 3],
  }));
  assert.equal(result.response.status, 200);
  assert.deepEqual(lastRender.plan.tracks, [owned('track-01'), owned('track-02'), owned('track-03')]);
  assert.equal(lastRender.plan.vignette, owned('vignette'));

  result = await request('POST', '/mix/generate-s3', body({ unexpected: true }));
  assert.equal(result.response.status, 400);
  assert.equal(result.payload.code, 'INVALID_REQUEST');

  result = await request('GET', '/mix/presigned-url?filename=track.wav', undefined, null);
  assert.equal(result.response.status, 401);
  result = await request('GET', '/mix/presigned-url?filename=track.wav', undefined);
  assert.equal(result.response.status, 200);
  assert.match(result.payload.s3Key, /^uploads\/user-1\/setlist\/[0-9a-f-]+_track\.wav$/);

  renderFailure = Object.assign(new Error('RAW_FFMPEG_PRIVATE_STDERR'), { statusCode: 500, code: 'RENDER_FAILED' });
  result = await request('POST', '/mix/generate-s3', body());
  assert.equal(result.response.status, 500);
  assert.equal(result.payload.code, 'RENDER_FAILED');
  assert.equal(JSON.stringify(result.payload).includes('RAW_FFMPEG_PRIVATE_STDERR'), false);
  assert.deepEqual(fs.readdirSync(tempRoot), []);
  renderFailure = null;

  uploadFailure = true;
  result = await request('POST', '/mix/generate-s3', body());
  assert.equal(result.response.status, 502);
  assert.equal(result.payload.code, 'OUTPUT_UPLOAD_FAILED');
  assert.equal(JSON.stringify(result.payload).includes('PRIVATE_OUTPUT_UPLOAD_DETAIL'), false);
  assert.deepEqual(fs.readdirSync(tempRoot), []);
  uploadFailure = false;

  result = await request('POST', '/mix/generate', undefined, null);
  assert.equal(result.response.status, 410);
  assert.equal(result.payload.code, 'LEGACY_SETLIST_ROUTE_RETIRED');

  console.log('SETLIST_STAGE1_HTTP=PASS');
} finally {
  await new Promise((resolve) => server.close(resolve));
  fs.rmSync(tempRoot, { recursive: true, force: true });
}
