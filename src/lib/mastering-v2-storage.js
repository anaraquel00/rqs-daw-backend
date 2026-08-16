'use strict';

const { RqsHttpError } = require('./supabase-server');

const DEFAULT_AWS_REGION = 'sa-east-1';
const PRODUCTION_BUCKET_NAME = 'amzn-rqs-bunker-sa';
const VALID_STORAGE_ENVIRONMENTS = new Set(['staging', 'production']);

function optionalEnv(name) {
  return String(process.env[name] || '').trim();
}

function storageConfigError(message, code = 'MASTERING_STORAGE_NOT_CONFIGURED') {
  return new RqsHttpError(503, message, code);
}

function getMasteringStorageConfig() {
  const localOutput = process.env.RQS_MASTERING_V2_LOCAL_OUTPUT === '1';
  const region = optionalEnv('RQS_MASTERING_V2_AWS_REGION') || DEFAULT_AWS_REGION;

  if (localOutput) {
    return {
      environment: 'local',
      region,
      bucketName: null,
      localOutput: true,
    };
  }

  const environment = optionalEnv('RQS_MASTERING_V2_STORAGE_ENV').toLowerCase();
  const bucketName = optionalEnv('RQS_MASTERING_V2_BUCKET_NAME');

  if (!VALID_STORAGE_ENVIRONMENTS.has(environment)) {
    throw storageConfigError(
      'Mastering storage environment must be explicitly configured as staging or production.',
    );
  }

  if (!bucketName) {
    throw storageConfigError('Mastering storage bucket is not configured.');
  }

  if (environment === 'staging' && bucketName === PRODUCTION_BUCKET_NAME) {
    throw storageConfigError(
      'Staging Mastering storage cannot use the production bucket.',
      'MASTERING_STORAGE_ENV_MISMATCH',
    );
  }

  if (environment === 'production' && bucketName !== PRODUCTION_BUCKET_NAME) {
    throw storageConfigError(
      'Production Mastering storage bucket does not match the approved production bucket.',
      'MASTERING_STORAGE_ENV_MISMATCH',
    );
  }

  return {
    environment,
    region,
    bucketName,
    localOutput: false,
  };
}

module.exports = {
  DEFAULT_AWS_REGION,
  PRODUCTION_BUCKET_NAME,
  getMasteringStorageConfig,
};
