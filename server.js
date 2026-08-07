const express = require('express');
const cors = require('cors');
const app = express();

// 🟢 PROTEÇÃO SRE (Barra Dupla): Corrige requisições com //mastering/ de forma automática [1]
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
app.options(/.*/, cors(corsOptions)); // Express 5 RegExp

// 🟢 AJUSTE DE PARSER SRE: Salva o buffer binário original em req.rawBody para a validação do Stripe! [1]
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

// Importando os Motores Modulares
const masteringRouter = require('./src/controllers/mastering');
const mixRouter = require('./src/controllers/mix-generator');
const videoRouter = require('./src/controllers/video-engine');
const stemsRouter = require('./src/controllers/stem-splitter');
const paymentRouter = require('./src/controllers/payment'); // 🟢 NOVO MÓDULO DE PAGAMENTOS

// Endpoints sincronizados com a Vercel
app.use('/mastering', masteringRouter);
app.use('/mix', mixRouter);
app.use('/video', videoRouter);
app.use('/stems', stemsRouter);
app.use('/payment', paymentRouter); // 🟢 Rota ativa em https://(seu-lambda-url)/payment/stripe-webhook

const PORT = process.env.PORT || 8080;
app.listen(PORT, '0.0.0.0', () => {
    console.log(`RQS DSP Core rodando na porta ${PORT}`);
    console.log(`[RQS MAINFRAME] Módulos operacionais: [DSP] [MIXER] [VIDEO] [STEMS]`);
});

server.keepAliveTimeout = 120000;
server.headersTimeout = 120000;
