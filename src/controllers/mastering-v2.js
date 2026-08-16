'use strict';

const express = require('express');
const multer = require('multer');
const { spawn } = require('child_process');
const crypto = require('crypto');
const os = require('os');
const path = require('path');
const fs = require('fs');

const {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  DeleteObjectCommand,
} = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
const {
  RqsHttpError,
  verifySupabaseUser,
  assertUserOwnedS3Key,
  reserveMasteringQuota,
  confirmMasteringQuota,
  releaseMasteringQuota,
} = require('../lib/supabase-server');
const { getMasteringStorageConfig } = require('../lib/mastering-v2-storage');

const router = express.Router();
const TMP_DIR = os.tmpdir();
const MAX_DIRECT_UPLOAD_BYTES = 1024 * 1024 * 1024;
const MAX_S3_INPUT_BYTES = MAX_DIRECT_UPLOAD_BYTES;
const ALLOWED_AUDIO_EXTENSIONS = new Set(['.wav', '.mp3']);
const LOCAL_OUTPUT_MODE = process.env.RQS_MASTERING_V2_LOCAL_OUTPUT === '1';
const ALLOW_DIRECT_UPLOAD = LOCAL_OUTPUT_MODE || process.env.RQS_MASTERING_V2_DIRECT_UPLOAD === '1';
const LOCAL_DOWNLOAD_TTL_MS = 15 * 60 * 1000;
const LOCAL_TEST_USER_ID = '00000000-0000-4000-8000-000000000001';

function allowedAudioExtension(filename) {
  const extension = path.extname(filename || '').toLowerCase();
  return ALLOWED_AUDIO_EXTENSIONS.has(extension) ? extension : null;
}

function sanitizeUploadName(value) {
  const safe = path.basename(String(value || 'audio.wav'))
    .replace(/[\u2010-\u2015]/g, '-')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9._,-]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
  return safe || 'audio.wav';
}

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, TMP_DIR),
  filename: (req, file, cb) => {
    const extension = allowedAudioExtension(file.originalname) || '.bin';
    cb(null, `v2_input_${crypto.randomUUID()}${extension}`);
  },
});

const upload = multer({
  storage,
  limits: {
    fileSize: MAX_DIRECT_UPLOAD_BYTES,
    files: 1,
    fields: 16,
  },
  fileFilter: (req, file, cb) => {
    if (!allowedAudioExtension(file.originalname)) {
      const error = new Error('Direct audio upload accepts WAV or MP3 files only.');
      error.statusCode = 400;
      return cb(error);
    }
    return cb(null, true);
  },
});

const s3Clients = new Map();

function getS3Client(region) {
  if (!s3Clients.has(region)) {
    s3Clients.set(region, new S3Client({
      region,
      requestChecksumCalculation: 'WHEN_REQUIRED',
    }));
  }
  return s3Clients.get(region);
}

const PYTHON_BIN = process.env.RQS_PYTHON_BIN
  || (fs.existsSync('/opt/venv/bin/python3')
    ? '/opt/venv/bin/python3'
    : (process.platform === 'win32' ? 'python' : 'python3'));
const PYTHON_MODULE = 'src.controllers.mastering_v2_cli';
const localDownloads = new Map();
let capabilitiesCache = null;

function runPython(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON_BIN, ['-m', PYTHON_MODULE, ...args], {
      cwd: path.resolve(__dirname, '../..'),
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', data => { stdout += data.toString(); });
    child.stderr.on('data', data => { stderr += data.toString(); });
    child.on('error', reject);
    child.on('close', code => resolve({ code, stdout, stderr }));
  });
}

function safeUnlink(filePath) {
  if (!filePath) return;
  try {
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
  } catch (error) {
    console.warn(`[MASTERING V2] Cleanup warning for ${filePath}:`, error);
  }
}

async function safeDeleteS3(key) {
  if (!key) return;
  try {
    const storageConfig = getMasteringStorageConfig();
    const s3Client = getS3Client(storageConfig.region);
    await s3Client.send(new DeleteObjectCommand({
      Bucket: storageConfig.bucketName,
      Key: key,
    }));
  } catch (error) {
    console.warn('[MASTERING V2] S3 cleanup warning.');
  }
}

function sanitizeBaseName(value) {
  return value
    .replace(/[\u2010-\u2015]/g, '-')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9\s_,-]/g, '')
    .trim() || 'RQS_Track';
}

function originalNameFromRequest(s3Key, uploadedFile) {
  if (s3Key) {
    return path.basename(s3Key)
      .replace(/^\d+_[0-9a-f-]+_/i, '')
      .replace(/^\d+_/, '')
      .replace(/\.[^/.]+$/, '');
  }
  if (uploadedFile) {
    return uploadedFile.originalname.replace(/\.[^/.]+$/, '');
  }
  return 'RQS_Track';
}

