'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { Transform } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const express = require('express');
const multer = require('multer');
const {
  S3Client,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
} = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
const {
  RqsHttpError,
  assertUserOwnedS3Key,
  verifySupabaseUser,
} = require('../lib/supabase-server');
const { getMasteringStorageConfig } = require('../lib/mastering-v2-storage');

const MAX_STEMS_INPUT_BYTES = 256 * 1024 * 1024;
const MAX_STEMS_DURATION_SECONDS = 600;
// Keep one minute below Lambda's 900-second ceiling for S3 upload and cleanup.
const DEMUCS_TIMEOUT_SECONDS = 840;
const FFPROBE_TIMEOUT_SECONDS = 15;
const SIGNED_URL_TTL_SECONDS = 900;
const PROCESS_KILL_GRACE_MS = 2_000;
const MAX_PROCESS_OUTPUT_BYTES = 64 * 1024;
const ALLOWED_AUDIO_EXTENSIONS = new Set(['.wav', '.mp3']);

function stemsError(statusCode, message, code) {
  return new RqsHttpError(statusCode, message, code);
}

function audioExtension(value) {
  if (typeof value !== 'string' || !value.trim() || value.includes('\0')) {
    throw stemsError(400, 'Invalid audio filename.', 'STEMS_INPUT_NAME_INVALID');
  }
  const extension = path.extname(value.trim()).toLowerCase();
  if (!ALLOWED_AUDIO_EXTENSIONS.has(extension)) {
    throw stemsError(415, 'Only WAV and MP3 inputs are supported.', 'STEMS_INPUT_TYPE_UNSUPPORTED');
  }
  return extension;
}

function safeDownloadName(s3Key) {
  const extension = path.posix.extname(s3Key);
  const sourceName = path.posix.basename(s3Key, extension);
  const safeStem = sourceName
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 100) || 'rqs_stems';
  return `${safeStem}_stems.zip`;
}

function validateContentType(contentType, extension) {
  if (contentType === undefined || contentType === null || String(contentType).trim() === '') {
    return;
  }
  const normalized = String(contentType).split(';', 1)[0].trim().toLowerCase();
  const allowed = extension === '.mp3'
    ? new Set(['audio/mpeg', 'audio/mp3', 'audio/x-mpeg', 'application/octet-stream'])
    : new Set(['audio/wav', 'audio/x-wav', 'audio/wave', 'audio/vnd.wave', 'application/octet-stream']);
  if (!allowed.has(normalized)) {
    throw stemsError(415, 'Audio content type does not match the input.', 'STEMS_CONTENT_TYPE_INVALID');
  }
}

function validateInputSize(value, maximumBytes = MAX_STEMS_INPUT_BYTES) {
  const size = typeof value === 'bigint' ? Number(value) : Number(value);
  if (!Number.isSafeInteger(size) || size <= 0) {
    throw stemsError(400, 'Audio size is missing or invalid.', 'STEMS_INPUT_SIZE_INVALID');
  }
  if (size > maximumBytes) {
    throw stemsError(413, 'Audio exceeds the technical processing size limit.', 'STEMS_INPUT_TOO_LARGE');
  }
  return size;
}

function validateProbeResult(result, extension, maximumSeconds = MAX_STEMS_DURATION_SECONDS) {
  const durationSeconds = Number(result?.durationSeconds);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw stemsError(415, 'Audio media could not be verified.', 'STEMS_MEDIA_INVALID');
  }
  if (durationSeconds > maximumSeconds) {
    throw stemsError(413, 'Audio exceeds the technical processing duration limit.', 'STEMS_DURATION_TOO_LONG');
  }

  const formats = String(result?.formatName || '')
    .toLowerCase()
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  const expectedFormat = extension === '.mp3' ? 'mp3' : 'wav';
  if (!formats.includes(expectedFormat)) {
    throw stemsError(415, 'Audio container does not match the input type.', 'STEMS_MEDIA_TYPE_MISMATCH');
  }
  return { durationSeconds, formatName: expectedFormat };
}

