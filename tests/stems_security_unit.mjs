import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  audioExtension,
  constants,
  runManagedProcess,
  signalProcessTree,
  validateContentType,
  validateInputSize,
  validateProbeResult,
} = require('../src/controllers/stem-splitter.js');

function fakeChild(pid = 4321) {
  const child = new EventEmitter();
  child.pid = pid;
  child.exitCode = null;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.killSignals = [];
  child.kill = (signalName) => {
    child.killSignals.push(signalName);
    return true;
  };
  return child;
}

test('technical safety constants stay within the approved Lambda candidate envelope', () => {
  assert.equal(constants.MAX_STEMS_INPUT_BYTES, 256 * 1024 * 1024);
  assert.equal(constants.MAX_STEMS_DURATION_SECONDS, 600);
  assert.ok(constants.DEMUCS_TIMEOUT_SECONDS <= 240);
  assert.ok(constants.SIGNED_URL_TTL_SECONDS <= 900);
});

test('only WAV and MP3 extensions are accepted', () => {
  assert.equal(audioExtension('track.WAV'), '.wav');
  assert.equal(audioExtension('track.mp3'), '.mp3');
  assert.throws(() => audioExtension('track.flac'), { code: 'STEMS_INPUT_TYPE_UNSUPPORTED' });
  assert.throws(() => audioExtension(''), { code: 'STEMS_INPUT_NAME_INVALID' });
});

test('content type and object size fail closed', () => {
  validateContentType('audio/wav; charset=binary', '.wav');
  validateContentType('audio/mpeg', '.mp3');
  validateContentType(undefined, '.wav');
  assert.throws(
    () => validateContentType('text/plain', '.wav'),
    { code: 'STEMS_CONTENT_TYPE_INVALID' },
  );
  assert.equal(validateInputSize(1024, 2048), 1024);
  assert.throws(() => validateInputSize(0, 2048), { code: 'STEMS_INPUT_SIZE_INVALID' });
  assert.throws(() => validateInputSize(2049, 2048), { code: 'STEMS_INPUT_TOO_LARGE' });
});

test('ffprobe result must be finite, bounded and match the declared container', () => {
  assert.deepEqual(
    validateProbeResult({ durationSeconds: 120.5, formatName: 'wav' }, '.wav'),
    { durationSeconds: 120.5, formatName: 'wav' },
  );
  assert.deepEqual(
    validateProbeResult({ durationSeconds: 42, formatName: 'mp3' }, '.mp3'),
    { durationSeconds: 42, formatName: 'mp3' },
  );
  assert.throws(
    () => validateProbeResult({ durationSeconds: Number.NaN, formatName: 'wav' }, '.wav'),
    { code: 'STEMS_MEDIA_INVALID' },
  );
  assert.throws(
    () => validateProbeResult({ durationSeconds: 601, formatName: 'wav' }, '.wav'),
    { code: 'STEMS_DURATION_TOO_LONG' },
  );
  assert.throws(
    () => validateProbeResult({ durationSeconds: 1, formatName: 'matroska,webm' }, '.wav'),
    { code: 'STEMS_MEDIA_TYPE_MISMATCH' },
  );
});

test('Linux process-tree termination targets the whole process group', () => {
  const child = fakeChild(2468);
  const calls = [];
  signalProcessTree(child, 'SIGTERM', {
    platform: 'linux',
    processKill: (pid, signalName) => calls.push({ pid, signalName }),
  });
  assert.deepEqual(calls, [{ pid: -2468, signalName: 'SIGTERM' }]);
  assert.deepEqual(child.killSignals, []);
});

test('bounded process timeout terminates the Linux process group and returns a safe code', async () => {
  const child = fakeChild(1357);
  const processSignals = [];
  let spawnOptions;
  const promise = runManagedProcess('demucs-wrapper', [], {
    timeoutMs: 5,
    killGraceMs: 5,
    platform: 'linux',
    spawnImpl: (command, args, options) => {
      spawnOptions = options;
      return child;
    },
    processKill: (pid, signalName) => {
      processSignals.push({ pid, signalName });
      if (signalName === 'SIGTERM') {
        child.exitCode = 143;
        setImmediate(() => child.emit('close', 143, 'SIGTERM'));
      }
    },
  });

  await assert.rejects(promise, { code: 'STEMS_PROCESS_TIMEOUT' });
  assert.equal(spawnOptions.detached, true);
  assert.deepEqual(processSignals[0], { pid: -1357, signalName: 'SIGTERM' });
});

test('request abort terminates processing and returns no internal process output', async () => {
  const child = fakeChild(9876);
  const controller = new AbortController();
  const processSignals = [];
  const promise = runManagedProcess('demucs-wrapper', [], {
    signal: controller.signal,
    timeoutMs: 5_000,
    platform: 'linux',
    spawnImpl: () => child,
    processKill: (pid, signalName) => {
      processSignals.push({ pid, signalName });
      child.exitCode = 143;
      setImmediate(() => child.emit('close', 143, 'SIGTERM'));
    },
  });
  child.stderr.write('/tmp/private bearer-secret raw demucs stderr');
  controller.abort();

  await assert.rejects(promise, (error) => {
    assert.equal(error.code, 'STEMS_REQUEST_ABORTED');
    assert.doesNotMatch(error.message, /private|bearer-secret|demucs stderr/i);
    return true;
  });
  assert.deepEqual(processSignals[0], { pid: -9876, signalName: 'SIGTERM' });
});