function parseOptionalNumber(value, fieldName) {
  if (value === undefined || value === null || value === '') return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    const error = new Error(`${fieldName} must be a finite number.`);
    error.statusCode = 400;
    throw error;
  }
  return parsed;
}

function registerLocalDownload(filePath, fileName, req) {
  const token = crypto.randomUUID();
  const expiresAt = Date.now() + LOCAL_DOWNLOAD_TTL_MS;
  const timer = setTimeout(() => {
    const entry = localDownloads.get(token);
    if (entry) {
      localDownloads.delete(token);
      safeUnlink(entry.filePath);
    }
  }, LOCAL_DOWNLOAD_TTL_MS);
  if (typeof timer.unref === 'function') timer.unref();

  localDownloads.set(token, { filePath, fileName, expiresAt, timer });
  return `${req.protocol}://${req.get('host')}/mastering/v2/local-download/${token}`;
}

async function resolveRequestUser(req) {
  if (LOCAL_OUTPUT_MODE) {
    return { id: LOCAL_TEST_USER_ID, local: true };
  }
  return verifySupabaseUser(req);
}

async function requireMasteringUser(req, res, next) {
  try {
    req.rqsMasteringUser = await resolveRequestUser(req);
    return next();
  } catch (error) {
    const status = error.statusCode || 500;
    if (status >= 500) {
      console.error('[MASTERING V2] authentication middleware error:', error);
    }
    return res.status(status).json({
      error: status >= 500 ? 'Authentication service unavailable.' : error.message,
      ...(error.code ? { code: error.code } : {}),
    });
  }
}

async function resolveInput(req, user) {
  const uploadedFile = req.file || null;
  const s3Key = req.body.s3Key;

  if (uploadedFile) {
    if (!ALLOW_DIRECT_UPLOAD) {
      safeUnlink(uploadedFile.path);
      const error = new Error('Direct Mastering V2 upload is disabled outside the local integration environment.');
      error.statusCode = 400;
      throw error;
    }
    return { inputPath: uploadedFile.path, uploadedFile, s3Key: null };
  }

  if (!s3Key) {
    const error = new Error('No audio input received.');
    error.statusCode = 400;
    throw error;
  }

  if (!LOCAL_OUTPUT_MODE) {
    assertUserOwnedS3Key(s3Key, user.id);
  }

  const extension = path.extname(s3Key).toLowerCase();
  if (!ALLOWED_AUDIO_EXTENSIONS.has(extension)) {
    const error = new Error('S3 audio input must use a WAV or MP3 key.');
    error.statusCode = 400;
    throw error;
  }

  const storageConfig = getMasteringStorageConfig();
  const s3Client = getS3Client(storageConfig.region);
  const inputPath = path.join(TMP_DIR, `v2_s3_input_${crypto.randomUUID()}${extension}`);
  const downloadCommand = new GetObjectCommand({
    Bucket: storageConfig.bucketName,
    Key: s3Key,
  });
  const response = await s3Client.send(downloadCommand);
  const contentLength = Number(response.ContentLength);

  if (!Number.isFinite(contentLength) || contentLength < 0) {
    response.Body?.destroy?.();
    throw new RqsHttpError(502, 'S3 audio size could not be verified.', 'S3_INPUT_SIZE_UNKNOWN');
  }

  if (contentLength > MAX_S3_INPUT_BYTES) {
    response.Body?.destroy?.();
    throw new RqsHttpError(413, 'S3 audio input exceeds the 1 GiB limit.', 'S3_INPUT_TOO_LARGE');
  }

  const fileStream = fs.createWriteStream(inputPath, { flags: 'wx' });

  await new Promise((resolve, reject) => {
    response.Body.pipe(fileStream);
    response.Body.on('error', reject);
    fileStream.on('error', reject);
    fileStream.on('finish', resolve);
  });

  return { inputPath, uploadedFile: null, s3Key };
}

