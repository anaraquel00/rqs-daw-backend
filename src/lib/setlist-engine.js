'use strict';

const fs = require('node:fs');
const ffmpeg = require('fluent-ffmpeg');
const { RqsHttpError } = require('./supabase-server');

const OUTPUT_SAMPLE_RATE = 48000;
const OUTPUT_CHANNELS = 2;
const OUTPUT_BYTES_PER_SAMPLE = 3;
const OUTPUT_CODEC = 'pcm_s24le';
const OUTPUT_CONTENT_TYPE = 'audio/wav';
const OUTPUT_FORMAT = 'wav';

const MAX_REQUEST_BYTES = 32 * 1024;
const MIN_TRACKS = 2;
const MAX_TRACKS = 8;
const MAX_INDIVIDUAL_INPUT_BYTES = 96 * 1024 * 1024;
const MAX_TOTAL_INPUT_BYTES = 192 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 256 * 1024 * 1024;
const MAX_INDIVIDUAL_DURATION_SECONDS = 12 * 60;
const MAX_TOTAL_DURATION_SECONDS = 20 * 60;
const MAX_VIGNETTE_DURATION_SECONDS = 60;
const MIN_CROSSFADE_SECONDS = 0.5;
const MAX_CROSSFADE_SECONDS = 15;

const KNOWN_FIELDS = new Set([
  'tracks',
  'vignette',
  'crossfades',
  'curve',
  'loudness',
  'exportName',
  'outputFormat',
]);
const CURVE_MAP = Object.freeze({
  linear: 'tri',
  'equal-power': 'qsin',
  'fast-cut': 'exp',
});
const LOUDNESS_MODES = new Set(['off', 'normalize']);
const AUDIO_EXTENSIONS = new Set(['.wav', '.mp3']);

function setlistError(statusCode, message, code) {
  return new RqsHttpError(statusCode, message, code);
}

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function extensionForKey(key) {
  const clean = String(key || '').split(/[?#]/, 1)[0].toLowerCase();
  const dot = clean.lastIndexOf('.');
  const extension = dot >= 0 ? clean.slice(dot) : '';
  if (!AUDIO_EXTENSIONS.has(extension)) {
    throw setlistError(400, 'Setlist inputs must use WAV or MP3 keys.', 'INVALID_TRACK_KEY');
  }
  return extension;
}

function normalizeExportName(value) {
  if (typeof value !== 'string') {
    throw setlistError(400, 'Export name must be text.', 'INVALID_EXPORT_NAME');
  }
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 80) {
    throw setlistError(400, 'Export name must contain 1 to 80 characters.', 'INVALID_EXPORT_NAME');
  }
  const normalized = trimmed
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);
  if (!normalized) {
    throw setlistError(400, 'Export name has no safe characters.', 'INVALID_EXPORT_NAME');
  }
  return normalized;
}

