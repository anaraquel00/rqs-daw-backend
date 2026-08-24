'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pipeline } = require('node:stream/promises');
const express = require('express');
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
  readAuthenticatedProfileRole,
  verifySupabaseUser,
} = require('../lib/supabase-server');
const { getMasteringStorageConfig } = require('../lib/mastering-v2-storage');
const setlistEngine = require('../lib/setlist-engine');
const { setlistJsonParser } = require('../lib/setlist-json-parser');

const DOWNLOAD_URL_TTL_SECONDS = 900;
const UPLOAD_URL_TTL_SECONDS = 900;

function setlistError(statusCode, message, code) {
  return new RqsHttpError(statusCode, message, code);
}

function sanitizeUploadName(value) {
  if (typeof value !== 'string' || !value.trim()) {
    throw setlistError(400, 'Audio filename is required.', 'INVALID_UPLOAD_NAME');
  }
  const baseName = path.basename(value.trim()).slice(0, 180);
  const extension = setlistEngine.extensionForKey(baseName);
  const stem = baseName
    .slice(0, -extension.length)
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 120);
  if (!stem) {
    throw setlistError(400, 'Audio filename has no safe characters.', 'INVALID_UPLOAD_NAME');
  }
  return `${stem}${extension}`;
}

function contentTypeForExtension(extension) {
  return extension === '.mp3' ? 'audio/mpeg' : 'audio/wav';
}

function assertOwnedKey(key, userId, kind) {
  try {
    return assertUserOwnedS3Key(key, userId);
  } catch (error) {
    if (error.code === 'S3_KEY_FORBIDDEN') {
      throw setlistError(403, `${kind} is not owned by the authenticated user.`, 'TRACK_NOT_OWNED');
    }
    if (error.code === 'S3_KEY_INVALID') {
      throw setlistError(400, `${kind} key is invalid.`, 'INVALID_TRACK_KEY');
    }
    throw error;
  }
}

function sendSetlistError(res, error, context) {
  const status = Number(error?.statusCode) || 500;
  const code = String(error?.code || 'SETLIST_INTERNAL_ERROR');
  if (status >= 500) {
    console.error(`[RQS SETLIST] ${context} failed safely:`, code);
  }
  if (res.headersSent) return;
  res.status(status).json({
    error: status >= 500 ? 'Setlist service failed safely.' : error.message,
    code,
  });
}

function enforceSetlistPlanLimit(plan, role) {
  if (role !== 'free' && role !== 'premium') {
    throw setlistError(403, 'Canonical user profile is invalid.', 'SETLIST_PROFILE_INVALID');
  }
  const maximumTracks = role === 'premium' ? 8 : 3;
  if (plan.tracks.length > maximumTracks) {
    throw setlistError(
      403,
      'Setlist music track limit exceeded for the authenticated plan.',
      'SETLIST_PLAN_LIMIT_EXCEEDED',
    );
  }
}

