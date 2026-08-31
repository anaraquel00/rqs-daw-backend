import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const express = require('express');
const stemsRouter = require('../src/controllers/stem-splitter');

const expectedBody = {
  success: false,
  code: 'STEMS_V1_DISABLED',
  error: 'Stem separation is temporarily unavailable in V1.',
};

const controllerSource = await readFile(
  new URL('../src/controllers/stem-splitter.js', import.meta.url),
  'utf8',
);

for (const forbiddenDependency of [
  '@aws-sdk',
  'multer',
  'child_process',
  'core_demucs',
  'ffprobe',
  'GetObjectCommand',
  'PutObjectCommand',
]) {
  assert.equal(
    controllerSource.includes(forbiddenDependency),
    false,
    `Disabled V1 controller must not load or reference ${forbiddenDependency}`,
  );
}

const app = express();
app.use('/stems', stemsRouter);

const server = http.createServer(app);
await new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', resolve);
});

const { port } = server.address();

function request(path, { body = '', contentType = 'application/json' } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({
      host: '127.0.0.1',
      port,
      path,
      method: 'POST',
      headers: {
        'content-type': contentType,
        'content-length': Buffer.byteLength(body),
      },
    }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => resolve({
        statusCode: res.statusCode,
        contentType: res.headers['content-type'],
        body: Buffer.concat(chunks).toString('utf8'),
      }));
    });
    req.once('error', reject);
    req.end(body);
  });
}

try {
  const splitS3 = await request('/stems/split-s3', {
    body: JSON.stringify({ s3Key: 'uploads/synthetic/not-used.wav' }),
  });

  const splitUpload = await request('/stems/split', {
    body: '--synthetic-boundary\r\ncontent that must never be parsed\r\n--synthetic-boundary--',
    contentType: 'multipart/form-data; boundary=synthetic-boundary',
  });

  for (const response of [splitS3, splitUpload]) {
    assert.equal(response.statusCode, 410);
    assert.match(response.contentType, /^application\/json\b/);
    assert.deepEqual(JSON.parse(response.body), expectedBody);

    const responseText = response.body.toLowerCase();
    for (const forbiddenField of ['downloadurl', 's3key', 'token', 'secret', 'details', 'log']) {
      assert.equal(
        responseText.includes(forbiddenField),
        false,
        `Disabled response must not contain ${forbiddenField}`,
      );
    }
  }
} finally {
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

console.log('STEMS_V1_DISABLED_SPLIT_S3: PASS');
console.log('STEMS_V1_DISABLED_SPLIT_UPLOAD: PASS');
console.log('STEMS_V1_DISABLED_NO_EXPENSIVE_PATH: PASS');