function validateSetlistRequest(body) {
  if (!isPlainObject(body)) {
    throw setlistError(400, 'Setlist request must be a JSON object.', 'INVALID_REQUEST');
  }

  let serialized;
  try {
    serialized = JSON.stringify(body);
  } catch {
    throw setlistError(400, 'Setlist request is not serializable.', 'INVALID_REQUEST');
  }
  if (Buffer.byteLength(serialized, 'utf8') > MAX_REQUEST_BYTES) {
    throw setlistError(413, 'Setlist request is too large.', 'INVALID_REQUEST');
  }

  const unknownFields = Object.keys(body).filter((field) => !KNOWN_FIELDS.has(field));
  if (unknownFields.length > 0) {
    throw setlistError(400, 'Setlist request contains unsupported fields.', 'INVALID_REQUEST');
  }

  if (!Array.isArray(body.tracks) || body.tracks.length < MIN_TRACKS || body.tracks.length > MAX_TRACKS) {
    throw setlistError(
      400,
      `Setlist requires ${MIN_TRACKS} to ${MAX_TRACKS} music tracks.`,
      'INVALID_TRACK_COUNT',
    );
  }

  const tracks = body.tracks.map((key) => {
    if (typeof key !== 'string' || !key.trim()) {
      throw setlistError(400, 'Every music track key must be non-empty text.', 'INVALID_TRACK_KEY');
    }
    const normalized = key.trim();
    extensionForKey(normalized);
    return normalized;
  });
  if (new Set(tracks).size !== tracks.length) {
    throw setlistError(400, 'Duplicate music track keys are not allowed.', 'DUPLICATE_TRACK_KEY');
  }

  let vignette = null;
  if (body.vignette !== undefined && body.vignette !== null) {
    if (typeof body.vignette !== 'string' || !body.vignette.trim()) {
      throw setlistError(400, 'Optional vignette key must be non-empty text.', 'INVALID_VIGNETTE_KEY');
    }
    vignette = body.vignette.trim();
    extensionForKey(vignette);
    if (tracks.includes(vignette)) {
      throw setlistError(400, 'Vignette must be separate from music tracks.', 'INVALID_VIGNETTE_KEY');
    }
  }

  if (!Array.isArray(body.crossfades) || body.crossfades.length !== tracks.length - 1) {
    throw setlistError(400, 'Crossfade count must equal music track count minus one.', 'INVALID_CROSSFADE');
  }
  const crossfades = body.crossfades.map((value) => {
    if (
      typeof value !== 'number'
      || !Number.isFinite(value)
      || value < MIN_CROSSFADE_SECONDS
      || value > MAX_CROSSFADE_SECONDS
    ) {
      throw setlistError(
        400,
        `Crossfades must be finite numbers from ${MIN_CROSSFADE_SECONDS} to ${MAX_CROSSFADE_SECONDS} seconds.`,
        'INVALID_CROSSFADE',
      );
    }
    return value;
  });

  if (typeof body.curve !== 'string' || !Object.hasOwn(CURVE_MAP, body.curve)) {
    throw setlistError(400, 'Unsupported Setlist crossfade curve.', 'UNSUPPORTED_CURVE');
  }
  if (typeof body.loudness !== 'string' || !LOUDNESS_MODES.has(body.loudness)) {
    throw setlistError(400, 'Unsupported Setlist loudness mode.', 'UNSUPPORTED_LOUDNESS_MODE');
  }
  if (body.outputFormat !== OUTPUT_FORMAT) {
    throw setlistError(400, 'Setlist Stage 1 supports WAV output only.', 'UNSUPPORTED_OUTPUT_FORMAT');
  }

  return Object.freeze({
    tracks: Object.freeze(tracks),
    vignette,
    crossfades: Object.freeze(crossfades),
    curve: body.curve,
    loudness: body.loudness,
    exportName: normalizeExportName(body.exportName),
    outputFormat: OUTPUT_FORMAT,
  });
}

function validateObjectSize(contentLength, label) {
  const size = Number(contentLength);
  if (!Number.isFinite(size) || size <= 0) {
    throw setlistError(422, `${label} size could not be verified.`, 'INPUT_SIZE_UNKNOWN');
  }
  if (size > MAX_INDIVIDUAL_INPUT_BYTES) {
    throw setlistError(413, `${label} exceeds the Stage 1 size limit.`, 'INPUT_TOO_LARGE');
  }
  return size;
}

function validateTotalInputSize(sizes) {
  const total = sizes.reduce((sum, size) => sum + size, 0);
  if (total > MAX_TOTAL_INPUT_BYTES) {
    throw setlistError(413, 'Combined Setlist inputs exceed the Stage 1 size limit.', 'INPUT_TOO_LARGE');
  }
  return total;
}

function probeAudio(filePath) {
  return new Promise((resolve, reject) => {
    ffmpeg.ffprobe(filePath, (error, metadata) => {
      if (error) {
        reject(setlistError(422, 'An input audio file could not be inspected.', 'INVALID_AUDIO_INPUT'));
        return;
      }
      const audioStream = metadata?.streams?.find((stream) => stream.codec_type === 'audio');
      const duration = Number(audioStream?.duration ?? metadata?.format?.duration);
      if (!audioStream || !Number.isFinite(duration) || duration <= 0) {
        reject(setlistError(422, 'An input does not contain measurable audio.', 'INVALID_AUDIO_INPUT'));
        return;
      }
      resolve({
        duration,
        sampleRate: Number(audioStream.sample_rate) || null,
        channels: Number(audioStream.channels) || null,
        codec: String(audioStream.codec_name || 'unknown'),
      });
    });
  });
}

