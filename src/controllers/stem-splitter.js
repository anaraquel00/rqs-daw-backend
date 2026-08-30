const express = require('express');

const router = express.Router();

const STEMS_V1_DISABLED_RESPONSE = Object.freeze({
    success: false,
    code: 'STEMS_V1_DISABLED',
    error: 'Stem separation is temporarily unavailable in V1.'
});

function stemsV1Disabled(req, res) {
    return res.status(410).json(STEMS_V1_DISABLED_RESPONSE);
}

// Project 1 V1 intentionally fails closed before upload parsing, S3 access,
// media probing, or Demucs execution. Heavy Stems processing belongs to V2.
router.post('/split-s3', stemsV1Disabled);
router.post('/split', stemsV1Disabled);

module.exports = router;
module.exports.stemsV1Disabled = stemsV1Disabled;
module.exports.STEMS_V1_DISABLED_RESPONSE = STEMS_V1_DISABLED_RESPONSE;
