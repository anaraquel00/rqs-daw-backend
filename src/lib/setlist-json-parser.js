'use strict';

const express = require('express');
const { MAX_REQUEST_BYTES } = require('./setlist-engine');

const parseSetlistJson = express.json({ limit: MAX_REQUEST_BYTES });

function setlistJsonParser(req, res, next) {
  parseSetlistJson(req, res, (error) => {
    if (!error) {
      next();
      return;
    }
    if (error.type === 'entity.too.large') {
      res.status(413).json({
        error: 'Setlist request is too large.',
        code: 'INVALID_REQUEST',
      });
      return;
    }
    res.status(400).json({
      error: 'Setlist request must be valid JSON.',
      code: 'INVALID_REQUEST',
    });
  });
}

module.exports = { setlistJsonParser };