function validateProbedInputs(plan, trackProbes, vignetteProbe = null) {
  if (!Array.isArray(trackProbes) || trackProbes.length !== plan.tracks.length) {
    throw setlistError(500, 'Setlist probe result count mismatch.', 'RENDER_CONTRACT_ERROR');
  }

  for (const probe of trackProbes) {
    if (probe.duration > MAX_INDIVIDUAL_DURATION_SECONDS) {
      throw setlistError(413, 'A music track exceeds the Stage 1 duration limit.', 'INPUT_TOO_LONG');
    }
  }
  if (vignetteProbe && vignetteProbe.duration > MAX_VIGNETTE_DURATION_SECONDS) {
    throw setlistError(413, 'Vignette exceeds the Stage 1 duration limit.', 'INPUT_TOO_LONG');
  }

  const totalMusicDuration = trackProbes.reduce((sum, probe) => sum + probe.duration, 0);
  if (totalMusicDuration > MAX_TOTAL_DURATION_SECONDS) {
    throw setlistError(413, 'Combined music duration exceeds the Stage 1 limit.', 'INPUT_TOO_LONG');
  }

  plan.crossfades.forEach((fade, index) => {
    const shorterAdjacentTrack = Math.min(trackProbes[index].duration, trackProbes[index + 1].duration);
    if (fade >= shorterAdjacentTrack) {
      throw setlistError(400, 'Crossfade must be shorter than both adjacent tracks.', 'INVALID_CROSSFADE');
    }
  });

  const outputDuration = totalMusicDuration - plan.crossfades.reduce((sum, fade) => sum + fade, 0);
  const estimatedOutputBytes = Math.ceil(
    outputDuration * OUTPUT_SAMPLE_RATE * OUTPUT_CHANNELS * OUTPUT_BYTES_PER_SAMPLE + 4096,
  );
  if (estimatedOutputBytes > MAX_OUTPUT_BYTES) {
    throw setlistError(413, 'Estimated WAV output exceeds the Stage 1 safety limit.', 'OUTPUT_TOO_LARGE');
  }

  return { totalMusicDuration, outputDuration, estimatedOutputBytes };
}

function buildFilterPlan(plan, trackProbes, vignetteProbe = null) {
  let lastOutput = '0:a';
  const filters = [];
  const curve = CURVE_MAP[plan.curve];

  for (let index = 0; index < plan.tracks.length - 1; index += 1) {
    const output = `music_xfade_${index + 1}`;
    filters.push({
      filter: 'acrossfade',
      options: { d: plan.crossfades[index], c1: curve, c2: curve },
      inputs: [lastOutput, `${index + 1}:a`],
      outputs: output,
    });
    lastOutput = output;
  }

  if (plan.loudness === 'normalize') {
    filters.push({
      filter: 'loudnorm',
      options: 'I=-16:LRA=11:TP=-1.5',
      inputs: lastOutput,
      outputs: 'music_normalized',
    });
    lastOutput = 'music_normalized';
  }

  if (plan.vignette) {
    const vignetteInput = `${plan.tracks.length}:a`;
    const delaySeconds = 2;
    const vignetteDuration = vignetteProbe.duration;
    const duckStart = 1.5;
    const duckEnd = delaySeconds + vignetteDuration;
    const recoverEnd = duckEnd + 1.5;
    const duckExpression = `'if(lt(t,${duckStart}),1,if(lt(t,${delaySeconds}),1-(t-${duckStart})*1.3,if(lt(t,${duckEnd}),0.35,if(lt(t,${recoverEnd}),0.35+(t-${duckEnd})*0.433333,1))))':eval=frame`;

    filters.push({
      filter: 'adelay',
      options: '2000|2000',
      inputs: vignetteInput,
      outputs: 'vignette_delayed',
    });
    filters.push({
      filter: 'volume',
      options: duckExpression,
      inputs: lastOutput,
      outputs: 'music_ducked',
    });
    filters.push({
      filter: 'amix',
      options: { inputs: 2, duration: 'first', dropout_transition: 0, normalize: 0 },
      inputs: ['music_ducked', 'vignette_delayed'],
      outputs: 'setlist_final',
    });
    lastOutput = 'setlist_final';
  }

  return { filters, finalOutput: lastOutput };
}