function buildRenderArgs(body, inputPath, outputPath) {
  const intensityPercent = parseOptionalNumber(body.intensity_percent, 'intensity_percent');
  if (intensityPercent === null) {
    const error = new Error('intensity_percent is required.');
    error.statusCode = 400;
    throw error;
  }

  const args = [
    'render',
    '--input', inputPath,
    '--output', outputPath,
    '--destination', body.destination || '',
    '--atmosphere', body.atmosphere || '',
    '--intensity-percent', String(intensityPercent),
    '--soundcloud-mode', body.soundcloud_mode || 'standard',
  ];

  if (body.platform) args.push('--platform', body.platform);
  const requestedLufs = parseOptionalNumber(body.requested_lufs, 'requested_lufs');
  if (requestedLufs !== null) args.push('--requested-lufs', String(requestedLufs));

  const isPreview = body.preview === 'true' || body.preview === true;
  if (isPreview) {
    args.push('--preview');
    const previewStartSeconds = parseOptionalNumber(body.preview_start_seconds, 'preview_start_seconds');
    if (previewStartSeconds !== null) {
      if (previewStartSeconds < 0) {
        const error = new Error('preview_start_seconds must be greater than or equal to 0.');
        error.statusCode = 400;
        throw error;
      }
      args.push('--preview-start-seconds', String(previewStartSeconds));
    }
  }
  return args;
}

function extractCliError(result) {
  const raw = result.stderr.trim();
  if (!raw) return 'Mastering V2 failed.';
  const lastLine = raw.split(/\r?\n/).filter(Boolean).pop();
  try {
    const payload = JSON.parse(lastLine);
    return payload.detail || raw;
  } catch {
    return raw;
  }
}

router.get('/capabilities', async (req, res) => {
  try {
    if (capabilitiesCache) return res.status(200).json(capabilitiesCache);
    const result = await runPython(['capabilities']);
    if (result.code !== 0) {
      console.error('[MASTERING V2] capabilities CLI error:', result.stderr);
      return res.status(500).json({ error: 'Failed to load Mastering V2 contract.' });
    }
    const jsonLine = result.stdout.split(/\r?\n/).filter(Boolean).pop();
    capabilitiesCache = JSON.parse(jsonLine);
    return res.status(200).json(capabilitiesCache);
  } catch (error) {
    console.error('[MASTERING V2] capabilities error:', error);
    return res.status(500).json({ error: 'Failed to load Mastering V2 contract.' });
  }
});

router.get('/presigned-url', requireMasteringUser, async (req, res) => {
  try {
    if (LOCAL_OUTPUT_MODE) {
      return res.status(400).json({ error: 'Presigned upload is not used in local output mode.' });
    }

    const storageConfig = getMasteringStorageConfig();
    const s3Client = getS3Client(storageConfig.region);
    const user = req.rqsMasteringUser;
    const originalName = sanitizeUploadName(req.query.filename);
    const extension = allowedAudioExtension(originalName);
    if (!extension) {
      return res.status(400).json({ error: 'Upload accepts WAV or MP3 files only.' });
    }

    const contentType = extension === '.mp3' ? 'audio/mpeg' : 'audio/wav';
    const s3Key = `uploads/${user.id}/${Date.now()}_${crypto.randomUUID()}_${originalName}`;

    const uploadUrl = await getSignedUrl(
      s3Client,
      new PutObjectCommand({
        Bucket: storageConfig.bucketName,
        Key: s3Key,
        ContentType: contentType,
      }),
      { expiresIn: 900 },
    );

    return res.status(200).json({ uploadUrl, s3Key });
  } catch (error) {
    const status = error.statusCode || 500;
    if (status >= 500) console.error('[MASTERING V2] presigned upload error:', error);
    return res.status(status).json({
      error: status >= 500 ? 'Failed to create secure upload URL.' : error.message,
      ...(error.code ? { code: error.code } : {}),
    });
  }
});

router.get('/local-download/:token', (req, res) => {
  if (!LOCAL_OUTPUT_MODE) {
    return res.status(404).json({ error: 'Local Mastering V2 output mode is disabled.' });
  }

  const entry = localDownloads.get(req.params.token);
  if (!entry || entry.expiresAt <= Date.now()) {
    if (entry) {
      clearTimeout(entry.timer);
      localDownloads.delete(req.params.token);
      safeUnlink(entry.filePath);
    }
    return res.status(404).json({ error: 'Local Mastering V2 output expired.' });
  }

  return res.download(entry.filePath, entry.fileName);
});

