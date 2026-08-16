const express = require('express');
const cors = require('cors');

process.env.RQS_MASTERING_V2_LOCAL_OUTPUT = process.env.RQS_MASTERING_V2_LOCAL_OUTPUT || '1';

const masteringV2Router = require('../src/controllers/mastering-v2');

const app = express();
app.disable('x-powered-by');

app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  next();
});

const corsOptions = {
  origin: ['http://localhost:4200', 'http://127.0.0.1:4200'],
  allowedHeaders: ['Content-Type', 'Authorization'],
};

app.use(cors(corsOptions));
app.options(/.*/, cors(corsOptions));
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'UP',
    service: 'RQS Mastering V2 Local Integration',
    localOutput: true,
    timestamp: new Date().toISOString(),
  });
});

app.use('/mastering/v2', masteringV2Router);

const PORT = Number(process.env.PORT || 8080);
app.listen(PORT, '0.0.0.0', () => {
  console.log(`[MASTERING V2 LOCAL] listening on ${PORT}`);
  console.log(`[MASTERING V2 LOCAL] python=${process.env.RQS_PYTHON_BIN || 'auto-detect'}`);
});