async function renderSetlistToFile({ trackPaths, vignettePath = null, plan, outputPath, signal = null }) {
  const trackProbes = await Promise.all(trackPaths.map(probeAudio));
  const vignetteProbe = vignettePath ? await probeAudio(vignettePath) : null;
  const durationContract = validateProbedInputs(plan, trackProbes, vignetteProbe);
  const filterPlan = buildFilterPlan(plan, trackProbes, vignetteProbe);

  await new Promise((resolve, reject) => {
    const command = ffmpeg();
    trackPaths.forEach((filePath) => command.input(filePath));
    if (vignettePath) command.input(vignettePath);

    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      if (signal) signal.removeEventListener('abort', onAbort);
      callback(value);
    };
    const onAbort = () => {
      command.kill('SIGKILL');
      finish(reject, setlistError(499, 'Setlist request was cancelled.', 'REQUEST_ABORTED'));
    };
    if (signal?.aborted) {
      onAbort();
      return;
    }
    if (signal) signal.addEventListener('abort', onAbort, { once: true });

    command
      .complexFilter(filterPlan.filters, filterPlan.finalOutput)
      .audioCodec(OUTPUT_CODEC)
      .audioFrequency(OUTPUT_SAMPLE_RATE)
      .audioChannels(OUTPUT_CHANNELS)
      .format(OUTPUT_FORMAT)
      .outputOptions('-map_metadata', '-1')
      .on('end', () => finish(resolve))
      .on('error', (error) => {
        const sanitized = setlistError(500, 'Setlist render failed.', 'RENDER_FAILED');
        sanitized.cause = error;
        finish(reject, sanitized);
      })
      .save(outputPath);
  });

  const outputStat = await fs.promises.stat(outputPath);
  if (outputStat.size <= 0 || outputStat.size > MAX_OUTPUT_BYTES) {
    await fs.promises.rm(outputPath, { force: true });
    throw setlistError(500, 'Rendered Setlist output violated the size contract.', 'OUTPUT_SIZE_INVALID');
  }

  return {
    ...durationContract,
    trackProbes,
    vignetteProbe,
    outputBytes: outputStat.size,
    outputCodec: OUTPUT_CODEC,
    outputSampleRate: OUTPUT_SAMPLE_RATE,
    outputChannels: OUTPUT_CHANNELS,
  };
}

module.exports = {
  AUDIO_EXTENSIONS,
  CURVE_MAP,
  LOUDNESS_MODES,
  MAX_CROSSFADE_SECONDS,
  MAX_INDIVIDUAL_DURATION_SECONDS,
  MAX_INDIVIDUAL_INPUT_BYTES,
  MAX_OUTPUT_BYTES,
  MAX_REQUEST_BYTES,
  MAX_TOTAL_DURATION_SECONDS,
  MAX_TOTAL_INPUT_BYTES,
  MAX_TRACKS,
  MAX_VIGNETTE_DURATION_SECONDS,
  MIN_CROSSFADE_SECONDS,
  MIN_TRACKS,
  OUTPUT_CHANNELS,
  OUTPUT_CODEC,
  OUTPUT_CONTENT_TYPE,
  OUTPUT_FORMAT,
  OUTPUT_SAMPLE_RATE,
  buildFilterPlan,
  extensionForKey,
  normalizeExportName,
  probeAudio,
  renderSetlistToFile,
  validateObjectSize,
  validateProbedInputs,
  validateSetlistRequest,
  validateTotalInputSize,
};
