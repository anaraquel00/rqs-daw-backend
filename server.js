const express = require('express');
const cors = require('cors');
const app = express();

app.disable('x-powered-by');

app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    next();
});

// Normalize accidental duplicate path separators before route matching.
app.use((req, res, next) => {
    req.url = req.url.replace(/\/\/+/g, '/');
    next();
});

const corsOptions = {
    origin: [
        'http://localhost:4200',
        'https://rqs-daw-frontend.vercel.app',
        'https://studio.raquelsynths.com'
    ],
    allowedHeaders: ['Content-Type', 'Authorization']
};

app.use(cors(corsOptions));
app.options(/.*/, cors(corsOptions));

// Keep the raw request body for Stripe webhook verification.
app.use(express.json({
    limit: '50mb',
    verify: (req, res, buf) => {
        req.rawBody = buf;
    }
}));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

app.get('/health', (req, res) => {
    res.status(200).json({
        status: 'UP',
        mainframe: 'RQS-DAW Core Active',
        timestamp: new Date().toISOString()
    });
});

const masteringRouter = require('./src/controllers/mastering');
const masteringV2Router = require('./src/controllers/mastering-v2');
const mixRouter = require('./src/controllers/mix-generator');
const videoRouter = require('./src/controllers/video-engine');
const stemsRouter = require('./src/controllers/stem-splitter');
const paymentRouter = require('./src/controllers/payment');

app.use('/mastering', masteringRouter);
app.use('/mastering/v2', masteringV2Router);
app.use('/mix', mixRouter);
app.use('/video', videoRouter);
app.use('/stems', stemsRouter);
app.use('/payment', paymentRouter);

const PORT = process.env.PORT || 8080;
app.listen(PORT, '0.0.0.0', () => {
    console.log(`RQS DSP Core rodando na porta ${PORT}`);
    console.log('[RQS MAINFRAME] Módulos operacionais: [DSP] [DSP_V2] [MIXER] [VIDEO] [STEMS]');
});