function createSetlistRouter(overrides = {}) {
  const router = express.Router();
  const verifyUser = overrides.verifyUser || verifySupabaseUser;
  const readProfileRole = overrides.readProfileRole || readAuthenticatedProfileRole;
  const getStorageConfig = overrides.getStorageConfig || getMasteringStorageConfig;
  const makeS3Client = overrides.makeS3Client || ((region) => new S3Client({ region }));
  const signUrl = overrides.signUrl || getSignedUrl;
  const renderSetlist = overrides.renderSetlist || setlistEngine.renderSetlistToFile;
  const tmpRoot = overrides.tmpRoot || os.tmpdir();

  async function requireSetlistUser(req, res, next) {
    try {
      req.rqsSetlistUser = await verifyUser(req);
      next();
    } catch (error) {
      sendSetlistError(res, error, 'authentication');
    }
  }

  router.get('/presigned-url', requireSetlistUser, async (req, res) => {
    try {
      const storage = getStorageConfig();
      if (storage.localOutput || !storage.bucketName) {
        throw setlistError(503, 'Setlist S3 storage is not configured.', 'SETLIST_STORAGE_NOT_CONFIGURED');
      }
      const user = req.rqsSetlistUser;
      const safeName = sanitizeUploadName(req.query.filename);
      const extension = setlistEngine.extensionForKey(safeName);
      const contentType = contentTypeForExtension(extension);
      const s3Key = `uploads/${user.id}/setlist/${crypto.randomUUID()}_${safeName}`;
      const client = makeS3Client(storage.region);
      const uploadUrl = await signUrl(
        client,
        new PutObjectCommand({
          Bucket: storage.bucketName,
          Key: s3Key,
          ContentType: contentType,
        }),
        { expiresIn: UPLOAD_URL_TTL_SECONDS },
      );
      res.status(200).json({ uploadUrl, s3Key });
    } catch (error) {
      sendSetlistError(res, error, 'presigned upload');
    }
  });

  router.post('/generate-s3', requireSetlistUser, setlistJsonParser, async (req, res) => {
    let requestDirectory = null;
    const cleanupRequestDirectory = async () => {
      if (!requestDirectory) return;
      const directory = requestDirectory;
      requestDirectory = null;
      try {
        await fs.promises.rm(directory, { recursive: true, force: true });
      } catch (cleanupError) {
        console.error('[RQS SETLIST] temporary cleanup failed:', cleanupError.message);
      }
    };
    const abortController = new AbortController();
    const onAborted = () => abortController.abort();
    req.once('aborted', onAborted);

    try {
      const plan = setlistEngine.validateSetlistRequest(req.body);
      const user = req.rqsSetlistUser;
      const role = await readProfileRole(req, user.id);
      enforceSetlistPlanLimit(plan, role);
      plan.tracks.forEach((key, index) => assertOwnedKey(key, user.id, `Music track ${index + 1}`));
      if (plan.vignette) assertOwnedKey(plan.vignette, user.id, 'Vignette');

      const storage = getStorageConfig();
      if (storage.localOutput || !storage.bucketName) {
        throw setlistError(503, 'Setlist S3 storage is not configured.', 'SETLIST_STORAGE_NOT_CONFIGURED');
      }
      const client = makeS3Client(storage.region);
      const inputs = [
        ...plan.tracks.map((key, index) => ({ key, kind: 'track', index })),
        ...(plan.vignette ? [{ key: plan.vignette, kind: 'vignette', index: 0 }] : []),
      ];

      const sizes = await Promise.all(inputs.map(async (input) => {
        const metadata = await client.send(
          new HeadObjectCommand({ Bucket: storage.bucketName, Key: input.key }),
          { abortSignal: abortController.signal },
        );
        return setlistEngine.validateObjectSize(
          metadata.ContentLength,
          input.kind === 'track' ? `Music track ${input.index + 1}` : 'Vignette',
        );
      }));
      setlistEngine.validateTotalInputSize(sizes);

      requestDirectory = await fs.promises.mkdtemp(path.join(tmpRoot, 'rqs-setlist-'));
      const musicPaths = [];
      let vignettePath = null;

      for (const input of inputs) {
        const extension = setlistEngine.extensionForKey(input.key);
        const localName = input.kind === 'track'
          ? `music_${String(input.index + 1).padStart(2, '0')}${extension}`
          : `vignette${extension}`;
        const localPath = path.join(requestDirectory, localName);
        const object = await client.send(
          new GetObjectCommand({ Bucket: storage.bucketName, Key: input.key }),
          { abortSignal: abortController.signal },
        );
        if (!object.Body || typeof object.Body.pipe !== 'function') {
          throw setlistError(502, 'S3 input stream was unavailable.', 'INPUT_DOWNLOAD_FAILED');
        }
        await pipeline(
          object.Body,
          fs.createWriteStream(localPath, { flags: 'wx' }),
          { signal: abortController.signal },
        );
        if (input.kind === 'track') musicPaths.push(localPath);
        else vignettePath = localPath;
      }

      const outputPath = path.join(requestDirectory, 'setlist-output.wav');
      const renderMetadata = await renderSetlist({
        trackPaths: musicPaths,
        vignettePath,
        plan,
        outputPath,
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        throw setlistError(499, 'Setlist request was cancelled.', 'REQUEST_ABORTED');
      }

      const outputKey = `outputs/${user.id}/setlists/${crypto.randomUUID()}.wav`;
      const outputStat = await fs.promises.stat(outputPath);
      const outputStream = fs.createReadStream(outputPath);
      try {
        await client.send(
          new PutObjectCommand({
            Bucket: storage.bucketName,
            Key: outputKey,
            Body: outputStream,
            ContentLength: outputStat.size,
            ContentType: setlistEngine.OUTPUT_CONTENT_TYPE,
          }),
          { abortSignal: abortController.signal },
        );
      } catch (error) {
        outputStream.destroy();
        if (error instanceof RqsHttpError) throw error;
        throw setlistError(502, 'Setlist output upload failed.', 'OUTPUT_UPLOAD_FAILED');
      }

      const downloadName = `${plan.exportName}.wav`;
      const downloadUrl = await signUrl(
        client,
        new GetObjectCommand({
          Bucket: storage.bucketName,
          Key: outputKey,
          ResponseContentDisposition: `attachment; filename="${downloadName}"`,
        }),
        { expiresIn: DOWNLOAD_URL_TTL_SECONDS },
      );

      await cleanupRequestDirectory();
      res.status(200).json({
        success: true,
        downloadUrl,
        fileName: downloadName,
        output: {
          format: setlistEngine.OUTPUT_FORMAT,
          codec: renderMetadata.outputCodec,
          sampleRate: renderMetadata.outputSampleRate,
          channels: renderMetadata.outputChannels,
          durationSeconds: renderMetadata.outputDuration,
        },
      });
    } catch (error) {
      await cleanupRequestDirectory();
      if (!req.aborted) sendSetlistError(res, error, 'render');
    } finally {
      req.off('aborted', onAborted);
    }
  });

  router.post('/generate', (req, res) => {
    res.status(410).json({
      error: 'Legacy Setlist upload is retired. Use authenticated Setlist Stage 1 S3 routes.',
      code: 'LEGACY_SETLIST_ROUTE_RETIRED',
    });
  });

  return router;
}

const router = createSetlistRouter();
module.exports = router;
module.exports.createSetlistRouter = createSetlistRouter;
module.exports.sanitizeUploadName = sanitizeUploadName;
module.exports.enforceSetlistPlanLimit = enforceSetlistPlanLimit;