function signalProcessTree(child, signalName, {
  platform = process.platform,
  processKill = process.kill,
} = {}) {
  if (!child || child.exitCode !== null || !Number.isInteger(child.pid) || child.pid <= 0) return;

  if (platform !== 'win32') {
    try {
      processKill(-child.pid, signalName);
      return;
    } catch {
      // Fall back to the direct child if the process group has already exited.
    }
  }

  try {
    child.kill(signalName);
  } catch {
    // A concurrently exiting child requires no further action.
  }
}

function runManagedProcess(command, args, {
  signal,
  timeoutMs,
  spawnImpl = spawn,
  platform = process.platform,
  processKill = process.kill,
  killGraceMs = PROCESS_KILL_GRACE_MS,
  timeoutError = () => stemsError(504, 'Stems processing timed out.', 'STEMS_PROCESS_TIMEOUT'),
  abortError = () => stemsError(499, 'Stems processing was cancelled.', 'STEMS_REQUEST_ABORTED'),
  failureError = () => stemsError(500, 'Stems processing failed.', 'STEMS_PROCESS_FAILED'),
} = {}) {
  return new Promise((resolve, reject) => {
    let child;
    let settled = false;
    let stopReason = null;
    let timeoutHandle = null;
    let killHandle = null;
    let stdout = '';
    let stderr = '';

    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      if (timeoutHandle) clearTimeout(timeoutHandle);
      if (killHandle) clearTimeout(killHandle);
      signal?.removeEventListener('abort', onAbort);
      if (error) reject(error);
      else resolve(result);
    };

    const stop = (reason) => {
      if (settled || stopReason) return;
      stopReason = reason;
      signalProcessTree(child, 'SIGTERM', { platform, processKill });
      killHandle = setTimeout(() => {
        signalProcessTree(child, 'SIGKILL', { platform, processKill });
      }, killGraceMs);
      killHandle.unref?.();
    };

    const onAbort = () => stop('abort');

    if (signal?.aborted) {
      finish(abortError());
      return;
    }

    try {
      child = spawnImpl(command, args, {
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: platform !== 'win32',
      });
    } catch {
      finish(failureError());
      return;
    }

    signal?.addEventListener('abort', onAbort, { once: true });
    if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timeoutHandle = setTimeout(() => stop('timeout'), timeoutMs);
    }

    child.stdout?.on('data', (chunk) => {
      if (stdout.length < MAX_PROCESS_OUTPUT_BYTES) {
        stdout += String(chunk).slice(0, MAX_PROCESS_OUTPUT_BYTES - stdout.length);
      }
    });
    child.stderr?.on('data', (chunk) => {
      if (stderr.length < MAX_PROCESS_OUTPUT_BYTES) {
        stderr += String(chunk).slice(0, MAX_PROCESS_OUTPUT_BYTES - stderr.length);
      }
    });
    child.once('error', () => finish(failureError()));
    child.once('close', (code, closeSignal) => {
      if (stopReason === 'timeout') {
        finish(timeoutError());
      } else if (stopReason === 'abort') {
        finish(abortError());
      } else if (code !== 0) {
        finish(failureError());
      } else {
        finish(null, { code, closeSignal, stdout, stderr });
      }
    });
  });
}

async function probeAudioFile({
  inputPath,
  extension,
  signal,
  maximumSeconds = MAX_STEMS_DURATION_SECONDS,
  timeoutSeconds = FFPROBE_TIMEOUT_SECONDS,
  spawnImpl,
}) {
  const result = await runManagedProcess(
    'ffprobe',
    ['-v', 'error', '-show_entries', 'format=duration,format_name', '-of', 'json', inputPath],
    {
      signal,
      timeoutMs: timeoutSeconds * 1_000,
      spawnImpl,
      timeoutError: () => stemsError(415, 'Audio media probe timed out.', 'STEMS_MEDIA_PROBE_TIMEOUT'),
      abortError: () => stemsError(499, 'Stems processing was cancelled.', 'STEMS_REQUEST_ABORTED'),
      failureError: () => stemsError(415, 'Audio media could not be verified.', 'STEMS_MEDIA_INVALID'),
    },
  );

  let parsed;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw stemsError(415, 'Audio media could not be verified.', 'STEMS_MEDIA_INVALID');
  }
  return validateProbeResult({
    durationSeconds: parsed?.format?.duration,
    formatName: parsed?.format?.format_name,
  }, extension, maximumSeconds);
}

