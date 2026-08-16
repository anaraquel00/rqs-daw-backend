'use strict';

class RqsHttpError extends Error {
  constructor(statusCode, message, code = 'RQS_ERROR') {
    super(message);
    this.name = 'RqsHttpError';
    this.statusCode = statusCode;
    this.code = code;
  }
}

function requireEnv(name) {
  const value = process.env[name];
  if (!value || !String(value).trim()) {
    throw new RqsHttpError(500, `Server configuration missing: ${name}.`, 'SERVER_CONFIG_MISSING');
  }
  return String(value).trim();
}

function getSupabaseConfig() {
  return {
    url: requireEnv('SUPABASE_URL').replace(/\/+$/, ''),
    secretKey: requireEnv('SUPABASE_SECRET_KEY'),
  };
}

function extractBearerToken(req) {
  const header = String(req?.headers?.authorization || '').trim();
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match || !match[1].trim()) {
    throw new RqsHttpError(401, 'Authentication required.', 'AUTH_REQUIRED');
  }
  return match[1].trim();
}

async function readJsonSafe(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text.slice(0, 512) };
  }
}

async function supabaseFetch(pathname, {
  method = 'GET',
  userToken = null,
  admin = false,
  body = undefined,
  extraHeaders = {},
} = {}) {
  const { url, secretKey } = getSupabaseConfig();
  const authToken = admin ? secretKey : userToken;

  const headers = {
    apikey: secretKey,
    ...extraHeaders,
  };

  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  return fetch(`${url}${pathname}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function verifySupabaseUser(req) {
  const token = extractBearerToken(req);
  let response;

  try {
    response = await supabaseFetch('/auth/v1/user', { userToken: token });
  } catch (error) {
    if (error instanceof RqsHttpError) throw error;
    throw new RqsHttpError(502, 'Authentication service unavailable.', 'AUTH_UPSTREAM_UNAVAILABLE');
  }

  if (response.status === 401 || response.status === 403) {
    throw new RqsHttpError(401, 'Invalid or expired session.', 'AUTH_INVALID');
  }
  if (!response.ok) {
    throw new RqsHttpError(502, 'Authentication service error.', 'AUTH_UPSTREAM_ERROR');
  }

  const user = await readJsonSafe(response);
  if (!user || typeof user.id !== 'string' || !user.id) {
    throw new RqsHttpError(401, 'Invalid authenticated user.', 'AUTH_USER_INVALID');
  }
  return user;
}

function assertUserOwnedS3Key(s3Key, userId) {
  if (typeof s3Key !== 'string' || !s3Key || s3Key.length > 1024) {
    throw new RqsHttpError(400, 'Invalid S3 audio key.', 'S3_KEY_INVALID');
  }
  const prefix = `uploads/${userId}/`;
  if (!s3Key.startsWith(prefix)) {
    throw new RqsHttpError(403, 'S3 audio key is not owned by the authenticated user.', 'S3_KEY_FORBIDDEN');
  }
  const suffix = s3Key.slice(prefix.length);
  if (!suffix || suffix.includes('\\') || suffix.includes('../') || suffix.includes('/..')) {
    throw new RqsHttpError(400, 'Invalid S3 audio key.', 'S3_KEY_INVALID');
  }
  return s3Key;
}

async function callAdminRpc(functionName, payload) {
  let response;
  try {
    response = await supabaseFetch(
      `/rest/v1/rpc/${encodeURIComponent(functionName)}`,
      {
        method: 'POST',
        admin: true,
        body: payload,
        extraHeaders: { Accept: 'application/json' },
      },
    );
  } catch (error) {
    if (error instanceof RqsHttpError) throw error;
    throw new RqsHttpError(502, 'Database service unavailable.', 'DB_UPSTREAM_UNAVAILABLE');
  }

  const data = await readJsonSafe(response);
  if (!response.ok) {
    const upstreamCode = data?.code || null;
    const upstreamMessage = String(data?.message || '');

    if (
      upstreamCode === 'P0001' &&
      upstreamMessage.includes('MASTERING_QUOTA_EXCEEDED')
    ) {
      throw new RqsHttpError(429, 'Free mastering quota exhausted.', 'MASTERING_QUOTA_EXCEEDED');
    }
    if (
      upstreamMessage.includes('PROFILE_NOT_FOUND') ||
      upstreamMessage.includes('PROFILE_ROLE_') ||
      upstreamMessage.includes('COMPLETED_MASTERS_')
    ) {
      throw new RqsHttpError(403, 'User profile is not eligible for mastering.', 'MASTERING_PROFILE_INVALID');
    }

    throw new RqsHttpError(502, 'Mastering quota service error.', 'MASTERING_QUOTA_UPSTREAM_ERROR');
  }
  return data;
}

async function reserveMasteringQuota(userId, reservationId) {
  return callAdminRpc('reserve_mastering_quota', {
    p_user_id: userId,
    p_reservation_id: reservationId,
  });
}

async function confirmMasteringQuota(userId, reservationId) {
  return callAdminRpc('confirm_mastering_quota', {
    p_user_id: userId,
    p_reservation_id: reservationId,
  });
}

async function releaseMasteringQuota(userId, reservationId) {
  return callAdminRpc('release_mastering_quota', {
    p_user_id: userId,
    p_reservation_id: reservationId,
  });
}

module.exports = {
  RqsHttpError,
  extractBearerToken,
  verifySupabaseUser,
  assertUserOwnedS3Key,
  reserveMasteringQuota,
  confirmMasteringQuota,
  releaseMasteringQuota,
};