router.post('/process', requireMasteringUser, upload.single('audio'), async (req, res) => {
  let inputPath = null;
  let outputPath = null;
  let keepOutputForDownload = false;
  let quotaReservationId = null;
  let quotaReservationUserId = null;
  let uploadedMasterS3Key = null;
  let quotaConfirmed = false;

  try {
    const user = req.rqsMasteringUser;
    const isPreview = req.body.preview === 'true' || req.body.preview === true;

    if (!isPreview && !LOCAL_OUTPUT_MODE) {
      quotaReservationId = crypto.randomUUID();
      quotaReservationUserId = user.id;
      await reserveMasteringQuota(user.id, quotaReservationId);
    }

    const resolved = await resolveInput(req, user);
    inputPath = resolved.inputPath;
    outputPath = path.join(TMP_DIR, `v2_output_${crypto.randomUUID()}.wav`);

    const args = buildRenderArgs(req.body, inputPath, outputPath);

    const result = await runPython(args);
    if (result.code !== 0) {
      const status = result.code === 2 ? 400 : 500;
      const error = new RqsHttpError(
        status,
        status === 400 ? 'Invalid Mastering V2 request.' : 'Mastering V2 processing failed.',
        status === 400 ? 'MASTERING_REQUEST_INVALID' : 'MASTERING_PROCESSING_FAILED',
      );
      if (status === 400) {
        error.details = extractCliError(result);
      } else {
        console.error('[MASTERING V2] processing CLI error:', result.stderr);
      }
      throw error;
    }

    if (isPreview) {
      keepOutputForDownload = true;
      return res.download(outputPath, 'rqs_v2_preview.wav', () => safeUnlink(outputPath));
    }

    const atmosphere = String(req.body.atmosphere || 'clear_sky').toUpperCase();
    const originalName = sanitizeBaseName(originalNameFromRequest(resolved.s3Key, resolved.uploadedFile));
    const cleanMasterName = `RQS_MASTER_V2_${atmosphere}_${originalName}`;

    if (LOCAL_OUTPUT_MODE) {
      keepOutputForDownload = true;
      const fileName = `${cleanMasterName}.wav`;
      const downloadUrl = registerLocalDownload(outputPath, fileName, req);
      return res.status(200).json({
        success: true,
        engine: 'mastering-v2-v1',
        outputMode: 'local',
        downloadUrl,
        fileName,
      });
    }

    const storageConfig = getMasteringStorageConfig();
    const s3Client = getS3Client(storageConfig.region);
    uploadedMasterS3Key = `masters/${user.id}/${cleanMasterName}_${Date.now()}_${crypto.randomUUID()}.wav`;
    const outputStat = await fs.promises.stat(outputPath);
    const outputStream = fs.createReadStream(outputPath);

    try {
      await s3Client.send(new PutObjectCommand({
        Bucket: storageConfig.bucketName,
        Key: uploadedMasterS3Key,
        Body: outputStream,
        ContentLength: outputStat.size,
        ContentType: 'audio/wav',
      }));
    } finally {
      outputStream.destroy();
    }

    const downloadUrl = await getSignedUrl(
      s3Client,
      new GetObjectCommand({
        Bucket: storageConfig.bucketName,
        Key: uploadedMasterS3Key,
        ResponseContentDisposition: `attachment; filename="${cleanMasterName}.wav"`,
      }),
      { expiresIn: 900 },
    );

    await confirmMasteringQuota(user.id, quotaReservationId);
    quotaConfirmed = true;

    return res.status(200).json({
      success: true,
      engine: 'mastering-v2-v1',
      outputMode: 's3',
      downloadUrl,
      fileName: `${cleanMasterName}.wav`,
    });
  } catch (error) {
    if (uploadedMasterS3Key && !quotaConfirmed) {
      await safeDeleteS3(uploadedMasterS3Key);
    }

    if (quotaReservationId && quotaReservationUserId && !quotaConfirmed) {
      try {
        await releaseMasteringQuota(quotaReservationUserId, quotaReservationId);
      } catch (releaseError) {
        console.error('[MASTERING V2] quota release failed.');
      }
    }

    const status = error.statusCode || 500;
    if (status >= 500) {
      console.error('[MASTERING V2] request error:', error);
    }

    if (!res.headersSent) {
      return res.status(status).json({
        error: status >= 500 ? 'Internal Mastering V2 error.' : error.message,
        ...(error.code ? { code: error.code } : {}),
        ...(status < 500 && error.details ? { details: error.details } : {}),
      });
    }
  } finally {
    safeUnlink(inputPath);
    if (!keepOutputForDownload) safeUnlink(outputPath);
  }
});

router.use((error, req, res, next) => {
  if (res.headersSent) return next(error);

  if (error instanceof multer.MulterError) {
    const message = error.code === 'LIMIT_FILE_SIZE'
      ? 'Direct audio upload exceeds the 1 GiB limit.'
      : 'Invalid Mastering V2 multipart upload.';
    return res.status(400).json({ error: message });
  }

  if (error && error.statusCode === 400) {
    return res.status(400).json({ error: error.message });
  }

  if (error instanceof RqsHttpError) {
    return res.status(error.statusCode).json({ error: error.message, code: error.code });
  }

  console.error('[MASTERING V2] upload middleware error:', error);
  return res.status(500).json({ error: 'Internal Mastering V2 upload error.' });
});

module.exports = router;
