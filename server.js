const express = require('express');
const cors = require('cors');
const app = express();

// 🛡️ O Patch de Segurança (Aceita localhost e a futura Vercel)
app.use(cors({
    origin: ['http://localhost:4200', 
        'https://rqs-daw-frontend.vercel.app', 
        'https://studio.raquelsynths.com.br'],
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization']
        
}));
app.use(express.json());

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

// 🚀 Boot do Sistema
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`[RQS MAINFRAME] Sistema unificado online na porta ${PORT}`);
    console.log(`[RQS MAINFRAME] Módulos operacionais: [DSP] [MIXER] [VIDEO] [STEMS]`);
});