async function runDemucsProcess({
  inputPath,
  outputDir,
  signal,
  timeoutSeconds = DEMUCS_TIMEOUT_SECONDS,
  spawnImpl,
  platform,
  processKill,
  killGraceMs,
}) {
  const scriptPath = path.join(__dirname, 'core_demucs.py');
  const result = await runManagedProcess(
    '/opt/venv/bin/python3',
    [scriptPath, inputPath, outputDir],
    {
      signal,
      timeoutMs: timeoutSeconds * 1_000,
      spawnImpl,
      platform,
      processKill,
      killGraceMs,
    },
  );

  const successMatch = /(?:^|\r?\n)SUCCESS:(.+?)(?:\r?\n|$)/.exec(result.stdout);
  if (!successMatch) {
    throw stemsError(500, 'Stems processing failed.', 'STEMS_OUTPUT_MISSING');
  }

  const zipPath = path.resolve(successMatch[1].trim());
  const relative = path.relative(path.resolve(outputDir), zipPath);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw stemsError(500, 'Stems processing failed.', 'STEMS_OUTPUT_PATH_INVALID');
  }
  const stat = await fs.promises.stat(zipPath).catch(() => null);
  if (!stat?.isFile() || stat.size <= 0) {
    throw stemsError(500, 'Stems processing failed.', 'STEMS_OUTPUT_MISSING');
  }
  return zipPath;
}

function createByteLimitTransform(maximumBytes) {
  let total = 0;
  return new Transform({
    transform(chunk, encoding, callback) {
      total += chunk.length;
      if (total > maximumBytes) {
        callback(stemsError(413, 'Audio exceeds the technical processing size limit.', 'STEMS_INPUT_TOO_LARGE'));
        return;
      }
      callback(null, chunk);
    },
  });
}

async function downloadS3Object({ client, bucketName, s3Key, inputPath, signal, maximumBytes }) {
  const object = await client.send(
    new GetObjectCommand({ Bucket: bucketName, Key: s3Key }),
    { abortSignal: signal },
  );
  if (!object?.Body || typeof object.Body.pipe !== 'function') {
    throw stemsError(502, 'Audio download stream was unavailable.', 'STEMS_INPUT_DOWNLOAD_FAILED');
  }

  try {
    await pipeline(
      object.Body,
      createByteLimitTransform(maximumBytes),
      fs.createWriteStream(inputPath, { flags: 'wx' }),
      { signal },
    );
  } catch (error) {
    object.Body.destroy?.();
    if (error instanceof RqsHttpError) throw error;
    if (signal.aborted) {
      throw stemsError(499, 'Stems processing was cancelled.', 'STEMS_REQUEST_ABORTED');
    }
    throw stemsError(502, 'Audio download failed.', 'STEMS_INPUT_DOWNLOAD_FAILED');
  }
}

function sendStemsError(res, error, context) {
  const statusCode = Number(error?.statusCode) || 500;
  const code = String(error?.code || 'STEMS_INTERNAL_ERROR');
  if (statusCode >= 500) {
    console.error(`[RQS STEMS] ${context} failed safely: ${code}`);
  }
  if (res.headersSent || res.destroyed || res.writableEnded) return;
  res.status(statusCode).json({
    error: statusCode >= 500 ? 'Stems processing failed safely.' : error.message,
    code,
  });
}

function createAbortContext(req, res) {
  const controller = new AbortController();
  const onRequestAborted = () => controller.abort();
  const onResponseClose = () => {
    if (!res.writableEnded) controller.abort();
  };
  req.once('aborted', onRequestAborted);
  res.once('close', onResponseClose);
  return {
    signal: controller.signal,
    dispose() {
      req.off('aborted', onRequestAborted);
      res.off('close', onResponseClose);
    },
  };
}

function requireActiveRequest(signal) {
  if (signal.aborted) {
    throw stemsError(499, 'Stems processing was cancelled.', 'STEMS_REQUEST_ABORTED');
  }
}

function requireS3Storage(getStorageConfig) {
  const storage = getStorageConfig();
  if (storage.localOutput || !storage.bucketName) {
    throw stemsError(503, 'Stems storage is not configured.', 'STEMS_STORAGE_NOT_CONFIGURED');
  }
  return storage;
}

