import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  PRODUCTION_BUCKET_NAME,
  getMasteringStorageConfig,
} = require('../src/lib/mastering-v2-storage');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function withEnv(values, callback) {
  const names = Object.keys(values);
  const previous = Object.fromEntries(names.map(name => [name, process.env[name]]));
  try {
    for (const [name, value] of Object.entries(values)) {
      if (value === null || value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
    return callback();
  } finally {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

function expectConfigError(values, expectedCode) {
  let caught = null;
  withEnv(values, () => {
    try {
      getMasteringStorageConfig();
    } catch (error) {
      caught = error;
    }
  });
  assert(caught, `Expected storage config error ${expectedCode}.`);
  assert(caught.statusCode === 503, `Expected HTTP 503, got ${caught.statusCode}.`);
  assert(caught.code === expectedCode, `Expected ${expectedCode}, got ${caught.code}.`);
}

const nonLocalBase = {
  RQS_MASTERING_V2_LOCAL_OUTPUT: null,
  RQS_MASTERING_V2_STORAGE_ENV: null,
  RQS_MASTERING_V2_BUCKET_NAME: null,
  RQS_MASTERING_V2_AWS_REGION: null,
};

expectConfigError(nonLocalBase, 'MASTERING_STORAGE_NOT_CONFIGURED');

expectConfigError({
  ...nonLocalBase,
  RQS_MASTERING_V2_STORAGE_ENV: 'staging',
  RQS_MASTERING_V2_BUCKET_NAME: PRODUCTION_BUCKET_NAME,
}, 'MASTERING_STORAGE_ENV_MISMATCH');

expectConfigError({
  ...nonLocalBase,
  RQS_MASTERING_V2_STORAGE_ENV: 'production',
  RQS_MASTERING_V2_BUCKET_NAME: 'rqs-mastering-staging-example',
}, 'MASTERING_STORAGE_ENV_MISMATCH');

withEnv({
  ...nonLocalBase,
  RQS_MASTERING_V2_STORAGE_ENV: 'staging',
  RQS_MASTERING_V2_BUCKET_NAME: 'rqs-mastering-v2-staging-example',
}, () => {
  const config = getMasteringStorageConfig();
  assert(config.environment === 'staging', 'Staging environment mismatch.');
  assert(config.bucketName === 'rqs-mastering-v2-staging-example', 'Staging bucket mismatch.');
  assert(config.region === 'sa-east-1', 'Default AWS region mismatch.');
  assert(config.localOutput === false, 'Staging must not be local output mode.');
});

withEnv({
  ...nonLocalBase,
  RQS_MASTERING_V2_STORAGE_ENV: 'production',
  RQS_MASTERING_V2_BUCKET_NAME: PRODUCTION_BUCKET_NAME,
}, () => {
  const config = getMasteringStorageConfig();
  assert(config.environment === 'production', 'Production environment mismatch.');
  assert(config.bucketName === PRODUCTION_BUCKET_NAME, 'Production bucket mismatch.');
});

withEnv({
  ...nonLocalBase,
  RQS_MASTERING_V2_LOCAL_OUTPUT: '1',
}, () => {
  const config = getMasteringStorageConfig();
  assert(config.environment === 'local', 'Local environment mismatch.');
  assert(config.bucketName === null, 'Local mode must not require an S3 bucket.');
});

console.log('MASTERING_V2_STORAGE_FAIL_CLOSED: PASS');
console.log('MASTERING_V2_STAGING_PRODUCTION_BUCKET_ISOLATION: PASS');
console.log('MASTERING_V2_LOCAL_STORAGE_BYPASS: PASS');
