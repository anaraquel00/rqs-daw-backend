'use strict';

const DEFAULT_ALLOWED_ORIGINS = Object.freeze([
  'http://localhost:4200',
  'https://rqs-daw-frontend.vercel.app',
  'https://studio.raquelsynths.com',
]);

function normalizeOrigin(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  if (raw === '*') {
    throw new Error('RQS_ALLOWED_ORIGINS must not contain wildcard origin "*".');
  }

  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`Invalid origin in RQS_ALLOWED_ORIGINS: ${raw}`);
  }

  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error(`Unsupported origin protocol in RQS_ALLOWED_ORIGINS: ${raw}`);
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error(`Origin must not contain credentials/query/fragment: ${raw}`);
  }
  if (url.pathname !== '/' && url.pathname !== '') {
    throw new Error(`Origin must not contain a path: ${raw}`);
  }

  return url.origin;
}

function getAllowedOrigins() {
  const configured = process.env.RQS_ALLOWED_ORIGINS;
  if (!configured || !String(configured).trim()) {
    return [...DEFAULT_ALLOWED_ORIGINS];
  }

  const origins = String(configured)
    .split(',')
    .map(normalizeOrigin)
    .filter(Boolean);

  const unique = [...new Set(origins)];
  if (unique.length === 0) {
    throw new Error('RQS_ALLOWED_ORIGINS did not contain any valid origins.');
  }
  return unique;
}

function getPaymentMode() {
  const value = String(process.env.RQS_PAYMENT_MODE || 'enabled').trim().toLowerCase();
  if (!['enabled', 'disabled'].includes(value)) {
    throw new Error('RQS_PAYMENT_MODE must be "enabled" or "disabled".');
  }
  return value;
}

module.exports = {
  DEFAULT_ALLOWED_ORIGINS,
  getAllowedOrigins,
  getPaymentMode,
};
