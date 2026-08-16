import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

process.env.SUPABASE_URL = 'https://supabase.example.invalid';
process.env.SUPABASE_SECRET_KEY = 'test-service-secret';

const {
  RqsHttpError,
  extractBearerToken,
  verifySupabaseUser,
  assertUserOwnedS3Key,
  reserveMasteringQuota,
} = require('../src/lib/supabase-server');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function expectHttpError(promiseFactory, statusCode, code) {
  let caught = null;
  try {
    await promiseFactory();
  } catch (error) {
    caught = error;
  }
  assert(caught instanceof RqsHttpError, `Expected RqsHttpError, got ${caught?.constructor?.name}`);
  assert(caught.statusCode === statusCode, `Expected HTTP ${statusCode}, got ${caught.statusCode}`);
  assert(caught.code === code, `Expected code ${code}, got ${caught.code}`);
}

await expectHttpError(
  async () => extractBearerToken({ headers: {} }),
  401,
  'AUTH_REQUIRED',
);

let observedAuthCall = null;
globalThis.fetch = async (url, options) => {
  observedAuthCall = { url, options };
  return new Response(
    JSON.stringify({ id: '11111111-1111-4111-8111-111111111111', email: 'test@example.invalid' }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  );
};

const user = await verifySupabaseUser({
  headers: { authorization: 'Bearer user-access-token' },
});

assert(user.id === '11111111-1111-4111-8111-111111111111', 'Unexpected verified user id.');
assert(
  observedAuthCall.url === 'https://supabase.example.invalid/auth/v1/user',
  'Unexpected Supabase Auth URL.',
);
assert(
  observedAuthCall.options.headers.Authorization === 'Bearer user-access-token',
  'User bearer token was not forwarded to Supabase Auth.',
);
assert(
  observedAuthCall.options.headers.apikey === 'test-service-secret',
  'Server API key header missing.',
);

assertUserOwnedS3Key(
  'uploads/11111111-1111-4111-8111-111111111111/123_track.wav',
  '11111111-1111-4111-8111-111111111111',
);

await expectHttpError(
  async () => assertUserOwnedS3Key(
    'uploads/22222222-2222-4222-8222-222222222222/123_track.wav',
    '11111111-1111-4111-8111-111111111111',
  ),
  403,
  'S3_KEY_FORBIDDEN',
);

let observedAdminCall = null;
globalThis.fetch = async (url, options) => {
  observedAdminCall = { url, options };
  return new Response(
    JSON.stringify({ code: 'P0001', message: 'MASTERING_QUOTA_EXCEEDED' }),
    { status: 400, headers: { 'content-type': 'application/json' } },
  );
};

await expectHttpError(
  async () => reserveMasteringQuota(
    '11111111-1111-4111-8111-111111111111',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  ),
  429,
  'MASTERING_QUOTA_EXCEEDED',
);

assert(
  observedAdminCall.options.headers.apikey === 'test-service-secret',
  'Secret API key must be sent through apikey for admin RPC.',
);
assert(
  observedAdminCall.options.headers.Authorization === undefined,
  'Non-JWT secret API key must not be sent as Authorization Bearer.',
);

console.log('MASTERING_V2_AUTH_UNIT: PASS');
console.log('MASTERING_V2_S3_OWNERSHIP_UNIT: PASS');
console.log('MASTERING_V2_QUOTA_ERROR_MAPPING: PASS');
