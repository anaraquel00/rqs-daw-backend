import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import process from 'node:process';

const PORT = 18080;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const PYTHON_BIN = process.env.RQS_PYTHON_BIN || 'python';

function createStereoPcm16Wav({ seconds = 5, sampleRate = 48000, frequency = 440, amplitude = 0.08 } = {}) {
  const channels = 2;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const frameCount = Math.floor(seconds * sampleRate);
  const dataSize = frameCount * channels * bytesPerSample;
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * channels * bytesPerSample, 28);
  buffer.writeUInt16LE(channels * bytesPerSample, 32);
  buffer.writeUInt16LE(bitsPerSample, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(dataSize, 40);

  let offset = 44;
  for (let i = 0; i < frameCount; i += 1) {
    const sample = Math.max(-1, Math.min(1, amplitude * Math.sin((2 * Math.PI * frequency * i) / sampleRate)));
    const pcm = Math.round(sample * 32767);
    buffer.writeInt16LE(pcm, offset);
    buffer.writeInt16LE(pcm, offset + 2);
    offset += 4;
  }

  return buffer;
}


function createPositionEncodedStereoPcm16Wav({ seconds = 24, sampleRate = 48000 } = {}) {
  const channels = 2;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const frameCount = Math.floor(seconds * sampleRate);
  const dataSize = frameCount * channels * bytesPerSample;
  const buffer = Buffer.alloc(44 + dataSize);

  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * channels * bytesPerSample, 28);
  buffer.writeUInt16LE(channels * bytesPerSample, 32);
  buffer.writeUInt16LE(bitsPerSample, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(dataSize, 40);

  let offset = 44;
  for (let i = 0; i < frameCount; i += 1) {
    const t = i / sampleRate;
    const frequency = t < 8 ? 220 : (t < 16 ? 440 : 880);
    const amplitude = t < 8 ? 0.045 : (t < 16 ? 0.075 : 0.11);
    const left = Math.max(-1, Math.min(1, amplitude * Math.sin(2 * Math.PI * frequency * t)));
    const right = Math.max(-1, Math.min(1, amplitude * Math.sin(2 * Math.PI * (frequency * 1.01) * t)));
    buffer.writeInt16LE(Math.round(left * 32767), offset);
    buffer.writeInt16LE(Math.round(right * 32767), offset + 2);
    offset += 4;
  }

  return buffer;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function parseWav(buffer, label) {
  assert(buffer.length > 44, `${label}: WAV response is too small.`);
  assert(buffer.subarray(0, 4).toString('ascii') === 'RIFF', `${label}: missing RIFF header.`);
  assert(buffer.subarray(8, 12).toString('ascii') === 'WAVE', `${label}: missing WAVE header.`);

  let offset = 12;
  let format = null;
  let audioData = null;

  while (offset + 8 <= buffer.length) {
    const chunkId = buffer.subarray(offset, offset + 4).toString('ascii');
    const chunkSize = buffer.readUInt32LE(offset + 4);
    const chunkStart = offset + 8;
    const chunkEnd = chunkStart + chunkSize;
    assert(chunkEnd <= buffer.length, `${label}: invalid ${chunkId} chunk length.`);

    if (chunkId === 'fmt ' && chunkSize >= 16) {
      format = {
        audioFormat: buffer.readUInt16LE(chunkStart),
        channels: buffer.readUInt16LE(chunkStart + 2),
        sampleRate: buffer.readUInt32LE(chunkStart + 4),
        byteRate: buffer.readUInt32LE(chunkStart + 8),
        blockAlign: buffer.readUInt16LE(chunkStart + 12),
        bitsPerSample: buffer.readUInt16LE(chunkStart + 14),
      };
    } else if (chunkId === 'data') {
      audioData = buffer.subarray(chunkStart, chunkEnd);
    }

    offset = chunkEnd + (chunkSize % 2);
  }

  assert(format, `${label}: fmt chunk missing.`);
  assert(audioData, `${label}: data chunk missing.`);
  return { format, audioData };
}

function assertWavEquivalent(actualBuffer, directBuffer, label) {
  const actual = parseWav(actualBuffer, `${label} HTTP`);
  const direct = parseWav(directBuffer, `${label} direct`);

  assert(
    JSON.stringify(actual.format) === JSON.stringify(direct.format),
    `${label}: HTTP/direct WAV format metadata differs. HTTP=${JSON.stringify(actual.format)} direct=${JSON.stringify(direct.format)}`,
  );
  assert(
    actual.audioData.length === direct.audioData.length,
    `${label}: HTTP/direct PCM length differs. HTTP=${actual.audioData.length} direct=${direct.audioData.length}`,
  );
  assert(
    actual.audioData.equals(direct.audioData),
    `${label}: HTTP output is not sample-exact with direct Mastering V2 output.`,
  );
}

async function requireOk(response, label) {
  if (response.ok) return;
  const body = await response.text();
  throw new Error(`${label} failed: ${response.status} ${body}`);
}

function makeMasteringForm(audioBytes, preview, previewStartSeconds = null) {
  const form = new FormData();
  form.append('audio', new Blob([audioBytes], { type: 'audio/wav' }), 'mastering_v2_http_e2e.wav');
  form.append('destination', 'streaming');
  form.append('platform', 'spotify');
  form.append('atmosphere', 'clear_sky');
  form.append('intensity_percent', '50');
  form.append('soundcloud_mode', 'standard');
  form.append('preview', preview ? 'true' : 'false');
  if (preview && previewStartSeconds !== null) {
    form.append('preview_start_seconds', String(previewStartSeconds));
  }
  return form;
}

function renderDirect(inputPath, outputPath, preview, previewStartSeconds = null) {
  const args = [
    '-m',
    'src.controllers.mastering_v2_cli',
    'render',
    '--input', inputPath,
    '--output', outputPath,
    '--destination', 'streaming',
    '--platform', 'spotify',
    '--atmosphere', 'clear_sky',
    '--intensity-percent', '50',
    '--soundcloud-mode', 'standard',
  ];
  if (preview) {
    args.push('--preview');
    if (previewStartSeconds !== null) {
      args.push('--preview-start-seconds', String(previewStartSeconds));
    }
  }

  const result = spawnSync(PYTHON_BIN, args, {
    cwd: process.cwd(),
    env: process.env,
    encoding: 'utf8',
  });
  assert(
    result.status === 0,
    `Direct Mastering V2 ${preview ? 'preview' : 'final'} failed. status=${result.status}\nstdout=${result.stdout}\nstderr=${result.stderr}`,
  );
  return readFileSync(outputPath);
}

async function waitForHealth(server, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (server.exitCode !== null) {
      throw new Error(`Backend exited before health check. exitCode=${server.exitCode}`);
    }
    try {
      const response = await fetch(`${BASE_URL}/health`);
      if (response.ok) return;
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

  const scratchDir = mkdtempSync(join(tmpdir(), 'rqs-mastering-v2-http-e2e-'));
  let stdout = '';
  let stderr = '';
  server.stdout.on('data', chunk => { stdout += chunk.toString(); });
  server.stderr.on('data', chunk => { stderr += chunk.toString(); });

  try {
    await waitForHealth(server);

    const corsResponse = await fetch(`${BASE_URL}/mastering/v2/capabilities`, {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:4200',
        'Access-Control-Request-Method': 'GET',
      },
    });
    await requireOk(corsResponse, 'CORS preflight');
    assert(
      corsResponse.headers.get('access-control-allow-origin') === 'http://localhost:4200',
      'CORS preflight did not allow the local Angular origin.',
    );

    const capabilitiesResponse = await fetch(`${BASE_URL}/mastering/v2/capabilities`);
    await requireOk(capabilitiesResponse, 'Capabilities');
    const capabilities = await capabilitiesResponse.json();
    assert(capabilities.release === 'mastering-v2-v1', 'Capabilities release mismatch.');
    assert(capabilities.intensity?.min === 0 && capabilities.intensity?.max === 100, 'Intensity contract mismatch.');
    assert(capabilities.destinations?.streaming?.platforms?.spotify, 'Spotify delivery policy missing.');

    const audioBytes = createStereoPcm16Wav();
    const directInput = join(scratchDir, 'source.wav');
    const directPreviewPath = join(scratchDir, 'direct_preview.wav');
    const directFinalPath = join(scratchDir, 'direct_final.wav');
    const explicitRangeInput = join(scratchDir, 'source_explicit_range.wav');
    const explicitRangeDirectPath = join(scratchDir, 'direct_preview_explicit_range.wav');
    writeFileSync(directInput, audioBytes);

    const directPreview = renderDirect(directInput, directPreviewPath, true);
    const directFinal = renderDirect(directInput, directFinalPath, false);

    const previewResponse = await fetch(`${BASE_URL}/mastering/v2/process`, {
      method: 'POST',
      body: makeMasteringForm(audioBytes, true),
    });
    await requireOk(previewResponse, 'Preview');
    const httpPreview = Buffer.from(await previewResponse.arrayBuffer());
    parseWav(httpPreview, 'Preview');
    assertWavEquivalent(httpPreview, directPreview, 'Preview');

    const explicitRangeAudio = createPositionEncodedStereoPcm16Wav();
    writeFileSync(explicitRangeInput, explicitRangeAudio);
    const explicitRangeStart = 7;
    const explicitRangeDirect = renderDirect(
      explicitRangeInput,
      explicitRangeDirectPath,
      true,
      explicitRangeStart,
    );
    const explicitRangeResponse = await fetch(`${BASE_URL}/mastering/v2/process`, {
      method: 'POST',
      body: makeMasteringForm(explicitRangeAudio, true, explicitRangeStart),
    });
    await requireOk(explicitRangeResponse, 'Explicit Preview range');
    const explicitRangeHttp = Buffer.from(await explicitRangeResponse.arrayBuffer());
    assertWavEquivalent(explicitRangeHttp, explicitRangeDirect, 'Explicit Preview range');

    const finalResponse = await fetch(`${BASE_URL}/mastering/v2/process`, {
      method: 'POST',
      body: makeMasteringForm(audioBytes, false),
    });
    await requireOk(finalResponse, 'Final render');
    const finalPayload = await finalResponse.json();
    assert(finalPayload.success === true, 'Final response success flag missing.');
    assert(finalPayload.engine === 'mastering-v2-v1', 'Final response engine mismatch.');
    assert(finalPayload.outputMode === 'local', 'Local output mode was not used in E2E.');
    const expectedFileName = 'RQS_MASTER_V2_CLEAR_SKY_STREAMING_SPOTIFY_-14LUFS_mastering_v2_http_e2e.wav';
    assert(
      finalPayload.fileName === expectedFileName,
      `Final filename metadata mismatch. expected=${expectedFileName} actual=${finalPayload.fileName}`,
    );
    assert(typeof finalPayload.downloadUrl === 'string' && finalPayload.downloadUrl.startsWith(BASE_URL), 'Local download URL mismatch.');

    const downloadResponse = await fetch(finalPayload.downloadUrl);
    await requireOk(downloadResponse, 'Final download');
    const disposition = downloadResponse.headers.get('content-disposition') || '';
    assert(
      disposition.includes(expectedFileName),
      `Final Content-Disposition filename mismatch: ${disposition}`,
    );
    const httpFinal = Buffer.from(await downloadResponse.arrayBuffer());
    parseWav(httpFinal, 'Final');
    assertWavEquivalent(httpFinal, directFinal, 'Final');

    const secondDownload = await fetch(finalPayload.downloadUrl);
    await requireOk(secondDownload, 'Repeated final download');
    const repeatedFinal = Buffer.from(await secondDownload.arrayBuffer());
    assertWavEquivalent(repeatedFinal, directFinal, 'Repeated final');

    const rangeResponse = await fetch(finalPayload.downloadUrl, {
      headers: { Range: 'bytes=0-43' },
    });
    assert(rangeResponse.status === 206, `Range download expected 206, got ${rangeResponse.status}.`);
    const rangeBytes = Buffer.from(await rangeResponse.arrayBuffer());
    assert(rangeBytes.length === 44, `Range download expected 44 bytes, got ${rangeBytes.length}.`);
    assert(rangeBytes.subarray(0, 4).toString('ascii') === 'RIFF', 'Range download does not start with RIFF.');

    console.log('MASTERING_V2_HTTP_DIRECT_EQUIVALENCE: PASS');
    console.log('MASTERING_V2_HTTP_EXPLICIT_PREVIEW_RANGE: PASS');
    console.log('MASTERING_V2_LOCAL_MEDIA_REUSE: PASS');
    console.log('MASTERING_V2_HTTP_E2E: PASS');
  } catch (error) {
    console.error('MASTERING_V2_HTTP_E2E: FAIL');
    console.error(error);
    console.error('--- backend stdout ---');
    console.error(stdout);
    console.error('--- backend stderr ---');
    console.error(stderr);
    process.exitCode = 1;
  } finally {
    rmSync(scratchDir, { recursive: true, force: true });
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
