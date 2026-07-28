const express = require('express');
const cors = require('cors');
const app = express();

// 1. Configuração do Objeto de CORS
const corsOptions = {
    origin: [
        'http://localhost:4200', 
        'https://rqs-daw-frontend.vercel.app', 
        'https://studio.raquelsynths.com'
    ],
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization']
};

app.use(cors(corsOptions));

// 🟢 AJUSTE SRE 1: Garante aprovação imediata de preflight em qualquer rota [1]
app.options('*', cors(corsOptions));

// 🟢 AJUSTE SRE 2: Expande os limites de payload JSON para trafegar dados pesados sem travar [1.1.2]
app.use(express.json({ limit: '80mb' }));
app.use(express.urlencoded({ limit: '80mb', extended: true }));

// 🟢 AJUSTE SRE 3: Endpoint de Aquecimento (Warm-up / Health Check)
// Chame essa rota via Angular assim que studio.raquelsynths.com carregar na tela! [1.1.1]
app.get('/api/v1/health', (req, res) => {
    res.status(200).json({
        status: 'UP',
        mainframe: 'RQS-DAW Core Active',
        timestamp: new Date().toISOString()
    });
});

// 🔌 Importando os Motores Modulares
const masteringRouter = require('./src/controllers/mastering');
const mixRouter = require('./src/controllers/mix-generator');
const videoRouter = require('./src/controllers/video-engine');
const stemsRouter = require('./src/controllers/stem-splitter');

// 🛤️ Acoplando as Rotas (A Mágica da Unificação)
app.use('/api/v1/mastering', masteringRouter);
app.use('/api/v1/mix', mixRouter);
app.use('/api/v1/video', videoRouter);
app.use('/api/v1/stems', stemsRouter);

// 🚀 Boot do Sistema (Mapeado para a porta 8080 do AWS Lambda Adapter)
const PORT = process.env.PORT || 8080;
app.listen(PORT, '0.0.0.0', () => {
    console.log(`RQS DSP Core rodando na porta ${PORT}`);
    console.log(`[RQS MAINFRAME] Módulos operacionais: [DSP] [MIXER] [VIDEO] [STEMS]`);
});