function createStemsRouter(overrides = {}) {
  const router = express.Router();
  const verifyUser = overrides.verifyUser || verifySupabaseUser;
  const assertOwnedKey = overrides.assertOwnedKey || assertUserOwnedS3Key;
  const getStorageConfig = overrides.getStorageConfig || getMasteringStorageConfig;
  const makeS3Client = overrides.makeS3Client || ((region) => new S3Client({ region }));
  const signUrl = overrides.signUrl || getSignedUrl;
  const probeAudio = overrides.probeAudio || probeAudioFile;
  const runDemucs = overrides.runDemucs || runDemucsProcess;
  const tmpRoot = overrides.tmpRoot || os.tmpdir();
  const maximumBytes = overrides.maxInputBytes || MAX_STEMS_INPUT_BYTES;
  const maximumSeconds = overrides.maxDurationSeconds || MAX_STEMS_DURATION_SECONDS;
  const demucsTimeoutSeconds = Math.min(
    overrides.demucsTimeoutSeconds || DEMUCS_TIMEOUT_SECONDS,
    DEMUCS_TIMEOUT_SECONDS,
  );

  async function requireStemsUser(req, res, next) {
    try {
      req.rqsStemsUser = await verifyUser(req);
      next();
    } catch (error) {
      sendStemsError(res, error, 'authentication');
    }
  }

  const legacyUpload = multer({
    storage: multer.diskStorage({
      destination: (req, file, callback) => callback(null, req.rqsStemsTempDir),
      filename: (req, file, callback) => {
        try {
          const extension = audioExtension(file.originalname);
          callback(null, `input-${crypto.randomUUID()}${extension}`);
        } catch (error) {
          callback(error);
        }
      },
    }),
    limits: { fileSize: maximumBytes, files: 1 },
    fileFilter: (req, file, callback) => {
      try {
        const extension = audioExtension(file.originalname);
        validateContentType(file.mimetype, extension);
        callback(null, true);
      } catch (error) {
        callback(error);
      }
    },
  }).single('audio');

  router.post('/split-s3', requireStemsUser, async (req, res) => {
    const abortContext = createAbortContext(req, res);
    let requestDirectory = null;
    let outputStream = null;
    try {
      const user = req.rqsStemsUser;
      const s3Key = req.body?.s3Key;
      assertOwnedKey(s3Key, user.id);
      const extension = audioExtension(s3Key);
      const storage = requireS3Storage(getStorageConfig);
      const client = makeS3Client(storage.region);

      const metadata = await client.send(
        new HeadObjectCommand({ Bucket: storage.bucketName, Key: s3Key }),
        { abortSignal: abortContext.signal },
      );
      validateInputSize(metadata?.ContentLength, maximumBytes);
      validateContentType(metadata?.ContentType, extension);
      requireActiveRequest(abortContext.signal);

      requestDirectory = await fs.promises.mkdtemp(path.join(tmpRoot, 'rqs-stems-'));
      const inputPath = path.join(requestDirectory, `input${extension}`);
      await downloadS3Object({
        client,
        bucketName: storage.bucketName,
        s3Key,
        inputPath,
        signal: abortContext.signal,
        maximumBytes,
      });
      await probeAudio({
        inputPath,
        extension,
        signal: abortContext.signal,
        maximumSeconds,
      });
      const zipPath = await runDemucs({
        inputPath,
        outputDir: requestDirectory,
        signal: abortContext.signal,
        timeoutSeconds: demucsTimeoutSeconds,
      });
      requireActiveRequest(abortContext.signal);

      const outputKey = `stems/${user.id}/${crypto.randomUUID()}.zip`;
      const outputStat = await fs.promises.stat(zipPath);
      if (!outputStat.isFile() || outputStat.size <= 0) {
        throw stemsError(500, 'Stems processing failed.', 'STEMS_OUTPUT_MISSING');
      }
      outputStream = fs.createReadStream(zipPath);
      try {
        await client.send(
          new PutObjectCommand({
            Bucket: storage.bucketName,
            Key: outputKey,
            Body: outputStream,
            ContentLength: outputStat.size,
            ContentType: 'application/zip',
          }),
          { abortSignal: abortContext.signal },
        );
      } catch (error) {
        outputStream.destroy();
        if (abortContext.signal.aborted) {
          throw stemsError(499, 'Stems processing was cancelled.', 'STEMS_REQUEST_ABORTED');
        }
        throw stemsError(502, 'Stems output upload failed.', 'STEMS_OUTPUT_UPLOAD_FAILED');
      } finally {
        outputStream = null;
      }

      requireActiveRequest(abortContext.signal);
      const downloadUrl = await signUrl(
        client,
        new GetObjectCommand({
          Bucket: storage.bucketName,
          Key: outputKey,
          ResponseContentDisposition: `attachment; filename="${safeDownloadName(s3Key)}"`,
        }),
        { expiresIn: SIGNED_URL_TTL_SECONDS },
      );
      requireActiveRequest(abortContext.signal);
      res.status(200).json({ success: true, downloadUrl });
    } catch (error) {
      outputStream?.destroy();
      if (!abortContext.signal.aborted && !req.aborted && !res.destroyed && !res.writableEnded) {
        sendStemsError(res, error, 'S3 route');
      }
    } finally {
      abortContext.dispose();
      if (requestDirectory) {
        try {
          await fs.promises.rm(requestDirectory, { recursive: true, force: true });
        } catch {
          console.error('[RQS STEMS] cleanup failed safely: STEMS_CLEANUP_FAILED');
        }
      }
    }
  });

  router.post('/split', requireStemsUser, async (req, res) => {
    const abortContext = createAbortContext(req, res);
    let requestDirectory = null;
    try {
      requestDirectory = await fs.promises.mkdtemp(path.join(tmpRoot, 'rqs-stems-'));
      req.rqsStemsTempDir = requestDirectory;
      await new Promise((resolve, reject) => {
        legacyUpload(req, res, (error) => (error ? reject(error) : resolve()));
      });

      if (!req.file) {
        throw stemsError(400, 'One audio file is required.', 'STEMS_INPUT_REQUIRED');
      }
      const extension = audioExtension(req.file.originalname);
      validateInputSize(req.file.size, maximumBytes);
      validateContentType(req.file.mimetype, extension);
      await probeAudio({
        inputPath: req.file.path,
        extension,
        signal: abortContext.signal,
        maximumSeconds,
      });
      const zipPath = await runDemucs({
        inputPath: req.file.path,
        outputDir: requestDirectory,
        signal: abortContext.signal,
        timeoutSeconds: demucsTimeoutSeconds,
      });
      requireActiveRequest(abortContext.signal);

      await new Promise((resolve, reject) => {
        res.download(zipPath, 'rqs_6_stems.zip', (error) => {
          if (error) reject(error);
          else resolve();
        });
      });
    } catch (error) {
      let safeError = error;
      if (error instanceof multer.MulterError) {
        safeError = error.code === 'LIMIT_FILE_SIZE'
          ? stemsError(413, 'Audio exceeds the technical processing size limit.', 'STEMS_INPUT_TOO_LARGE')
          : stemsError(400, 'Invalid audio upload.', 'STEMS_UPLOAD_INVALID');
      }
      if (!abortContext.signal.aborted && !req.aborted && !res.destroyed && !res.writableEnded) {
        sendStemsError(res, safeError, 'legacy route');
      }
    } finally {
      abortContext.dispose();
      if (requestDirectory) {
        try {
          await fs.promises.rm(requestDirectory, { recursive: true, force: true });
        } catch {
          console.error('[RQS STEMS] cleanup failed safely: STEMS_CLEANUP_FAILED');
        }
      }
    }
  });

  return router;
}

const router = createStemsRouter();
module.exports = router;
module.exports.createStemsRouter = createStemsRouter;
module.exports.audioExtension = audioExtension;
module.exports.validateContentType = validateContentType;
module.exports.validateInputSize = validateInputSize;
module.exports.validateProbeResult = validateProbeResult;
module.exports.signalProcessTree = signalProcessTree;
module.exports.runManagedProcess = runManagedProcess;
module.exports.runDemucsProcess = runDemucsProcess;
module.exports.constants = {
  DEMUCS_TIMEOUT_SECONDS,
  MAX_STEMS_DURATION_SECONDS,
  MAX_STEMS_INPUT_BYTES,
  SIGNED_URL_TTL_SECONDS,
};
